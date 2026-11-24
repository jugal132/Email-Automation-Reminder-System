"""
Unit tests for ReminderScheduler module.

Tests cover:
- Due reminder detection (past, exact match, future)
- Status eligibility (pending required; sent, failed, cancelled excluded)
- Contact eligibility (active valid contact eligible; inactive, missing, invalid excluded)
- Pipeline orchestration (context builder, template rendering, message construction, simulation dispatch)
- Mandatory simulation-only safety (live env vars or live sender instances cannot trigger SMTP)
- In-memory duplicate processing protection
- Failure handling and fault isolation across reminders
- Execution report schema and summary counter accuracy
- Deterministic reference-time testing
- Invariance of source CSV files
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.contact_manager import ContactManager
from src.database import DatabaseError, DatabaseManager
from src.email_sender import EmailSender
from src.reminder_manager import ReminderManager
from src.scheduler import ReminderScheduler, SchedulerReminderResult
from src.template_processor import TemplateProcessor, TemplateValidationError


@pytest.fixture
def test_environment(tmp_path: Path):
    """
    Fixture creating isolated contact and reminder CSV files and initialized managers.
    Contacts:
      1: Alice (active)
      2: Bob (active)
      3: Carol (inactive)
      4: David (invalid email)
    Reminders:
      101: Contact 1, 2026-12-01 10:00, pending (due at 12:00)
      102: Contact 2, 2026-12-01 12:00, pending (exact match at 12:00)
      103: Contact 1, 2026-12-01 14:00, pending (future at 12:00)
      104: Contact 3, 2026-12-01 09:00, pending (inactive contact)
      105: Contact 4, 2026-12-01 09:00, pending (invalid contact)
      106: Contact 999, 2026-12-01 09:00, pending (missing contact)
      107: Contact 1, 2026-12-01 08:00, sent (already sent)
      108: Contact 1, 2026-12-01 08:00, failed (failed status)
      109: Contact 1, 2026-12-01 08:00, cancelled (cancelled status)
    """
    contacts_file = tmp_path / "contacts.csv"
    contacts_file.write_text(
        "contact_id,name,email,company,status\n"
        "1,Alice Active,alice@example.com,Acme,active\n"
        "2,Bob Active,bob@example.com,Global,active\n"
        "3,Carol Inactive,carol@example.com,Innovate,inactive\n"
        "4,David Invalid,invalid-email,NextGen,active\n",
        encoding="utf-8",
    )

    reminders_file = tmp_path / "reminders.csv"
    reminders_file.write_text(
        "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
        "101,1,Meeting Past,Past Subject,Please attend.,2026-12-01 10:00,pending\n"
        "102,2,Meeting Exact,Exact Subject,Right now.,2026-12-01 12:00,pending\n"
        "103,1,Meeting Future,Future Subject,Later today.,2026-12-01 14:00,pending\n"
        "104,3,Meeting Inactive,Inactive Subject,Notice.,2026-12-01 09:00,pending\n"
        "105,4,Meeting BadContact,Bad Contact Subject,Notice.,2026-12-01 09:00,pending\n"
        "106,999,Meeting Missing,Missing Contact Subject,Notice.,2026-12-01 09:00,pending\n"
        "107,1,Meeting Sent,Sent Subject,Already done.,2026-12-01 08:00,sent\n"
        "108,1,Meeting Failed,Failed Subject,Failed before.,2026-12-01 08:00,failed\n"
        "109,1,Meeting Cancelled,Cancelled Subject,Cancelled.,2026-12-01 08:00,cancelled\n",
        encoding="utf-8",
    )

    cm = ContactManager(data_source=contacts_file)
    rm = ReminderManager(data_source=reminders_file, contact_manager=cm)
    tp = TemplateProcessor()

    return {
        "contacts_file": contacts_file,
        "reminders_file": reminders_file,
        "contact_manager": cm,
        "reminder_manager": rm,
        "template_processor": tp,
    }


class TestDueReminderDetection:
    """Tests for identifying due vs future and ineligible reminders."""

    def test_past_and_exact_match_reminders_are_due(self, test_environment: dict) -> None:
        """Verify reminders with scheduled_at <= reference_time are identified as due."""
        rm = test_environment["reminder_manager"]
        cm = test_environment["contact_manager"]
        tp = test_environment["template_processor"]

        ref_time = datetime(2026, 12, 1, 12, 0)
        scheduler = ReminderScheduler(
            reminder_manager=rm,
            contact_manager=cm,
            template_processor=tp,
            reference_time=ref_time,
        )

        due = scheduler.get_due_reminders(reference_time=ref_time)
        due_ids = [r["reminder_id"] for r in due]

        # 101 (10:00 < 12:00) and 102 (12:00 == 12:00) should be due
        assert "101" in due_ids
        assert "102" in due_ids
        # 103 (14:00 > 12:00) is in future
        assert "103" not in due_ids

    def test_future_reminders_are_not_due(self, test_environment: dict) -> None:
        """Verify future reminders are excluded from due list."""
        rm = test_environment["reminder_manager"]
        cm = test_environment["contact_manager"]
        tp = test_environment["template_processor"]

        # Set reference time earlier than all reminders (e.g., 07:00)
        early_time = datetime(2026, 12, 1, 7, 0)
        scheduler = ReminderScheduler(
            reminder_manager=rm,
            contact_manager=cm,
            template_processor=tp,
            reference_time=early_time,
        )

        due = scheduler.get_due_reminders(reference_time=early_time)
        assert len(due) == 0

    def test_non_pending_statuses_excluded(self, test_environment: dict) -> None:
        """Verify sent (107), failed (108), and cancelled (109) reminders are not due."""
        rm = test_environment["reminder_manager"]
        cm = test_environment["contact_manager"]
        tp = test_environment["template_processor"]

        ref_time = datetime(2026, 12, 1, 12, 0)
        scheduler = ReminderScheduler(
            reminder_manager=rm,
            contact_manager=cm,
            template_processor=tp,
            reference_time=ref_time,
        )

        due = scheduler.get_due_reminders(reference_time=ref_time)
        due_ids = [r["reminder_id"] for r in due]

        assert "107" not in due_ids
        assert "108" not in due_ids
        assert "109" not in due_ids


class TestContactEligibility:
    """Tests for contact relationship constraints on scheduling."""

    def test_inactive_contact_is_excluded(self, test_environment: dict) -> None:
        """Verify reminder 104 with inactive contact 3 is excluded from due reminders."""
        rm = test_environment["reminder_manager"]
        cm = test_environment["contact_manager"]
        tp = test_environment["template_processor"]

        ref_time = datetime(2026, 12, 1, 12, 0)
        scheduler = ReminderScheduler(
            reminder_manager=rm,
            contact_manager=cm,
            template_processor=tp,
            reference_time=ref_time,
        )

        due = scheduler.get_due_reminders(reference_time=ref_time)
        due_ids = [r["reminder_id"] for r in due]
        assert "104" not in due_ids

    def test_invalid_and_missing_contacts_are_excluded(self, test_environment: dict) -> None:
        """Verify reminder 105 (bad contact) and 106 (missing contact) are excluded."""
        rm = test_environment["reminder_manager"]
        cm = test_environment["contact_manager"]
        tp = test_environment["template_processor"]

        ref_time = datetime(2026, 12, 1, 12, 0)
        scheduler = ReminderScheduler(
            reminder_manager=rm,
            contact_manager=cm,
            template_processor=tp,
            reference_time=ref_time,
        )

        due = scheduler.get_due_reminders(reference_time=ref_time)
        due_ids = [r["reminder_id"] for r in due]
        assert "105" not in due_ids
        assert "106" not in due_ids


class TestPipelineOrchestration:
    """Tests for end-to-end execution of run_once."""

    def test_run_once_pipeline_execution(self, test_environment: dict) -> None:
        """Verify run_once dispatches due reminders via simulation and captures report."""
        rm = test_environment["reminder_manager"]
        cm = test_environment["contact_manager"]
        tp = test_environment["template_processor"]

        ref_time = datetime(2026, 12, 1, 12, 0)
        scheduler = ReminderScheduler(
            reminder_manager=rm,
            contact_manager=cm,
            template_processor=tp,
            reference_time=ref_time,
        )

        report = scheduler.run_once(reference_time=ref_time)

        assert report.total_reminders_examined == 9
        assert report.total_due == 2  # #101 and #102
        assert report.total_processed == 2
        assert report.total_simulated == 2
        assert report.total_failed == 0
        assert report.total_skipped == 7  # 1 future, 3 bad contacts, 3 non-pending

        simulated_results = [r for r in report.results if r.processing_status == "simulated"]
        assert len(simulated_results) == 2
        recipients = {r.recipient for r in simulated_results}
        assert "alice@example.com" in recipients
        assert "bob@example.com" in recipients

    def test_source_reminders_csv_remains_unchanged(self, test_environment: dict) -> None:
        """Verify running scheduler in simulation mode does NOT mutate the source CSV."""
        reminders_file: Path = test_environment["reminders_file"]
        content_before = reminders_file.read_text(encoding="utf-8")

        ref_time = datetime(2026, 12, 1, 12, 0)
        scheduler = ReminderScheduler(
            reminder_manager=test_environment["reminder_manager"],
            contact_manager=test_environment["contact_manager"],
            template_processor=test_environment["template_processor"],
            reference_time=ref_time,
        )
        scheduler.run_once(reference_time=ref_time)

        content_after = reminders_file.read_text(encoding="utf-8")
        assert content_before == content_after, "Source CSV file was mutated during simulation!"


class TestSimulationOnlySafety:
    """Mandatory safety tests: verify scheduler CANNOT send real emails under any circumstances."""

    @patch("smtplib.SMTP")
    @patch("smtplib.SMTP_SSL")
    def test_scheduler_strictly_enforces_simulation_mode(
        self, mock_ssl: MagicMock, mock_smtp: MagicMock, test_environment: dict
    ) -> None:
        """
        Verify that even if an EmailSender configured with live mode and ALLOW_REAL_EMAILS=true
        is passed to the scheduler, the scheduler forces mode='simulation' and never touches SMTP.
        """
        live_sender = EmailSender(
            mode="live",
            config={
                "ALLOW_REAL_EMAILS": "true",
                "SMTP_HOST": "smtp.live.com",
                "SMTP_PORT": 587,
                "SMTP_USERNAME": "user",
                "SMTP_PASSWORD": "pwd",
            },
        )

        ref_time = datetime(2026, 12, 1, 12, 0)
        scheduler = ReminderScheduler(
            reminder_manager=test_environment["reminder_manager"],
            contact_manager=test_environment["contact_manager"],
            template_processor=test_environment["template_processor"],
            email_sender=live_sender,
            reference_time=ref_time,
        )

        # Scheduler must force simulation
        assert scheduler.email_sender.mode == "simulation"

        report = scheduler.run_once(reference_time=ref_time)

        # Assert zero SMTP calls
        assert mock_smtp.call_count == 0
        assert mock_ssl.call_count == 0
        assert report.total_simulated == 2


class TestDuplicateProcessingProtection:
    """Tests for preventing duplicate dispatches in a single run."""

    def test_in_memory_duplicate_protection(self, tmp_path: Path) -> None:
        """Verify identical reminder IDs in same batch are not dispatched twice."""
        contacts_file = tmp_path / "dup_c.csv"
        contacts_file.write_text(
            "contact_id,name,email,company,status\n1,Alice,alice@example.com,Co,active\n",
            encoding="utf-8",
        )
        # Note: ReminderManager flags duplicate IDs as invalid, so we test duplicate ID handling
        reminders_file = tmp_path / "dup_r.csv"
        reminders_file.write_text(
            "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
            "201,1,Meeting,Sub 1,Msg 1,2026-12-01 10:00,pending\n"
            "201,1,Meeting,Sub 2,Msg 2,2026-12-01 10:00,pending\n",
            encoding="utf-8",
        )

        cm = ContactManager(data_source=contacts_file)
        rm = ReminderManager(data_source=reminders_file, contact_manager=cm)
        scheduler = ReminderScheduler(reminder_manager=rm, contact_manager=cm)

        report = scheduler.run_once(reference_time=datetime(2026, 12, 1, 12, 0))

        # First record is valid & simulated; second record was marked invalid duplicate by manager & skipped
        assert report.total_simulated == 1
        assert report.total_skipped == 1


class TestFailureHandlingAndIsolation:
    """Tests for isolating individual reminder errors without crashing the batch."""

    def test_template_rendering_failure_is_isolated(
        self, tmp_path: Path, test_environment: dict
    ) -> None:
        """
        Verify that if one reminder fails template rendering, subsequent eligible
        reminders continue to be processed and simulated successfully.
        """
        # Create a mock template processor that fails on reminder #101
        mock_tp = MagicMock()
        mock_tp.build_context.side_effect = TemplateProcessor.build_context

        def mock_render(context):
            if context.get("reminder_id") == "101":
                raise TemplateValidationError("Simulated template render error for #101")
            return "Rendered valid body for reminder"

        mock_tp.render.side_effect = mock_render

        ref_time = datetime(2026, 12, 1, 12, 0)
        scheduler = ReminderScheduler(
            reminder_manager=test_environment["reminder_manager"],
            contact_manager=test_environment["contact_manager"],
            template_processor=mock_tp,
            reference_time=ref_time,
        )

        report = scheduler.run_once(reference_time=ref_time)

        assert report.total_due == 2
        assert report.total_processed == 2
        # #101 failed, #102 simulated!
        assert report.total_failed == 1
        assert report.total_simulated == 1

        failed_item = [r for r in report.results if r.reminder_id == "101"][0]
        assert failed_item.processing_status == "failed"
        assert "Simulated template render error" in failed_item.error

        success_item = [r for r in report.results if r.reminder_id == "102"][0]
        assert success_item.processing_status == "simulated"


class TestSchedulerDatabaseIntegration:
    """Tests verifying database persistence and fault isolation in ReminderScheduler."""

    def test_scheduler_persists_report_to_database(self, test_environment: dict) -> None:
        """Verify scheduler automatically persists execution report when database_manager is provided."""
        db_mgr = DatabaseManager(":memory:")
        db_mgr.init_db()

        ref_time = datetime(2026, 12, 1, 12, 0)
        scheduler = ReminderScheduler(
            reminder_manager=test_environment["reminder_manager"],
            contact_manager=test_environment["contact_manager"],
            template_processor=test_environment["template_processor"],
            reference_time=ref_time,
            database_manager=db_mgr,
        )

        report = scheduler.run_once(reference_time=ref_time)

        # Check DB has execution record
        db_exec = db_mgr.get_execution_by_id(report.execution_id)
        assert db_exec is not None
        assert db_exec["execution_id"] == report.execution_id
        assert db_exec["total_due"] == 2
        assert db_exec["total_simulated"] == 2

        # Check DB has reminder results
        results = db_mgr.get_results_for_execution(report.execution_id)
        assert len(results) == len(report.results)
        db_mgr.close()

    def test_scheduler_fault_isolation_on_database_failure(self, test_environment: dict) -> None:
        """Verify scheduler catches database persistence errors and returns in-memory report safely."""
        failing_db = MagicMock(spec=DatabaseManager)
        failing_db.save_execution_report.side_effect = DatabaseError("Simulated disk full or DB locked")

        ref_time = datetime(2026, 12, 1, 12, 0)
        scheduler = ReminderScheduler(
            reminder_manager=test_environment["reminder_manager"],
            contact_manager=test_environment["contact_manager"],
            template_processor=test_environment["template_processor"],
            reference_time=ref_time,
            database_manager=failing_db,
        )

        # Pipeline should NOT raise; in-memory report must be returned cleanly
        report = scheduler.run_once(reference_time=ref_time)

        assert report is not None
        assert report.total_due == 2
        assert report.total_simulated == 2
        failing_db.save_execution_report.assert_called_once()

