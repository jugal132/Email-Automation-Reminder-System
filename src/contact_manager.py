"""
Contact Manager Module.

Responsible for loading, cleaning, validating, deduplicating, and filtering contact records
for the Email Automation & Reminder System.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
from src.logger_config import get_logger

logger = get_logger(__name__)

# Base directory for resolving relative paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# RFC 5322-compliant practical email validation pattern
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*(?:\.[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*)+$"
)

REQUIRED_COLUMNS: Set[str] = {"contact_id", "name", "email", "status"}


class ContactManagerError(Exception):
    """Base exception for all ContactManager-related errors."""


class ContactFileNotFoundError(ContactManagerError, FileNotFoundError):
    """Raised when the specified contact CSV file does not exist."""


class EmptyFileError(ContactManagerError, ValueError):
    """Raised when the contacts CSV file is empty (0 bytes or no data)."""


class ContactDataError(ContactManagerError, ValueError):
    """Raised when the CSV structure is invalid or required columns are missing."""


def validate_email_format(email: Optional[str]) -> bool:
    """
    Validate the structural syntax of an email address using a standard regex pattern.

    Note:
        Format validation evaluates structural compliance only (e.g. user@domain.tld).
        It does NOT confirm whether a physical mailbox exists, nor does it perform
        DNS MX record lookups or communicate with remote mail servers.

    Args:
        email: Email string to validate.

    Returns:
        bool: True if structural syntax is valid, False otherwise.
    """
    if not email or not isinstance(email, str):
        return False
    trimmed = email.strip()
    if not trimmed:
        return False
    return bool(EMAIL_REGEX.match(trimmed))


class ContactManager:
    """
    Manages contact ingestion, cleaning, validation, deduplication, and active filtering.
    """

    def __init__(self, data_source: Optional[str | Path] = None) -> None:
        """
        Initialize the ContactManager.

        Args:
            data_source: Path to contacts CSV file. If relative, it is resolved
                         against the project root directory. Defaults to 'data/contacts.csv'.
        """
        if data_source is None:
            self.file_path = PROJECT_ROOT / "data" / "contacts.csv"
        else:
            path_obj = Path(data_source)
            self.file_path = path_obj if path_obj.is_absolute() else PROJECT_ROOT / path_obj

        self._all_contacts: List[Dict[str, Any]] = []
        self._valid_contacts: List[Dict[str, Any]] = []
        self._invalid_contacts: List[Dict[str, Any]] = []
        self._duplicate_contacts: List[Dict[str, Any]] = []
        self._is_loaded: bool = False

    @property
    def is_loaded(self) -> bool:
        """Indicate whether contacts have been loaded and validated."""
        return self._is_loaded

    def load_contacts(self) -> List[Dict[str, Any]]:
        """
        Load contacts from the configured CSV file, performing structure validation,
        cleaning, validation, and deduplication.

        Returns:
            List[Dict[str, Any]]: List of all processed contact records.

        Raises:
            ContactFileNotFoundError: If the CSV file does not exist.
            EmptyFileError: If the CSV file is completely empty (0 bytes or header-only with no rows).
            ContactDataError: If the CSV structure is malformed or required columns are missing.
        """
        if not self.file_path.exists():
            raise ContactFileNotFoundError(
                f"Contacts file not found at: '{self.file_path.resolve()}'"
            )

        # Check for 0-byte empty file
        if self.file_path.stat().st_size == 0:
            raise EmptyFileError(
                f"Contacts file is empty (0 bytes) at: '{self.file_path.resolve()}'"
            )

        try:
            # Read CSV with pandas, preserving string representations
            df = pd.read_csv(self.file_path, dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError as exc:
            raise EmptyFileError(
                f"Contacts file contains no readable data: '{self.file_path.resolve()}'"
            ) from exc
        except Exception as exc:
            raise ContactDataError(
                f"Failed to parse CSV file '{self.file_path.resolve()}': {exc}"
            ) from exc

        # Check if file has header but zero rows
        if df.empty:
            raise EmptyFileError(
                f"Contacts file contains headers but no data records: '{self.file_path.resolve()}'"
            )

        # Normalize column headers: strip whitespace and lowercase
        raw_columns = list(df.columns)
        normalized_columns = [str(c).strip().lower() for c in raw_columns]
        df.columns = normalized_columns

        # Verify all required columns are present
        missing_columns = REQUIRED_COLUMNS - set(normalized_columns)
        if missing_columns:
            sorted_missing = sorted(list(missing_columns))
            raise ContactDataError(
                f"Contacts CSV missing required column(s): {', '.join(sorted_missing)}. "
                f"Found columns: {normalized_columns}"
            )

        # Reset collections
        self._all_contacts = []
        self._valid_contacts = []
        self._invalid_contacts = []
        self._duplicate_contacts = []

        # Track seen emails for duplicate detection: normalized_email -> first_seen_contact_id
        seen_emails: Dict[str, str] = {}

        # Process and clean each record
        for idx, row in df.iterrows():
            record = self._process_row(row=row.to_dict(), row_index=idx, seen_emails=seen_emails)
            self._all_contacts.append(record)

            if record["is_duplicate"]:
                self._duplicate_contacts.append(record)

            if record["is_valid"]:
                self._valid_contacts.append(record)
            else:
                self._invalid_contacts.append(record)

        self._is_loaded = True
        logger.info(
            "Loaded %d contacts from %s: %d valid, %d invalid (%d duplicates).",
            len(self._all_contacts),
            self.file_path.name,
            len(self._valid_contacts),
            len(self._invalid_contacts),
            len(self._duplicate_contacts),
        )

        return self._all_contacts

    def _process_row(
        self,
        row: Dict[str, Any],
        row_index: int,
        seen_emails: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Clean, validate, and check duplicates for a single contact row.

        Args:
            row: Raw row dictionary from pandas.
            row_index: Row index (0-based) for error reporting.
            seen_emails: Registry mapping normalized emails to the first contact_id seen.

        Returns:
            Dict[str, Any]: Standardized contact dictionary with validation metadata.
        """
        errors: List[str] = []
        cleaned: Dict[str, Any] = {}

        # 1. Clean string fields
        for key, val in row.items():
            if isinstance(val, str):
                cleaned[key] = val.strip()
            else:
                cleaned[key] = "" if val is None or pd.isna(val) else str(val).strip()

        # Preserve IDs without modification other than stripping whitespace
        contact_id = cleaned.get("contact_id", "")
        name = cleaned.get("name", "")
        raw_email = cleaned.get("email", "")
        raw_status = cleaned.get("status", "")
        company = cleaned.get("company", "")

        # Normalize email: lowercase & stripped
        normalized_email = raw_email.lower()
        cleaned["email"] = normalized_email

        # Normalize status: lowercase & stripped
        normalized_status = raw_status.lower()
        cleaned["status"] = normalized_status

        # 2. Validate required fields presence
        if not contact_id:
            errors.append("Missing required field: 'contact_id'")
        if not name:
            errors.append("Missing required field: 'name'")
        if not raw_email:
            errors.append("Missing required field: 'email'")
        if not raw_status:
            errors.append("Missing required field: 'status'")

        # 3. Validate email format (only if email was provided)
        if raw_email:
            if not validate_email_format(normalized_email):
                errors.append(f"Invalid email address format: '{raw_email}'")

        # 4. Duplicate email detection (case-insensitive)
        is_duplicate = False
        if normalized_email and not errors:
            # Check if this email was already registered by an earlier record
            if normalized_email in seen_emails:
                is_duplicate = True
                first_id = seen_emails[normalized_email]
                errors.append(
                    f"Duplicate email address '{normalized_email}' (previously registered by contact_id: '{first_id}')"
                )
            else:
                seen_emails[normalized_email] = contact_id

        is_valid = len(errors) == 0

        # Construct final structured contact record
        return {
            "row_index": row_index + 1,  # 1-based index matching typical CSV lines (excluding header)
            "contact_id": contact_id,
            "name": name,
            "email": normalized_email,
            "company": company,
            "status": normalized_status,
            "is_valid": is_valid,
            "is_duplicate": is_duplicate,
            "validation_errors": errors,
            "raw_data": row,
        }

    def get_all_contacts(self) -> List[Dict[str, Any]]:
        """
        Retrieve all loaded contacts. Automatically loads data if not yet loaded.

        Returns:
            List[Dict[str, Any]]: List of all contact records.
        """
        if not self._is_loaded:
            self.load_contacts()
        return list(self._all_contacts)

    def get_valid_contacts(self) -> List[Dict[str, Any]]:
        """
        Retrieve records that passed all validation checks (required fields, valid format, non-duplicate).

        Returns:
            List[Dict[str, Any]]: List of valid contact records.
        """
        if not self._is_loaded:
            self.load_contacts()
        return list(self._valid_contacts)

    def get_invalid_contacts(self) -> List[Dict[str, Any]]:
        """
        Retrieve records that failed one or more validation checks, with reasons.

        Returns:
            List[Dict[str, Any]]: List of invalid contact records.
        """
        if not self._is_loaded:
            self.load_contacts()
        return list(self._invalid_contacts)

    def get_duplicate_contacts(self) -> List[Dict[str, Any]]:
        """
        Retrieve contact records identified as duplicates of previously encountered records.

        Returns:
            List[Dict[str, Any]]: List of duplicate contact records.
        """
        if not self._is_loaded:
            self.load_contacts()
        return list(self._duplicate_contacts)

    def get_active_contacts(self) -> List[Dict[str, Any]]:
        """
        Retrieve valid contacts that have an active status ('active').
        Inactive, draft, or invalid contacts are excluded.

        Returns:
            List[Dict[str, Any]]: List of active, valid contact records.
        """
        if not self._is_loaded:
            self.load_contacts()
        return [c for c in self._valid_contacts if c["status"] == "active"]

    def get_validation_summary(self) -> Dict[str, Any]:
        """
        Calculate and return validation summary statistics.

        Counting & Overlap Strategy:
            - total_records = valid_records + invalid_records.
            - invalid_records includes records with missing fields, invalid email format,
              and duplicate records.
            - duplicate_records is a subset of invalid_records.
            - valid_records = active_records + inactive_records.
            - active_records: valid contacts where status == 'active'.
            - inactive_records: valid contacts where status != 'active' (e.g., 'inactive', 'draft').

        Returns:
            Dict[str, Any]: Dictionary containing counts and category percentages.
        """
        if not self._is_loaded:
            self.load_contacts()

        total = len(self._all_contacts)
        valid = len(self._valid_contacts)
        invalid = len(self._invalid_contacts)
        duplicates = len(self._duplicate_contacts)
        active = len(self.get_active_contacts())
        inactive = valid - active

        return {
            "total_records": total,
            "valid_records": valid,
            "invalid_records": invalid,
            "duplicate_records": duplicates,
            "active_records": active,
            "inactive_records": inactive,
        }
