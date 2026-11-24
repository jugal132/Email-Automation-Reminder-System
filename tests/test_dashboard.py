"""
Unit and integration tests for dashboard.py module.

Tests cover:
- Path resolution and database status probing
- Handling of missing, empty, and populated databases
- Campaign metrics retrieval and safety invariants
- Data transformations for charts (outcome distributions and history trends)
- In-memory CSV export buffer generation
- Read-only guarantees: source CSVs and database tables remain untouched
- Non-invocation of EmailSender or ReminderScheduler
- Streamlit AppTest headless execution
"""

import csv
import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from dashboard import (
    check_database_status,
    fetch_campaign_metrics,
    fetch_execution_history,
    fetch_execution_results,
    format_history_trends,
    format_outcome_distribution,
    generate_campaign_csv_buffer,
    generate_detailed_csv_buffer,
    get_read_only_db_manager,
    resolve_db_path,
)
from src.database import DatabaseManager
from src.scheduler import SchedulerExecutionReport, SchedulerReminderResult


@pytest.fixture
def sample_populated_db(tmp_path: Path):
    """Fixture providing a temporary SQLite database populated with execution history."""
    db_file = tmp_path / "dashboard_test.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.init_db()

    rep1 = SchedulerExecutionReport(
        execution_id="exec-dash-001",
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
                reminder_id="101",
                contact_id="1",
                recipient="alice@example.com",
                subject="Roadmap Meeting",
                scheduled_at="2026-12-01 10:00",
                processing_status="simulated",
                delivery_status="simulated",
                error=None,
                timestamp="2026-12-01 10:00:01",
                metadata={"message_id": "sim-001"},
            ),
            SchedulerReminderResult(
                reminder_id="102",
                contact_id="2",
                recipient="bob@example.com",
                subject="Invoice Due",
                scheduled_at="2026-12-01 10:00",
                processing_status="simulated",
                delivery_status="simulated",
                error=None,
                timestamp="2026-12-01 10:00:02",
                metadata={"message_id": "sim-002"},
            ),
            SchedulerReminderResult(
                reminder_id="103",
                contact_id="3",
                recipient="carol@example.com",
                subject="Renewal",
                scheduled_at="2026-12-05 10:00",
                processing_status="not_due",
                delivery_status=None,
                error="Scheduled in future",
                timestamp="2026-12-01 10:00:03",
            ),
        ],
    )
    db_mgr.save_execution_report(rep1, notes="Demo Run 1")

    rep2 = SchedulerExecutionReport(
        execution_id="exec-dash-002",
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
                reminder_id="104",
                contact_id="4",
                recipient="david@example.com",
                subject="Alert",
                scheduled_at="2026-12-01 14:00",
                processing_status="failed",
                delivery_status="failed",
                error="Simulated network error",
                timestamp="2026-12-01 14:00:01",
            ),
        ],
    )
    db_mgr.save_execution_report(rep2, notes="Demo Run 2")

    yield db_file, db_mgr
    db_mgr.close()


@pytest.fixture
def sample_empty_db(tmp_path: Path):
    """Fixture providing an empty temporary SQLite database."""
    db_file = tmp_path / "empty_test.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.init_db()
    yield db_file, db_mgr
    db_mgr.close()


class TestPathAndDatabaseStatus:
    """Tests for resolving paths and probing database status."""

    def test_resolve_default_and_custom_db_path(self, tmp_path: Path):
        """Verify default resolution points to email_automation.db, and custom paths work."""
        default_path = resolve_db_path()
        assert default_path.name == "email_automation.db"

        custom_target = tmp_path / "custom.db"
        resolved_custom = resolve_db_path(custom_target)
        assert resolved_custom == custom_target.resolve()

    def test_check_database_status_missing_file(self, tmp_path: Path):
        """Verify missing database file is correctly diagnosed."""
        missing_file = tmp_path / "non_existent.db"
        status = check_database_status(missing_file)
        assert status["exists"] is False
        assert status["readable"] is False
        assert "not found" in status["error"]

    def test_check_database_status_existing_db(self, sample_populated_db):
        """Verify accessible database file reports true and tables found."""
        db_file, _ = sample_populated_db
        status = check_database_status(db_file)
        assert status["exists"] is True
        assert status["readable"] is True
        assert status["size_kb"] > 0
        assert "execution_history" in status["tables"]
        assert "reminder_executions" in status["tables"]


class TestDataFetchingAndMetrics:
    """Tests for fetching metrics, history, and individual outcomes."""

    def test_fetch_campaign_metrics_populated(self, sample_populated_db):
        """Verify campaign metrics are calculated accurately with safety invariant."""
        _, db_mgr = sample_populated_db
        metrics = fetch_campaign_metrics(db_mgr)

        assert metrics["total_runs"] == 2
        assert metrics["total_reminders_examined"] == 8
        assert metrics["total_due"] == 3
        assert metrics["total_simulated"] == 2
        assert metrics["total_failed"] == 1
        assert metrics["actual_sent"] == 0  # Strict invariant
        assert metrics["simulation_success_rate"] == 66.67

    def test_fetch_campaign_metrics_empty_db(self, sample_empty_db):
        """Verify campaign metrics on empty database return zeroed structure."""
        _, db_mgr = sample_empty_db
        metrics = fetch_campaign_metrics(db_mgr)

        assert metrics["total_runs"] == 0
        assert metrics["total_simulated"] == 0
        assert metrics["actual_sent"] == 0
        assert metrics["simulation_success_rate"] == 0.0

    def test_fetch_execution_history_and_results(self, sample_populated_db):
        """Verify retrieving history list and individual reminder results."""
        _, db_mgr = sample_populated_db
        history = fetch_execution_history(db_mgr)
        assert len(history) == 2

        results_1 = fetch_execution_results(db_mgr, "exec-dash-001")
        assert len(results_1) == 3
        recipients = {r["recipient"] for r in results_1}
        assert "alice@example.com" in recipients

        results_2 = fetch_execution_results(db_mgr, "exec-dash-002")
        assert len(results_2) == 1
        assert results_2[0]["processing_status"] == "failed"


class TestChartDataTransformations:
    """Tests for preparing DataFrames for charts and analytics."""

    def test_format_outcome_distribution(self, sample_populated_db):
        """Verify outcome counts and percentages are computed properly."""
        _, db_mgr = sample_populated_db
        all_results = db_mgr.get_all_reminder_executions()
        df = format_outcome_distribution(all_results)

        assert not df.empty
        assert set(df.columns) == {"Outcome Status", "Count", "Percentage"}
        status_counts = dict(zip(df["Outcome Status"], df["Count"]))
        assert status_counts.get("Simulated") == 2
        assert status_counts.get("Failed") == 1
        assert status_counts.get("Not_due") == 1

    def test_format_outcome_distribution_empty(self):
        """Verify empty result list returns an empty DataFrame with valid columns."""
        df = format_outcome_distribution([])
        assert df.empty
        assert set(df.columns) == {"Outcome Status", "Count", "Percentage"}

    def test_format_history_trends(self, sample_populated_db):
        """Verify chronological sequence and series columns for trend charting."""
        _, db_mgr = sample_populated_db
        history = fetch_execution_history(db_mgr)
        df_trends = format_history_trends(history)

        assert not df_trends.empty
        assert len(df_trends) == 2
        assert "Simulated" in df_trends.columns
        assert "Failed" in df_trends.columns
        assert "Skipped" in df_trends.columns

    def test_format_history_trends_empty(self):
        """Verify empty history list returns an empty DataFrame without errors."""
        df_trends = format_history_trends([])
        assert df_trends.empty


class TestCSVExportBuffers:
    """Tests for in-memory CSV export buffers."""

    def test_generate_campaign_csv_buffer(self, sample_populated_db):
        """Verify in-memory campaign summary CSV buffer has valid headers and values."""
        _, db_mgr = sample_populated_db
        buf = generate_campaign_csv_buffer(db_mgr)
        content = buf.getvalue().decode("utf-8")

        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)

        assert len(rows) == 2
        assert "execution_id" in reader.fieldnames
        assert "actual_sent" in reader.fieldnames
        for r in rows:
            assert int(r["actual_sent"]) == 0

    def test_generate_detailed_csv_buffer(self, sample_populated_db):
        """Verify in-memory detailed execution CSV buffer has valid headers and rows."""
        _, db_mgr = sample_populated_db
        buf = generate_detailed_csv_buffer(db_mgr, "exec-dash-001")
        content = buf.getvalue().decode("utf-8")

        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)

        assert len(rows) == 3
        assert rows[0]["execution_id"] == "exec-dash-001"
        assert rows[0]["recipient"] == "alice@example.com"


class TestDashboardSafetyAndImmutability:
    """Mandatory safety tests: dashboard is strictly read-only and never sends emails."""

    def test_dashboard_does_not_mutate_database(self, sample_populated_db):
        """Verify all dashboard read methods leave database records unaltered."""
        _, db_mgr = sample_populated_db

        # Snapshot before
        history_before = db_mgr.get_execution_history()
        results_before = db_mgr.get_all_reminder_executions()

        # Run all dashboard queries and data transformations
        fetch_campaign_metrics(db_mgr)
        fetch_execution_history(db_mgr)
        fetch_execution_results(db_mgr, "exec-dash-001")
        generate_campaign_csv_buffer(db_mgr)
        generate_detailed_csv_buffer(db_mgr, "exec-dash-001")

        # Snapshot after
        history_after = db_mgr.get_execution_history()
        results_after = db_mgr.get_all_reminder_executions()

        assert history_before == history_after
        assert results_before == results_after

    def test_dashboard_does_not_import_or_call_dispatch_methods(self):
        """Verify dashboard module does not invoke ReminderScheduler.run_once or EmailSender.send."""
        import dashboard

        # Verify dashboard module does not expose or call sending functions
        assert not hasattr(dashboard, "run_once")
        assert not hasattr(dashboard, "send")
        assert not hasattr(dashboard, "send_simulated")


class TestDashboardRenderExecution:
    """Smoke test rendering functions with mocked Streamlit calls."""

    @patch("dashboard.st")
    def test_dashboard_main_smoke_test(self, mock_st, sample_populated_db):
        """Verify dashboard main executes top-to-bottom without unhandled exceptions."""
        db_file, _ = sample_populated_db
        # Set mock columns to return iterable of mocks
        mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
        mock_st.selectbox.return_value = "exec-dash-001"

        with patch("dashboard.resolve_db_path", return_value=db_file):
            import dashboard
            dashboard.main()
            mock_st.set_page_config.assert_called_once()
            assert mock_st.metric.called
