"""
Unit tests for ReportGenerator module.

Tests cover:
- ReportGenerator initialization and directory creation
- Campaign summary aggregation
- Execution report generation
- CSV export for campaign summary and detailed runs
- Error handling
- Summary text formatting
- Strict simulation-mode invariant (actual_sent == 0)
"""

import csv
from pathlib import Path
import pytest

from src.database import DatabaseManager
from src.report_generator import ReportGenerator, ReportGeneratorError
from src.scheduler import SchedulerExecutionReport, SchedulerReminderResult


@pytest.fixture
def test_db():
    """Fixture providing an in-memory DatabaseManager populated with test runs."""
    db = DatabaseManager(":memory:")
    db.init_db()

    # Execution 1
    rep1 = SchedulerExecutionReport(
        execution_id="exec-101",
        execution_timestamp="2026-12-01 10:00:00",
        reference_time="2026-12-01 10:00",
        total_reminders_examined=5,
        total_due=2,
        total_processed=2,
        total_simulated=2,
        total_failed=0,
        total_skipped=3,
        results=[
            SchedulerReminderResult(
                reminder_id="1",
                contact_id="10",
                recipient="alice@example.com",
                subject="Invoice Due",
                scheduled_at="2026-12-01 10:00",
                processing_status="simulated",
                delivery_status="simulated",
                error=None,
                timestamp="2026-12-01 10:00:01",
                metadata={"message_id": "sim-101-1"},
            ),
            SchedulerReminderResult(
                reminder_id="2",
                contact_id="20",
                recipient="bob@example.com",
                subject="Welcome",
                scheduled_at="2026-12-01 10:00",
                processing_status="simulated",
                delivery_status="simulated",
                error=None,
                timestamp="2026-12-01 10:00:02",
                metadata={"message_id": "sim-101-2"},
            ),
        ],
    )
    db.save_execution_report(rep1, notes="Successful first batch")

    # Execution 2
    rep2 = SchedulerExecutionReport(
        execution_id="exec-102",
        execution_timestamp="2026-12-01 14:00:00",
        reference_time="2026-12-01 14:00",
        total_reminders_examined=3,
        total_due=1,
        total_processed=1,
        total_simulated=0,
        total_failed=1,
        total_skipped=2,
        results=[
            SchedulerReminderResult(
                reminder_id="3",
                contact_id="30",
                recipient="carol@example.com",
                subject="Follow-up",
                scheduled_at="2026-12-01 14:00",
                processing_status="failed",
                delivery_status="failed",
                error="Simulated error in pipeline",
                timestamp="2026-12-01 14:00:01",
            )
        ],
    )
    db.save_execution_report(rep2, notes="Failed second batch")

    yield db
    db.close()


@pytest.fixture
def empty_db():
    """Fixture providing an empty in-memory DatabaseManager."""
    db = DatabaseManager(":memory:")
    db.init_db()
    yield db
    db.close()


class TestReportGeneratorInitialization:
    """Tests for ReportGenerator initialization and path handling."""

    def test_default_output_dir_created(self, tmp_path: Path):
        """Verify report generator creates target output directory if it does not exist."""
        custom_dir = tmp_path / "reports_test_dir"
        assert not custom_dir.exists()
        gen = ReportGenerator(output_dir=custom_dir)
        assert custom_dir.exists()
        assert gen.output_dir == custom_dir


class TestCampaignSummary:
    """Tests for aggregate metrics generation."""

    def test_generate_campaign_summary_empty_database(self, empty_db: DatabaseManager, tmp_path: Path):
        """Verify summary on empty database returns structured zeroed metrics."""
        gen = ReportGenerator(output_dir=tmp_path, database_manager=empty_db)
        summary = gen.generate_campaign_summary()

        assert summary["total_runs"] == 0
        assert summary["total_reminders_examined"] == 0
        assert summary["total_simulated"] == 0
        assert summary["total_failed"] == 0
        assert summary["actual_sent"] == 0  # Invariant
        assert summary["simulation_success_rate"] == 0.0
        assert summary["is_campaign_active"] is False

    def test_generate_campaign_summary_with_runs(self, test_db: DatabaseManager, tmp_path: Path):
        """Verify summary accurately aggregates runs."""
        gen = ReportGenerator(output_dir=tmp_path, database_manager=test_db)
        summary = gen.generate_campaign_summary()

        assert summary["total_runs"] == 2
        assert summary["total_reminders_examined"] == 8
        assert summary["total_due"] == 3
        assert summary["total_processed"] == 3
        assert summary["total_simulated"] == 2
        assert summary["total_failed"] == 1
        assert summary["total_skipped"] == 5
        assert summary["actual_sent"] == 0  # Strict invariant
        assert summary["simulation_success_rate"] == 66.67  # 2/3
        assert summary["latest_execution_timestamp"] == "2026-12-01 14:00:00"
        assert summary["is_campaign_active"] is True


class TestExecutionReport:
    """Tests for single execution reporting."""

    def test_generate_execution_report_success(self, test_db: DatabaseManager, tmp_path: Path):
        """Verify retrieving details and results for an execution ID."""
        gen = ReportGenerator(output_dir=tmp_path, database_manager=test_db)
        report = gen.generate_execution_report("exec-101")

        assert report["execution"]["execution_id"] == "exec-101"
        assert report["execution"]["notes"] == "Successful first batch"
        assert report["total_results"] == 2
        assert report["results"][0]["reminder_id"] == "1"
        assert report["results"][0]["message_id"] == "sim-101-1"

    def test_generate_execution_report_not_found_raises_error(
        self, test_db: DatabaseManager, tmp_path: Path
    ):
        """Verify querying non-existent execution ID raises ReportGeneratorError."""
        gen = ReportGenerator(output_dir=tmp_path, database_manager=test_db)
        with pytest.raises(ReportGeneratorError, match="not found"):
            gen.generate_execution_report("exec-non-existent")


class TestCSVExport:
    """Tests for CSV exporting."""

    def test_export_campaign_report_csv_format_and_values(
        self, test_db: DatabaseManager, tmp_path: Path
    ):
        """Verify exported campaign report CSV file format, headers, and values."""
        gen = ReportGenerator(output_dir=tmp_path, database_manager=test_db)
        csv_file = gen.export_campaign_report_csv(filename="custom_summary.csv")

        assert csv_file.exists()
        assert csv_file.name == "custom_summary.csv"

        with open(csv_file, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2
        # Check expected headers
        expected_headers = [
            "execution_id",
            "execution_timestamp",
            "reference_time",
            "total_reminders_examined",
            "total_due",
            "total_processed",
            "total_simulated",
            "total_failed",
            "total_skipped",
            "actual_sent",
            "simulation_success_rate_pct",
            "notes",
        ]
        assert reader.fieldnames == expected_headers

        # Check safety column value
        for r in rows:
            assert int(r["actual_sent"]) == 0

    def test_export_campaign_report_csv_on_empty_database(
        self, empty_db: DatabaseManager, tmp_path: Path
    ):
        """Verify exporting CSV on empty database produces valid headers with 0 data rows."""
        gen = ReportGenerator(output_dir=tmp_path, database_manager=empty_db)
        csv_file = gen.export_campaign_report_csv(filename="empty_report.csv")

        assert csv_file.exists()
        with open(csv_file, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 0

    def test_export_detailed_execution_csv(
        self, test_db: DatabaseManager, tmp_path: Path
    ):
        """Verify exporting detailed single execution CSV."""
        gen = ReportGenerator(output_dir=tmp_path, database_manager=test_db)
        detailed_file = gen.export_detailed_execution_csv("exec-101")

        assert detailed_file.exists()
        with open(detailed_file, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2
        assert rows[0]["reminder_id"] == "1"
        assert rows[0]["recipient"] == "alice@example.com"
        assert rows[0]["processing_status"] == "simulated"
        assert rows[0]["message_id"] == "sim-101-1"

    def test_format_summary_text(self, test_db: DatabaseManager, tmp_path: Path):
        """Verify format_summary_text produces aligned textual summary with safety text."""
        gen = ReportGenerator(output_dir=tmp_path, database_manager=test_db)
        summary = gen.generate_campaign_summary()
        text = gen.format_summary_text(summary)

        assert "CAMPAIGN SUMMARY METRICS (SIMULATION MODE)" in text
        assert "Actual Real Emails Sent   : 0 (Safety Invariant)" in text
        assert "Total Messages Simulated  : 2" in text
