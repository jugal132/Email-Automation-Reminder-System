"""
Reminder Manager Module.

Responsible for loading, cleaning, validating, cross-referencing contacts,
and deduplicating reminder records for the Email Automation & Reminder System.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
from src.contact_manager import ContactManager
from src.logger_config import get_logger

logger = get_logger(__name__)

# Base directory for resolving relative paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Supported operational statuses
SUPPORTED_STATUSES: Set[str] = {"pending", "sent", "failed", "cancelled"}

# Required CSV columns for reminders
REQUIRED_COLUMNS: Set[str] = {
    "reminder_id",
    "contact_id",
    "title",
    "subject",
    "message",
    "scheduled_at",
    "status",
}

# Accepted datetime formats (primary: YYYY-MM-DD HH:MM, secondary: YYYY-MM-DD HH:MM:SS)
DATETIME_FORMAT_PRIMARY = "%Y-%m-%d %H:%M"
DATETIME_FORMAT_SECONDARY = "%Y-%m-%d %H:%M:%S"


class ReminderManagerError(Exception):
    """Base exception for all ReminderManager errors."""


class ReminderFileNotFoundError(ReminderManagerError, FileNotFoundError):
    """Raised when the specified reminders CSV file does not exist."""


class ReminderEmptyFileError(ReminderManagerError, ValueError):
    """Raised when the reminders CSV file is empty (0 bytes or no data rows)."""


class ReminderDataError(ReminderManagerError, ValueError):
    """Raised when the CSV structure is invalid or required columns are missing."""


def parse_scheduled_datetime(val: Optional[str]) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Parse a scheduled_at string into a naive local datetime object.

    Expected format: 'YYYY-MM-DD HH:MM'.
    Also tolerates 'YYYY-MM-DD HH:MM:SS' and normalizes it.

    Timezone assumption:
        Naive local datetime values are used throughout this phase. Timezone-aware
        scheduling (e.g. UTC offsets or IANA timezone conversions) is not yet implemented.

    Args:
        val: String representation of date and time.

    Returns:
        Tuple[Optional[datetime], Optional[str]]:
            (parsed_datetime, normalized_string) if valid, or (None, None) if parsing fails.
    """
    if not val or not isinstance(val, str):
        return None, None

    cleaned = val.strip()
    if not cleaned:
        return None, None

    # Try primary format: YYYY-MM-DD HH:MM
    try:
        dt = datetime.strptime(cleaned, DATETIME_FORMAT_PRIMARY)
        return dt, dt.strftime(DATETIME_FORMAT_PRIMARY)
    except ValueError:
        pass

    # Try secondary format with seconds: YYYY-MM-DD HH:MM:SS
    try:
        dt = datetime.strptime(cleaned, DATETIME_FORMAT_SECONDARY)
        return dt, dt.strftime(DATETIME_FORMAT_PRIMARY)
    except ValueError:
        pass

    return None, None


class ReminderManager:
    """
    Manages reminder data ingestion, validation, contact reference checking,
    duplicate detection, and status filtering.
    """

    def __init__(
        self,
        data_source: Optional[str | Path] = None,
        contact_manager: Optional[ContactManager] = None,
        reference_time: Optional[datetime] = None,
    ) -> None:
        """
        Initialize the ReminderManager.

        Args:
            data_source: Path to reminders CSV file. If relative, resolved against project root.
                         Defaults to 'data/reminders.csv'.
            contact_manager: Optional initialized ContactManager instance for contact reference validation.
                             If omitted, an instance is automatically created and loaded.
            reference_time: Optional reference datetime for past/future evaluation (useful for testing).
                            Defaults to datetime.now() (naive local time).
        """
        if data_source is None:
            self.file_path = PROJECT_ROOT / "data" / "reminders.csv"
        else:
            path_obj = Path(data_source)
            self.file_path = path_obj if path_obj.is_absolute() else PROJECT_ROOT / path_obj

        self._contact_manager = contact_manager
        self._reference_time = reference_time or datetime.now()

        # Collections
        self._all_reminders: List[Dict[str, Any]] = []
        self._valid_reminders: List[Dict[str, Any]] = []
        self._invalid_reminders: List[Dict[str, Any]] = []
        self._duplicate_id_reminders: List[Dict[str, Any]] = []
        self._potential_duplicate_reminders: List[Dict[str, Any]] = []
        self._missing_contact_reminders: List[Dict[str, Any]] = []
        self._inactive_contact_reminders: List[Dict[str, Any]] = []

        self._is_loaded: bool = False

    @property
    def is_loaded(self) -> bool:
        """Check if reminders have been loaded and processed."""
        return self._is_loaded

    def set_reference_time(self, ref_time: datetime) -> None:
        """Update reference time for past/future evaluations."""
        self._reference_time = ref_time

    def _get_contact_directory(self) -> Tuple[Dict[str, Dict[str, Any]], Set[str], Set[str]]:
        """
        Retrieve and index contacts by contact_id.

        Returns:
            Tuple[Dict, Set, Set]:
                - all_contacts_by_id: Mapping of contact_id -> contact dictionary
                - valid_contact_ids: Set of contact_ids whose records are valid
                - active_contact_ids: Set of contact_ids who are valid and active
        """
        if self._contact_manager is None:
            self._contact_manager = ContactManager()

        all_contacts = self._contact_manager.get_all_contacts()
        contacts_by_id: Dict[str, Dict[str, Any]] = {}
        valid_ids: Set[str] = set()
        active_ids: Set[str] = set()

        for c in all_contacts:
            cid = str(c.get("contact_id", "")).strip()
            if cid:
                contacts_by_id[cid] = c
                if c.get("is_valid", False):
                    valid_ids.add(cid)
                    if c.get("status", "").lower() == "active":
                        active_ids.add(cid)

        return contacts_by_id, valid_ids, active_ids

    def load_reminders(self) -> List[Dict[str, Any]]:
        """
        Load reminders from CSV, perform structural checks, field validation,
        contact reference verification, date parsing, and deduplication.

        Returns:
            List[Dict[str, Any]]: All processed reminder records.

        Raises:
            ReminderFileNotFoundError: If the CSV file does not exist.
            ReminderEmptyFileError: If the CSV file is 0 bytes or header-only.
            ReminderDataError: If required columns are missing or CSV is malformed.
        """
        if not self.file_path.exists():
            raise ReminderFileNotFoundError(
                f"Reminders file not found at: '{self.file_path.resolve()}'"
            )

        if self.file_path.stat().st_size == 0:
            raise ReminderEmptyFileError(
                f"Reminders file is empty (0 bytes) at: '{self.file_path.resolve()}'"
            )

        try:
            df = pd.read_csv(self.file_path, dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError as exc:
            raise ReminderEmptyFileError(
                f"Reminders file contains no readable data: '{self.file_path.resolve()}'"
            ) from exc
        except Exception as exc:
            raise ReminderDataError(
                f"Failed to parse CSV file '{self.file_path.resolve()}': {exc}"
            ) from exc

        if df.empty:
            raise ReminderEmptyFileError(
                f"Reminders file contains headers but no data records: '{self.file_path.resolve()}'"
            )

        # Normalize column names
        raw_columns = list(df.columns)
        normalized_columns = [str(c).strip().lower() for c in raw_columns]
        df.columns = normalized_columns

        missing_columns = REQUIRED_COLUMNS - set(normalized_columns)
        if missing_columns:
            sorted_missing = sorted(list(missing_columns))
            raise ReminderDataError(
                f"Reminders CSV missing required column(s): {', '.join(sorted_missing)}. "
                f"Found columns: {normalized_columns}"
            )

        # Reset state
        self._all_reminders = []
        self._valid_reminders = []
        self._invalid_reminders = []
        self._duplicate_id_reminders = []
        self._potential_duplicate_reminders = []
        self._missing_contact_reminders = []
        self._inactive_contact_reminders = []

        # Load and index contacts
        contacts_by_id, valid_contact_ids, active_contact_ids = self._get_contact_directory()

        # Tracking registries
        seen_reminder_ids: Dict[str, int] = {}  # reminder_id -> row_index (1-based)
        seen_content_signatures: Dict[Tuple[str, str, str], str] = {}  # (cid, subject, time) -> first reminder_id

        for idx, row in df.iterrows():
            record = self._process_reminder_row(
                row=row.to_dict(),
                row_index=idx,
                contacts_by_id=contacts_by_id,
                valid_contact_ids=valid_contact_ids,
                active_contact_ids=active_contact_ids,
                seen_reminder_ids=seen_reminder_ids,
                seen_content_signatures=seen_content_signatures,
            )
            self._all_reminders.append(record)

            if record["is_duplicate_id"]:
                self._duplicate_id_reminders.append(record)

            if record["is_potential_duplicate"]:
                self._potential_duplicate_reminders.append(record)

            if record["has_missing_contact"]:
                self._missing_contact_reminders.append(record)

            if record["has_inactive_contact"]:
                self._inactive_contact_reminders.append(record)

            if record["is_valid"]:
                self._valid_reminders.append(record)
            else:
                self._invalid_reminders.append(record)

        self._is_loaded = True
        logger.info(
            "Loaded %d reminders from %s: %d valid, %d invalid (%d dup IDs, %d potential dups).",
            len(self._all_reminders),
            self.file_path.name,
            len(self._valid_reminders),
            len(self._invalid_reminders),
            len(self._duplicate_id_reminders),
            len(self._potential_duplicate_reminders),
        )
        return self._all_reminders

    def _process_reminder_row(
        self,
        row: Dict[str, Any],
        row_index: int,
        contacts_by_id: Dict[str, Dict[str, Any]],
        valid_contact_ids: Set[str],
        active_contact_ids: Set[str],
        seen_reminder_ids: Dict[str, int],
        seen_content_signatures: Dict[Tuple[str, str, str], str],
    ) -> Dict[str, Any]:
        """
        Validate and clean a single reminder row.
        """
        errors: List[str] = []
        warnings: List[str] = []
        cleaned: Dict[str, str] = {}

        # 1. Whitespace trimming
        for key, val in row.items():
            cleaned[key] = str(val).strip() if val is not None and not pd.isna(val) else ""

        reminder_id = cleaned.get("reminder_id", "")
        contact_id = cleaned.get("contact_id", "")
        title = cleaned.get("title", "")
        subject = cleaned.get("subject", "")
        message = cleaned.get("message", "")
        raw_scheduled_at = cleaned.get("scheduled_at", "")
        raw_status = cleaned.get("status", "")

        # Normalize status to lowercase
        normalized_status = raw_status.lower()
        cleaned["status"] = normalized_status

        # 2. Required fields presence
        if not reminder_id:
            errors.append("Missing required field: 'reminder_id'")
        if not contact_id:
            errors.append("Missing required field: 'contact_id'")
        if not title:
            errors.append("Missing required field: 'title'")
        if not subject:
            errors.append("Missing required field: 'subject'")
        if not message:
            errors.append("Missing required field: 'message'")
        if not raw_scheduled_at:
            errors.append("Missing required field: 'scheduled_at'")
        if not raw_status:
            errors.append("Missing required field: 'status'")

        # 3. Reminder ID uniqueness
        is_duplicate_id = False
        if reminder_id:
            if reminder_id in seen_reminder_ids:
                is_duplicate_id = True
                first_row = seen_reminder_ids[reminder_id]
                errors.append(
                    f"Duplicate reminder_id '{reminder_id}' (first seen at row {first_row})"
                )
            else:
                seen_reminder_ids[reminder_id] = row_index + 1

        # 4. Status validation
        if raw_status:
            if normalized_status not in SUPPORTED_STATUSES:
                errors.append(
                    f"Unknown status '{raw_status}'. Supported statuses: "
                    f"{', '.join(sorted(SUPPORTED_STATUSES))}"
                )

        # 5. Date and Time parsing
        parsed_dt: Optional[datetime] = None
        normalized_dt_str = raw_scheduled_at
        is_overdue = False

        if raw_scheduled_at:
            parsed_dt, norm_str = parse_scheduled_datetime(raw_scheduled_at)
            if parsed_dt is None:
                errors.append(
                    f"Invalid datetime format: '{raw_scheduled_at}'. Expected format: 'YYYY-MM-DD HH:MM'"
                )
            else:
                normalized_dt_str = norm_str or raw_scheduled_at
                cleaned["scheduled_at"] = normalized_dt_str
                # Past vs Future comparison against reference time
                if parsed_dt < self._reference_time:
                    is_overdue = True

        # 6. Contact reference validation
        has_missing_contact = False
        has_invalid_contact = False
        has_inactive_contact = False
        referenced_contact: Optional[Dict[str, Any]] = None

        if contact_id:
            if contact_id not in contacts_by_id:
                has_missing_contact = True
                errors.append(f"Referenced contact_id '{contact_id}' does not exist in contacts")
            else:
                referenced_contact = contacts_by_id[contact_id]
                if contact_id not in valid_contact_ids:
                    has_invalid_contact = True
                    reasons = "; ".join(referenced_contact.get("validation_errors", []))
                    errors.append(
                        f"Referenced contact_id '{contact_id}' is invalid ({reasons})"
                    )
                elif contact_id not in active_contact_ids:
                    has_inactive_contact = True
                    warnings.append(
                        f"Referenced contact_id '{contact_id}' exists and is valid, but has status 'inactive' (ineligible for automated dispatch)"
                    )

        # 7. Potential duplicate reminder content detection
        # Criteria: same contact_id, same subject (case-insensitive), same normalized scheduled_at
        is_potential_duplicate = False
        if contact_id and subject and normalized_dt_str:
            signature = (contact_id, subject.lower(), normalized_dt_str)
            if signature in seen_content_signatures:
                is_potential_duplicate = True
                first_rid = seen_content_signatures[signature]
                warnings.append(
                    f"Potential duplicate reminder content: matches contact_id '{contact_id}', "
                    f"subject '{subject}', scheduled_at '{normalized_dt_str}' (first seen with reminder_id: '{first_rid}')"
                )
            else:
                seen_content_signatures[signature] = reminder_id or f"row_{row_index+1}"

        is_valid = len(errors) == 0

        # Eligibility for future scheduling:
        # Must be valid, status == 'pending', recipient is active, and not overdue
        is_eligible_for_scheduling = (
            is_valid
            and normalized_status == "pending"
            and not has_inactive_contact
            and not is_overdue
        )

        return {
            "row_index": row_index + 1,
            "reminder_id": reminder_id,
            "contact_id": contact_id,
            "title": title,
            "subject": subject,
            "message": message,
            "scheduled_at": normalized_dt_str,
            "parsed_datetime": parsed_dt,
            "status": normalized_status,
            "is_valid": is_valid,
            "is_duplicate_id": is_duplicate_id,
            "is_potential_duplicate": is_potential_duplicate,
            "is_overdue": is_overdue,
            "has_missing_contact": has_missing_contact,
            "has_invalid_contact": has_invalid_contact,
            "has_inactive_contact": has_inactive_contact,
            "is_eligible_for_scheduling": is_eligible_for_scheduling,
            "validation_errors": errors,
            "validation_warnings": warnings,
            "contact_details": referenced_contact,
            "raw_data": row,
        }

    # -------------------------------------------------------------------------
    # Validation Result Query API
    # -------------------------------------------------------------------------

    def get_all_reminders(self) -> List[Dict[str, Any]]:
        """Retrieve all loaded reminders."""
        if not self._is_loaded:
            self.load_reminders()
        return list(self._all_reminders)

    def get_valid_reminders(self) -> List[Dict[str, Any]]:
        """Retrieve all reminders that passed validation checks."""
        if not self._is_loaded:
            self.load_reminders()
        return list(self._valid_reminders)

    def get_invalid_reminders(self) -> List[Dict[str, Any]]:
        """Retrieve all reminders that failed validation checks."""
        if not self._is_loaded:
            self.load_reminders()
        return list(self._invalid_reminders)

    def get_pending_reminders(self, only_active_contacts: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieve reminders with 'pending' status.

        Args:
            only_active_contacts: If True, only returns pending reminders where the
                                  referenced contact is valid and active. Defaults to True.

        Returns:
            List[Dict[str, Any]]: Pending reminder records.
        """
        if not self._is_loaded:
            self.load_reminders()

        pending = [r for r in self._valid_reminders if r["status"] == "pending"]
        if only_active_contacts:
            return [r for r in pending if not r["has_inactive_contact"]]
        return pending

    def get_overdue_reminders(self) -> List[Dict[str, Any]]:
        """
        Retrieve reminders with valid datetime timestamps that are in the past
        relative to the reference time.
        """
        if not self._is_loaded:
            self.load_reminders()
        return [r for r in self._all_reminders if r["is_overdue"] and r["parsed_datetime"] is not None]

    def get_duplicate_id_reminders(self) -> List[Dict[str, Any]]:
        """Retrieve reminders flagged for possessing duplicate reminder IDs."""
        if not self._is_loaded:
            self.load_reminders()
        return list(self._duplicate_id_reminders)

    def get_potential_duplicate_reminders(self) -> List[Dict[str, Any]]:
        """
        Retrieve reminders identified as potential duplicates based on identical
        contact_id, subject, and scheduled_at.
        """
        if not self._is_loaded:
            self.load_reminders()
        return list(self._potential_duplicate_reminders)

    def get_missing_contact_reminders(self) -> List[Dict[str, Any]]:
        """Retrieve reminders referencing non-existent contact IDs."""
        if not self._is_loaded:
            self.load_reminders()
        return list(self._missing_contact_reminders)

    def get_inactive_contact_reminders(self) -> List[Dict[str, Any]]:
        """Retrieve reminders assigned to existing contacts whose status is inactive."""
        if not self._is_loaded:
            self.load_reminders()
        return list(self._inactive_contact_reminders)

    def get_validation_summary(self) -> Dict[str, Any]:
        """
        Calculate and return validation summary statistics.

        Counting & Category Overlap Rules:
            - total_reminders = valid_reminders + invalid_reminders.
            - invalid_reminders includes records failing required fields, invalid date format,
              unknown status, duplicate IDs, or missing/invalid contact references.
            - duplicate_id_reminders is a subset of invalid_reminders.
            - missing_contact_reminders is a subset of invalid_reminders.
            - inactive_recipient_reminders tracks reminders whose referenced contact is valid
              but has status 'inactive'. (They may be valid structurally, but ineligible for dispatch).
            - potential_duplicate_reminders tracks content duplicates (flagged for review).
            - pending/sent/failed/cancelled counts reflect distribution across valid records.
            - overdue_reminders reflects valid timestamps in the past relative to reference_time.

        Returns:
            Dict[str, Any]: Calculated summary metrics.
        """
        if not self._is_loaded:
            self.load_reminders()

        total = len(self._all_reminders)
        valid = len(self._valid_reminders)
        invalid = len(self._invalid_reminders)
        dup_ids = len(self._duplicate_id_reminders)
        potential_dups = len(self._potential_duplicate_reminders)
        missing_contacts = len(self._missing_contact_reminders)
        inactive_recipients = len(self._inactive_contact_reminders)

        # Status distribution across valid records
        pending = sum(1 for r in self._valid_reminders if r["status"] == "pending")
        sent = sum(1 for r in self._valid_reminders if r["status"] == "sent")
        failed = sum(1 for r in self._valid_reminders if r["status"] == "failed")
        cancelled = sum(1 for r in self._valid_reminders if r["status"] == "cancelled")

        overdue = len(self.get_overdue_reminders())

        return {
            "total_reminders": total,
            "valid_reminders": valid,
            "invalid_reminders": invalid,
            "duplicate_id_reminders": dup_ids,
            "potential_duplicate_reminders": potential_dups,
            "missing_contact_reminders": missing_contacts,
            "inactive_recipient_reminders": inactive_recipients,
            "pending_reminders": pending,
            "sent_reminders": sent,
            "failed_reminders": failed,
            "cancelled_reminders": cancelled,
            "overdue_reminders": overdue,
        }
