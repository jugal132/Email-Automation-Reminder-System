"""
Unit tests for ContactManager module.

Tests cover:
- Valid contacts ingestion
- Invalid email address detection
- Missing required fields
- Missing required columns
- Duplicate email detection with case insensitivity
- Whitespace cleanup and normalization
- Active / Inactive status filtering
- Missing CSV file handling
- Empty CSV file handling
- Summary statistics accuracy and counting logic
"""

from pathlib import Path
import pytest

from src.contact_manager import (
    ContactDataError,
    ContactFileNotFoundError,
    ContactManager,
    EmptyFileError,
    validate_email_format,
)


class TestEmailValidationFunction:
    """Tests for standalone validate_email_format function."""

    def test_valid_emails(self) -> None:
        """Verify standard valid email formats pass validation."""
        valid_samples = [
            "aarav@example.com",
            "neha@gmail.com",
            "first.last@company.org",
            "user+tag@domain.co.in",
            "test_123@sub.example.com",
        ]
        for email in valid_samples:
            assert validate_email_format(email) is True, f"Failed for {email}"

    def test_invalid_emails(self) -> None:
        """Verify invalid email formats are rejected."""
        invalid_samples = [
            "abc",
            "missing@",
            "@example.com",
            "user@.com",
            "user@domain",
            "user@domain..com",
            "",
            "   ",
            None,
        ]
        for email in invalid_samples:
            assert validate_email_format(email) is False, f"Expected invalid for {email}"


class TestContactManagerLoadingAndErrors:
    """Tests for file loading, missing files, empty files, and header validation."""

    def test_missing_file_raises_error(self, tmp_path: Path) -> None:
        """Verify ContactFileNotFoundError is raised when file does not exist."""
        non_existent_file = tmp_path / "does_not_exist.csv"
        manager = ContactManager(data_source=non_existent_file)
        with pytest.raises(ContactFileNotFoundError) as exc_info:
            manager.load_contacts()
        assert "Contacts file not found" in str(exc_info.value)

    def test_zero_byte_empty_file_raises_error(self, tmp_path: Path) -> None:
        """Verify EmptyFileError is raised when CSV file has 0 bytes."""
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text("", encoding="utf-8")
        manager = ContactManager(data_source=empty_csv)
        with pytest.raises(EmptyFileError) as exc_info:
            manager.load_contacts()
        assert "empty" in str(exc_info.value).lower()

    def test_header_only_file_raises_error(self, tmp_path: Path) -> None:
        """Verify EmptyFileError is raised when CSV contains only headers and no data rows."""
        header_only_csv = tmp_path / "header_only.csv"
        header_only_csv.write_text("contact_id,name,email,company,status\n", encoding="utf-8")
        manager = ContactManager(data_source=header_only_csv)
        with pytest.raises(EmptyFileError) as exc_info:
            manager.load_contacts()
        assert "no data records" in str(exc_info.value).lower()

    def test_missing_required_columns_raises_error(self, tmp_path: Path) -> None:
        """Verify ContactDataError is raised when required columns are missing."""
        invalid_cols_csv = tmp_path / "missing_cols.csv"
        # Missing 'status' column
        invalid_cols_csv.write_text(
            "contact_id,name,email\n1,Alice,alice@example.com\n", encoding="utf-8"
        )
        manager = ContactManager(data_source=invalid_cols_csv)
        with pytest.raises(ContactDataError) as exc_info:
            manager.load_contacts()
        assert "missing required column(s)" in str(exc_info.value).lower()
        assert "status" in str(exc_info.value).lower()


class TestContactManagerDataCleaningAndValidation:
    """Tests for data cleaning, required field validation, and duplicate handling."""

    def test_valid_contacts_loading(self, tmp_path: Path) -> None:
        """Verify clean valid contacts are parsed and marked valid."""
        csv_path = tmp_path / "valid.csv"
        csv_path.write_text(
            "contact_id,name,email,company,status\n"
            "1,Alice Smith,alice@example.com,Acme,active\n"
            "2,Bob Jones,bob@example.com,Corp,inactive\n",
            encoding="utf-8",
        )
        manager = ContactManager(data_source=csv_path)
        contacts = manager.load_contacts()

        assert len(contacts) == 2
        assert len(manager.get_valid_contacts()) == 2
        assert len(manager.get_invalid_contacts()) == 0

    def test_whitespace_cleanup_and_normalization(self, tmp_path: Path) -> None:
        """Verify whitespace is trimmed and emails/statuses are lowercased."""
        csv_path = tmp_path / "whitespace.csv"
        csv_path.write_text(
            "contact_id,name,email,company,status\n"
            " 101 ,  John Doe  ,  JOHN.DOE@EXAMPLE.COM  ,  Big Co  ,  ACTIVE  \n",
            encoding="utf-8",
        )
        manager = ContactManager(data_source=csv_path)
        contacts = manager.load_contacts()
        record = contacts[0]

        assert record["contact_id"] == "101"
        assert record["name"] == "John Doe"
        assert record["email"] == "john.doe@example.com"
        assert record["company"] == "Big Co"
        assert record["status"] == "active"
        assert record["is_valid"] is True

    def test_missing_required_fields_flagged(self, tmp_path: Path) -> None:
        """Verify records with missing required fields are marked invalid with clear reasons."""
        csv_path = tmp_path / "missing_fields.csv"
        csv_path.write_text(
            "contact_id,name,email,company,status\n"
            ",No ID,noid@example.com,Co,active\n"
            "2,,noname@example.com,Co,active\n"
            "3,No Email,,Co,active\n"
            "4,No Status,nostatus@example.com,Co,\n",
            encoding="utf-8",
        )
        manager = ContactManager(data_source=csv_path)
        manager.load_contacts()

        invalid = manager.get_invalid_contacts()
        assert len(invalid) == 4
        assert len(manager.get_valid_contacts()) == 0

        # Check explicit error messages
        assert any("contact_id" in err for err in invalid[0]["validation_errors"])
        assert any("name" in err for err in invalid[1]["validation_errors"])
        assert any("email" in err for err in invalid[2]["validation_errors"])
        assert any("status" in err for err in invalid[3]["validation_errors"])

    def test_invalid_email_format_flagged(self, tmp_path: Path) -> None:
        """Verify malformed email formats are marked invalid."""
        csv_path = tmp_path / "bad_emails.csv"
        csv_path.write_text(
            "contact_id,name,email,company,status\n"
            "1,User One,not-an-email,Tech,active\n"
            "2,User Two,missing-domain@,Tech,active\n",
            encoding="utf-8",
        )
        manager = ContactManager(data_source=csv_path)
        manager.load_contacts()

        invalid = manager.get_invalid_contacts()
        assert len(invalid) == 2
        assert "Invalid email address format" in invalid[0]["validation_errors"][0]
        assert "Invalid email address format" in invalid[1]["validation_errors"][0]

    def test_duplicate_detection_case_insensitive(self, tmp_path: Path) -> None:
        """
        Verify duplicate emails with differing casing are detected.
        First record is kept as valid; subsequent duplicate is marked invalid.
        """
        csv_path = tmp_path / "duplicates.csv"
        csv_path.write_text(
            "contact_id,name,email,company,status\n"
            "1,Aarav Kumar,aarav@example.com,First Corp,active\n"
            "2,Aarav K Duplicate,AARAV@EXAMPLE.COM,Second Corp,active\n"
            "3,Aarav Third,  aarav@example.com  ,Third Corp,inactive\n",
            encoding="utf-8",
        )
        manager = ContactManager(data_source=csv_path)
        manager.load_contacts()

        valid = manager.get_valid_contacts()
        invalid = manager.get_invalid_contacts()
        duplicates = manager.get_duplicate_contacts()

        assert len(valid) == 1
        assert valid[0]["contact_id"] == "1"

        assert len(duplicates) == 2
        assert duplicates[0]["contact_id"] == "2"
        assert duplicates[0]["is_duplicate"] is True
        assert "Duplicate email address" in duplicates[0]["validation_errors"][0]
        assert "contact_id: '1'" in duplicates[0]["validation_errors"][0]

        assert duplicates[1]["contact_id"] == "3"
        assert duplicates[1]["is_duplicate"] is True

        assert len(invalid) == 2

    def test_active_and_inactive_filtering(self, tmp_path: Path) -> None:
        """
        Verify get_active_contacts returns only valid active records,
        excluding inactive, pending, draft, or invalid contacts.
        """
        csv_path = tmp_path / "status_filter.csv"
        csv_path.write_text(
            "contact_id,name,email,company,status\n"
            "1,Active User,active@example.com,Corp,active\n"
            "2,Active Spaced,spaced@example.com,Corp,  Active  \n"
            "3,Inactive User,inactive@example.com,Corp,inactive\n"
            "4,Draft User,draft@example.com,Corp,draft\n"
            "5,Active Bad Email,bad-email,Corp,active\n",
            encoding="utf-8",
        )
        manager = ContactManager(data_source=csv_path)
        manager.load_contacts()

        active = manager.get_active_contacts()
        active_ids = [c["contact_id"] for c in active]

        assert active_ids == ["1", "2"]
        assert "3" not in active_ids
        assert "4" not in active_ids
        assert "5" not in active_ids  # Invalid email, so excluded from active

    def test_validation_summary_counts(self, tmp_path: Path) -> None:
        """Verify calculated summary statistics adhere to counting specifications."""
        csv_path = tmp_path / "summary_test.csv"
        csv_path.write_text(
            "contact_id,name,email,company,status\n"
            "1,User One,user1@example.com,Corp,active\n"
            "2,User Two,user2@example.com,Corp,active\n"
            "3,User Three,user3@example.com,Corp,inactive\n"
            "4,User Four Dup,USER1@EXAMPLE.COM,Corp,active\n"
            "5,User Five Bad,invalid-email,Corp,active\n",
            encoding="utf-8",
        )
        manager = ContactManager(data_source=csv_path)
        summary = manager.get_validation_summary()

        assert summary["total_records"] == 5
        assert summary["valid_records"] == 3    # User 1, 2, 3
        assert summary["invalid_records"] == 2  # User 4 (dup), User 5 (bad email)
        assert summary["duplicate_records"] == 1
        assert summary["active_records"] == 2   # User 1, 2
        assert summary["inactive_records"] == 1 # User 3

        # Confirm mathematical invariants
        assert summary["total_records"] == summary["valid_records"] + summary["invalid_records"]
        assert summary["valid_records"] == summary["active_records"] + summary["inactive_records"]

    def test_real_sample_contacts_csv(self) -> None:
        """Verify the actual project data/contacts.csv passes validation as expected."""
        manager = ContactManager()
        contacts = manager.load_contacts()
        summary = manager.get_validation_summary()

        assert len(contacts) == 5
        assert summary["total_records"] == 5
        assert summary["valid_records"] == 5
        assert summary["invalid_records"] == 0
        assert summary["duplicate_records"] == 0
        assert summary["active_records"] == 4   # Alice, Bob, David, Emma
        assert summary["inactive_records"] == 1 # Carol (inactive)
