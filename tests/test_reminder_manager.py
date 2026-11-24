"""
Unit tests for ReminderManager module.

Tests cover:
- Valid reminder records
- Missing required fields
- Missing required columns
- Missing reminder file handling
- Empty CSV file handling (0-byte and header-only)
- Duplicate reminder IDs detection
- Invalid date formats handling
- Past reminders (overdue) evaluation
- Future reminders evaluation
- Missing contact references handling
- Inactive contacts filtering
- Unknown status rejection
- Status normalization
- Potential duplicate content detection
- Summary statistics accuracy and counting rules
- Pending reminder filtering logic
"""

from datetime import datetime
from pathlib import Path
import pytest

from src.contact_manager import ContactManager
from src.reminder_manager import (
    ReminderDataError,
    ReminderEmptyFileError,
    ReminderFileNotFoundError,
    ReminderManager,
    parse_scheduled_datetime,
)


@pytest.fixture
def mock_contact_manager(tmp_path: Path) -> ContactManager:
    """Fixture providing a ContactManager with known active, inactive, and invalid contacts."""
    contacts_csv = tmp_path / "fixture_contacts.csv"
    contacts_csv.write_text(
        "contact_id,name,email,company,status\n"
        "1,Alice Active,alice@example.com,Acme,active\n"
        "2,Bob Active,bob@example.com,Global,active\n"
        "3,Carol Inactive,carol@example.com,Innovate,inactive\n"
        "4,David Invalid,invalid-email,NextGen,active\n",
        encoding="utf-8",
    )
    cm = ContactManager(data_source=contacts_csv)
    cm.load_contacts()
    return cm


class TestDateTimeParsing:
    """Tests for parse_scheduled_datetime utility function."""

    def test_valid_primary_format(self) -> None:
        """Verify YYYY-MM-DD HH:MM parses cleanly."""
        dt, s = parse_scheduled_datetime("2026-12-01 10:30")
        assert dt == datetime(2026, 12, 1, 10, 30)
        assert s == "2026-12-01 10:30"

    def test_valid_secondary_format_with_seconds(self) -> None:
        """Verify YYYY-MM-DD HH:MM:SS is parsed and normalized to YYYY-MM-DD HH:MM."""
        dt, s = parse_scheduled_datetime("2026-12-01 10:30:45")
        assert dt == datetime(2026, 12, 1, 10, 30, 45)
        assert s == "2026-12-01 10:30"

    def test_invalid_date_formats(self) -> None:
        """Verify malformed date strings return None."""
        invalid_samples = [
            "2026/12/01 10:00",
            "01-12-2026 10:00",
            "not-a-date",
            "2026-12-01",
            "10:00",
            "",
            None,
        ]
        for sample in invalid_samples:
            dt, s = parse_scheduled_datetime(sample)
            assert dt is None
            assert s is None


class TestReminderManagerFileLoading:
    """Tests for file loading, missing files, and structure validation."""

    def test_missing_file_raises_error(self, tmp_path: Path) -> None:
        """Verify ReminderFileNotFoundError is raised for non-existent file."""
        non_existent = tmp_path / "not_found.csv"
        manager = ReminderManager(data_source=non_existent)
        with pytest.raises(ReminderFileNotFoundError) as exc_info:
            manager.load_reminders()
        assert "Reminders file not found" in str(exc_info.value)

    def test_zero_byte_file_raises_error(self, tmp_path: Path) -> None:
        """Verify ReminderEmptyFileError is raised for 0-byte file."""
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text("", encoding="utf-8")
        manager = ReminderManager(data_source=empty_csv)
        with pytest.raises(ReminderEmptyFileError) as exc_info:
            manager.load_reminders()
        assert "empty (0 bytes)" in str(exc_info.value)

    def test_header_only_file_raises_error(self, tmp_path: Path) -> None:
        """Verify ReminderEmptyFileError is raised for header-only file."""
        header_only = tmp_path / "header_only.csv"
        header_only.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n",
            encoding="utf-8",
        )
        manager = ReminderManager(data_source=header_only)
        with pytest.raises(ReminderEmptyFileError) as exc_info:
            manager.load_reminders()
        assert "no data records" in str(exc_info.value)

    def test_missing_required_columns_raises_error(self, tmp_path: Path) -> None:
        """Verify ReminderDataError is raised when mandatory columns are missing."""
        invalid_cols = tmp_path / "missing_cols.csv"
        # Missing 'status' and 'message'
        invalid_cols.write_text(
            "reminder_id,contact_id,title,subject,scheduled_at\n1,1,Title,Sub,2026-12-01 10:00\n",
            encoding="utf-8",
        )
        manager = ReminderManager(data_source=invalid_cols)
        with pytest.raises(ReminderDataError) as exc_info:
            manager.load_reminders()
        assert "missing required column(s)" in str(exc_info.value).lower()
        assert "status" in str(exc_info.value).lower()


class TestReminderValidationAndCleaning:
    """Tests for record validation, cleaning, status handling, and date evaluation."""

    def test_valid_reminder_loading(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """Verify valid reminders pass validation cleanly."""
        csv_file = tmp_path / "valid_reminders.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "101,1,Meeting,Project Update,Check status,2026-12-01 10:00,pending\n"
            "102,2,Billing,Invoice Reminder,Payment due,2026-12-02 14:00,sent\n",
            encoding="utf-8",
        )
        manager = ReminderManager(
            data_source=csv_file,
            contact_manager=mock_contact_manager,
            reference_time=datetime(2026, 11, 24, 12, 0),
        )
        reminders = manager.load_reminders()

        assert len(reminders) == 2
        assert len(manager.get_valid_reminders()) == 2
        assert len(manager.get_invalid_reminders()) == 0

    def test_whitespace_and_status_normalization(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """Verify whitespace is stripped and status is normalized to lowercase."""
        csv_file = tmp_path / "norm_reminders.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "  101  ,  1  ,  Check In  ,  Roadmap  ,  Message Body  ,  2026-12-01 10:00  ,  PENDING  \n",
            encoding="utf-8",
        )
        manager = ReminderManager(
            data_source=csv_file,
            contact_manager=mock_contact_manager,
            reference_time=datetime(2026, 11, 24, 12, 0),
        )
        reminders = manager.load_reminders()
        r = reminders[0]

        assert r["reminder_id"] == "101"
        assert r["contact_id"] == "1"
        assert r["title"] == "Check In"
        assert r["subject"] == "Roadmap"
        assert r["message"] == "Message Body"
        assert r["scheduled_at"] == "2026-12-01 10:00"
        assert r["status"] == "pending"
        assert r["is_valid"] is True

    def test_missing_required_fields_flagged(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """Verify null or whitespace-only required fields are flagged as invalid."""
        csv_file = tmp_path / "missing_fields.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            ",1,Title,Sub,Msg,2026-12-01 10:00,pending\n"
            "2,,Title,Sub,Msg,2026-12-01 10:00,pending\n"
            "3,1,,Sub,Msg,2026-12-01 10:00,pending\n"
            "4,1,Title,,Msg,2026-12-01 10:00,pending\n"
            "5,1,Title,Sub,,2026-12-01 10:00,pending\n"
            "6,1,Title,Sub,Msg,,pending\n"
            "7,1,Title,Sub,Msg,2026-12-01 10:00,\n",
            encoding="utf-8",
        )
        manager = ReminderManager(data_source=csv_file, contact_manager=mock_contact_manager)
        manager.load_reminders()

        invalid = manager.get_invalid_reminders()
        assert len(invalid) == 7
        assert "Missing required field: 'reminder_id'" in invalid[0]["validation_errors"]
        assert "Missing required field: 'contact_id'" in invalid[1]["validation_errors"]
        assert "Missing required field: 'title'" in invalid[2]["validation_errors"]
        assert "Missing required field: 'subject'" in invalid[3]["validation_errors"]
        assert "Missing required field: 'message'" in invalid[4]["validation_errors"]
        assert "Missing required field: 'scheduled_at'" in invalid[5]["validation_errors"]
        assert "Missing required field: 'status'" in invalid[6]["validation_errors"]

    def test_duplicate_reminder_ids(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """Verify duplicate reminder_ids are identified and flagged."""
        csv_file = tmp_path / "dup_ids.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "1,1,Meeting,Update A,Body A,2026-12-01 10:00,pending\n"
            "1,2,Billing,Update B,Body B,2026-12-02 11:00,pending\n",
            encoding="utf-8",
        )
        manager = ReminderManager(data_source=csv_file, contact_manager=mock_contact_manager)
        manager.load_reminders()

        valid = manager.get_valid_reminders()
        invalid = manager.get_invalid_reminders()
        dup_ids = manager.get_duplicate_id_reminders()

        assert len(valid) == 1
        assert len(invalid) == 1
        assert len(dup_ids) == 1
        assert dup_ids[0]["reminder_id"] == "1"
        assert "Duplicate reminder_id '1'" in dup_ids[0]["validation_errors"][0]

    def test_invalid_date_format_flagged(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """Verify invalid date strings are marked invalid."""
        csv_file = tmp_path / "bad_date.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "1,1,Meeting,Update,Body,2026/12/01 10:00,pending\n",
            encoding="utf-8",
        )
        manager = ReminderManager(data_source=csv_file, contact_manager=mock_contact_manager)
        manager.load_reminders()

        invalid = manager.get_invalid_reminders()
        assert len(invalid) == 1
        assert "Invalid datetime format" in invalid[0]["validation_errors"][0]

    def test_past_and_future_reminders(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """
        Verify past dates are marked is_overdue but remain valid (not malformed).
        Future dates are not overdue.
        """
        csv_file = tmp_path / "past_future.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "1,1,Past Reminder,Old Subject,Old Body,2026-11-20 10:00,pending\n"
            "2,2,Future Reminder,New Subject,New Body,2026-12-05 10:00,pending\n",
            encoding="utf-8",
        )
        # Fix reference time to 2026-11-24 12:00
        ref_time = datetime(2026, 11, 24, 12, 0)
        manager = ReminderManager(
            data_source=csv_file, contact_manager=mock_contact_manager, reference_time=ref_time
        )
        manager.load_reminders()

        valid = manager.get_valid_reminders()
        assert len(valid) == 2  # Both are structurally valid!

        overdue = manager.get_overdue_reminders()
        assert len(overdue) == 1
        assert overdue[0]["reminder_id"] == "1"
        assert overdue[0]["is_overdue"] is True

        future_record = [r for r in valid if r["reminder_id"] == "2"][0]
        assert future_record["is_overdue"] is False

    def test_unknown_status_flagged(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """Verify unsupported statuses are flagged with clear errors."""
        csv_file = tmp_path / "unknown_status.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "1,1,Meeting,Update,Body,2026-12-01 10:00,draft\n"
            "2,2,Meeting,Update,Body,2026-12-01 10:00,archived\n",
            encoding="utf-8",
        )
        manager = ReminderManager(data_source=csv_file, contact_manager=mock_contact_manager)
        manager.load_reminders()

        invalid = manager.get_invalid_reminders()
        assert len(invalid) == 2
        assert "Unknown status 'draft'" in invalid[0]["validation_errors"][0]
        assert "Unknown status 'archived'" in invalid[1]["validation_errors"][0]


class TestContactReferenceValidation:
    """Tests for contact relationship integrity."""

    def test_missing_contact_reference(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """Verify reminders referencing non-existent contact_id are marked invalid."""
        csv_file = tmp_path / "missing_contact.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "1,999,Meeting,Update,Body,2026-12-01 10:00,pending\n",
            encoding="utf-8",
        )
        manager = ReminderManager(data_source=csv_file, contact_manager=mock_contact_manager)
        manager.load_reminders()

        invalid = manager.get_invalid_reminders()
        missing_contact_rems = manager.get_missing_contact_reminders()

        assert len(invalid) == 1
        assert len(missing_contact_rems) == 1
        assert "does not exist in contacts" in invalid[0]["validation_errors"][0]

    def test_invalid_contact_reference(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """Verify reminders referencing a contact record that is invalid are marked invalid."""
        csv_file = tmp_path / "invalid_contact.csv"
        # Contact #4 is invalid in mock_contact_manager (bad email)
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "1,4,Meeting,Update,Body,2026-12-01 10:00,pending\n",
            encoding="utf-8",
        )
        manager = ReminderManager(data_source=csv_file, contact_manager=mock_contact_manager)
        manager.load_reminders()

        invalid = manager.get_invalid_reminders()
        assert len(invalid) == 1
        assert "is invalid" in invalid[0]["validation_errors"][0]

    def test_inactive_contact_filtering(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """
        Verify reminders referencing an inactive contact (#3) are identified,
        tracked in get_inactive_contact_reminders, and excluded from active pending reminders.
        """
        csv_file = tmp_path / "inactive_contact.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "1,1,Active Meeting,Sub 1,Msg 1,2026-12-01 10:00,pending\n"
            "2,3,Inactive Meeting,Sub 2,Msg 2,2026-12-02 10:00,pending\n",
            encoding="utf-8",
        )
        manager = ReminderManager(
            data_source=csv_file,
            contact_manager=mock_contact_manager,
            reference_time=datetime(2026, 11, 24, 12, 0),
        )
        manager.load_reminders()

        inactive_rems = manager.get_inactive_contact_reminders()
        assert len(inactive_rems) == 1
        assert inactive_rems[0]["reminder_id"] == "2"
        assert inactive_rems[0]["has_inactive_contact"] is True

        # When filtering pending reminders for active contacts only:
        eligible_pending = manager.get_pending_reminders(only_active_contacts=True)
        assert len(eligible_pending) == 1
        assert eligible_pending[0]["reminder_id"] == "1"

        # When requesting all pending reminders regardless of contact status:
        all_pending = manager.get_pending_reminders(only_active_contacts=False)
        assert len(all_pending) == 2


class TestPotentialDuplicateReminders:
    """Tests for content-based duplicate reminder detection."""

    def test_potential_duplicate_content_flagged(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """
        Verify reminders with same contact_id, subject (case-insensitive),
        and scheduled_at are flagged as potential duplicates.
        """
        csv_file = tmp_path / "potential_dups.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "1,1,Meeting,Project Status,Body A,2026-12-01 10:00,pending\n"
            "2,1,Follow-up,PROJECT STATUS,Body B,2026-12-01 10:00,pending\n"
            "3,2,Meeting,Project Status,Body C,2026-12-01 10:00,pending\n",
            encoding="utf-8",
        )
        manager = ReminderManager(data_source=csv_file, contact_manager=mock_contact_manager)
        manager.load_reminders()

        potential_dups = manager.get_potential_duplicate_reminders()
        assert len(potential_dups) == 1
        assert potential_dups[0]["reminder_id"] == "2"
        assert potential_dups[0]["is_potential_duplicate"] is True
        assert "Potential duplicate reminder content" in potential_dups[0]["validation_warnings"][0]


class TestValidationSummaryAndRealCSV:
    """Tests for summary statistics calculations and real project data."""

    def test_summary_statistics_counts(
        self, tmp_path: Path, mock_contact_manager: ContactManager
    ) -> None:
        """Verify summary metrics calculation and consistency invariants."""
        csv_file = tmp_path / "summary_test.csv"
        csv_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "1,1,Title,Sub 1,Msg,2026-12-01 10:00,pending\n"
            "2,2,Title,Sub 2,Msg,2026-11-20 10:00,sent\n"
            "3,3,Title,Sub 3,Msg,2026-12-05 10:00,pending\n"
            "4,999,Title,Sub 4,Msg,2026-12-10 10:00,pending\n"
            "5,1,Title,Sub 5,Msg,not-a-date,pending\n",
            encoding="utf-8",
        )
        ref_time = datetime(2026, 11, 24, 12, 0)
        manager = ReminderManager(
            data_source=csv_file, contact_manager=mock_contact_manager, reference_time=ref_time
        )
        summary = manager.get_validation_summary()

        assert summary["total_reminders"] == 5
        assert summary["valid_reminders"] == 3    # #1, #2, #3
        assert summary["invalid_reminders"] == 2  # #4 (missing contact 999), #5 (bad date)
        assert summary["missing_contact_reminders"] == 1
        assert summary["inactive_recipient_reminders"] == 1  # #3 (contact 3 is inactive)
        assert summary["sent_reminders"] == 1     # #2
        assert summary["pending_reminders"] == 2  # #1, #3
        assert summary["overdue_reminders"] == 1  # #2 (scheduled 2026-11-20 < ref_time)

        # Invariant check
        assert summary["total_reminders"] == summary["valid_reminders"] + summary["invalid_reminders"]

    def test_real_project_sample_reminders_csv(self) -> None:
        """Verify the actual data/reminders.csv in the project passes validation."""
        cm = ContactManager()
        manager = ReminderManager(contact_manager=cm)
        reminders = manager.load_reminders()
        summary = manager.get_validation_summary()

        assert len(reminders) == 5
        assert summary["total_reminders"] == 5
        assert summary["valid_reminders"] == 5
        assert summary["invalid_reminders"] == 0
        assert summary["inactive_recipient_reminders"] == 1  # Reminder #3 (Carol, inactive)
        assert summary["pending_reminders"] == 4
        assert summary["sent_reminders"] == 1

        # Check that 3 reminders are eligible pending for active contacts
        eligible = manager.get_pending_reminders(only_active_contacts=True)
        assert len(eligible) == 3
        eligible_ids = [r["reminder_id"] for r in eligible]
        assert eligible_ids == ["1", "2", "5"]
