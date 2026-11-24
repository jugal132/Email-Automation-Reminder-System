"""
Unit tests for DatabaseManager module.

Tests cover:
- Database initialization (:memory: and filesystem paths)
- Schema creation and idempotent migrations
- Relational integrity, foreign keys, and cascading deletes
- Atomic persistence of execution history and reminder outcomes
- Rollback on failure
- Querying execution history, results, and aggregated campaign metrics
- Context manager protocol
- Error handling
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.database import DatabaseConnectionError, DatabaseError, DatabaseManager
from src.scheduler import SchedulerExecutionReport, SchedulerReminderResult


@pytest.fixture
def memory_db():
    """Fixture providing an in-memory DatabaseManager with initialized schema."""
    db = DatabaseManager(":memory:")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def file_db(tmp_path: Path):
    """Fixture providing a temporary filesystem DatabaseManager."""
    db_file = tmp_path / "subfolder" / "test_automation.db"
    db = DatabaseManager(db_file)
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def sample_execution_report():
    """Fixture providing a sample populated SchedulerExecutionReport."""
    results = [
        SchedulerReminderResult(
            reminder_id="1",
            contact_id="10",
            recipient="alice@example.com",
            subject="Invoice Reminder",
            scheduled_at="2026-12-01 10:00",
            processing_status="simulated",
            delivery_status="simulated",
            error=None,
            timestamp="2026-12-01 10:00:01",
            metadata={"message_id": "sim-msg-001", "execution_id": "exec-001"},
        ),
        SchedulerReminderResult(
            reminder_id="2",
            contact_id="20",
            recipient="bob@example.com",
            subject="Contract Review",
            scheduled_at="2026-12-01 10:00",
            processing_status="failed",
            delivery_status="failed",
            error="Simulated network failure",
            timestamp="2026-12-01 10:00:02",
            metadata={"execution_id": "exec-001"},
        ),
        SchedulerReminderResult(
            reminder_id="3",
            contact_id="30",
            recipient="carol@example.com",
            subject="Welcome",
            scheduled_at="2026-12-05 10:00",
            processing_status="not_due",
            delivery_status=None,
            error="Scheduled in future",
            timestamp="2026-12-01 10:00:03",
        ),
    ]

    return SchedulerExecutionReport(
        execution_id="exec-001",
        execution_timestamp="2026-12-01 10:00:00",
        reference_time="2026-12-01 10:00",
        total_reminders_examined=3,
        total_due=2,
        total_processed=2,
        total_simulated=1,
        total_failed=1,
        total_skipped=1,
        results=results,
    )


class TestDatabaseInitialization:
    """Tests for database instantiation and connection lifecycle."""

    def test_default_db_path(self):
        """Verify default database path points to project data/email_automation.db."""
        mgr = DatabaseManager()
        assert "email_automation.db" in mgr.db_path

    def test_in_memory_database(self, memory_db: DatabaseManager):
        """Verify in-memory database configuration."""
        assert memory_db.db_path == ":memory:"
        conn = memory_db.get_connection()
        assert isinstance(conn, sqlite3.Connection)

    def test_filesystem_database_creates_parent_directories(self, tmp_path: Path):
        """Verify non-existent nested parent directories are created automatically."""
        deep_dir = tmp_path / "deep" / "nested" / "path" / "app.db"
        mgr = DatabaseManager(deep_dir)
        assert deep_dir.parent.exists()
        mgr.init_db()
        assert deep_dir.exists()
        mgr.close()

    def test_context_manager(self, tmp_path: Path):
        """Verify __enter__ and __exit__ correctly handle connection."""
        db_file = tmp_path / "cm_test.db"
        with DatabaseManager(db_file) as mgr:
            mgr.init_db()
            conn = mgr.get_connection()
            assert conn is not None
        # After exit, connection should be closed
        assert mgr._connection is None

    def test_connection_error_raises_database_connection_error(self):
        """Verify connection errors raise DatabaseConnectionError."""
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("Mock disk error")):
            mgr = DatabaseManager("test.db")
            with pytest.raises(DatabaseConnectionError):
                mgr.get_connection()


class TestSchemaLifecycle:
    """Tests for schema creation, tables, indexes, and idempotency."""

    def test_tables_and_indexes_created(self, memory_db: DatabaseManager):
        """Verify execution_history, reminder_executions, and indexes exist."""
        conn = memory_db.get_connection()
        cursor = conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'index');"
        )
        names = {row["name"] for row in cursor.fetchall()}

        assert "execution_history" in names
        assert "reminder_executions" in names
        assert "idx_reminder_executions_execution_id" in names
        assert "idx_reminder_executions_reminder_id" in names
        assert "idx_reminder_executions_contact_id" in names

    def test_init_db_is_idempotent(self, memory_db: DatabaseManager):
        """Verify calling init_db multiple times does not raise or duplicate tables."""
        memory_db.init_db()
        memory_db.init_db()
        memory_db.init_db()
        # Verify schema is unchanged and functional
        conn = memory_db.get_connection()
        cursor = conn.execute("SELECT count(*) as count FROM execution_history;")
        assert cursor.fetchone()["count"] == 0


class TestExecutionPersistence:
    """Tests for saving execution reports and data validation."""

    def test_save_execution_report_success(
        self, memory_db: DatabaseManager, sample_execution_report: SchedulerExecutionReport
    ):
        """Verify execution report and child reminder records are persisted correctly."""
        success = memory_db.save_execution_report(sample_execution_report, notes="Test run notes")
        assert success is True

        exec_row = memory_db.get_execution_by_id("exec-001")
        assert exec_row is not None
        assert exec_row["execution_id"] == "exec-001"
        assert exec_row["total_reminders_examined"] == 3
        assert exec_row["total_due"] == 2
        assert exec_row["total_simulated"] == 1
        assert exec_row["total_failed"] == 1
        assert exec_row["total_skipped"] == 1
        assert exec_row["notes"] == "Test run notes"

        results = memory_db.get_results_for_execution("exec-001")
        assert len(results) == 3
        assert results[0]["reminder_id"] == "1"
        assert results[0]["recipient"] == "alice@example.com"
        assert results[0]["processing_status"] == "simulated"
        assert results[0]["message_id"] == "sim-msg-001"

        assert results[1]["reminder_id"] == "2"
        assert results[1]["processing_status"] == "failed"
        assert results[1]["error"] == "Simulated network failure"

    def test_save_execution_report_from_dict(self, memory_db: DatabaseManager):
        """Verify saving execution report supplied as a plain dictionary."""
        report_dict = {
            "execution_id": "exec-dict-002",
            "execution_timestamp": "2026-12-01 11:00:00",
            "reference_time": "2026-12-01 11:00",
            "total_reminders_examined": 1,
            "total_due": 1,
            "total_processed": 1,
            "total_simulated": 1,
            "total_failed": 0,
            "total_skipped": 0,
            "results": [
                {
                    "reminder_id": "99",
                    "contact_id": "55",
                    "recipient": "david@example.com",
                    "subject": "Quick Update",
                    "scheduled_at": "2026-12-01 11:00",
                    "processing_status": "simulated",
                    "delivery_status": "simulated",
                    "error": None,
                    "timestamp": "2026-12-01 11:00:01",
                    "metadata": {"message_id": "msg-99"},
                }
            ],
        }

        success = memory_db.save_execution_report(report_dict)
        assert success is True

        persisted = memory_db.get_execution_by_id("exec-dict-002")
        assert persisted is not None
        assert persisted["total_simulated"] == 1

    def test_save_invalid_report_raises_database_error(self, memory_db: DatabaseManager):
        """Verify invalid report input types or missing execution_id raise DatabaseError."""
        with pytest.raises(DatabaseError, match="Invalid report type"):
            memory_db.save_execution_report("invalid string")

        with pytest.raises(DatabaseError, match="missing required 'execution_id'"):
            memory_db.save_execution_report({})

    def test_atomic_rollback_on_failure(
        self, memory_db: DatabaseManager, sample_execution_report: SchedulerExecutionReport
    ):
        """Verify transaction rollback: if child insertion fails, history record is not persisted."""
        conn = memory_db.get_connection()
        # Add a trigger that aborts when inserting reminder_id '2'
        conn.execute(
            """
            CREATE TRIGGER fail_child_insert
            BEFORE INSERT ON reminder_executions
            WHEN NEW.reminder_id = '2'
            BEGIN
                SELECT RAISE(ABORT, 'Simulated child insertion failure');
            END;
            """
        )

        # Attempt to save report containing reminder_id '2'
        with pytest.raises(DatabaseError, match="Simulated child insertion failure"):
            memory_db.save_execution_report(sample_execution_report)

        # Confirm atomicity: the execution_history record and prior child rows are rolled back completely
        assert memory_db.get_execution_by_id("exec-001") is None
        assert len(memory_db.get_results_for_execution("exec-001")) == 0


class TestQueriesAndCascade:
    """Tests for retrieval queries, metrics computation, and foreign key cascades."""

    def test_get_execution_history_ordering_and_limit(
        self, memory_db: DatabaseManager, sample_execution_report: SchedulerExecutionReport
    ):
        """Verify get_execution_history returns ordered records and respects limit."""
        # Insert 3 runs
        for i in range(1, 4):
            rep = SchedulerExecutionReport(
                execution_id=f"exec-00{i}",
                execution_timestamp=f"2026-12-01 10:0{i}:00",
                reference_time="2026-12-01 10:00",
                total_reminders_examined=1,
                total_due=1,
                total_processed=1,
                total_simulated=1,
                total_failed=0,
                total_skipped=0,
                results=[],
            )
            memory_db.save_execution_report(rep)

        history_all = memory_db.get_execution_history()
        assert len(history_all) == 3
        # Should be ordered newest first (by rowid desc)
        assert history_all[0]["execution_id"] == "exec-003"

        history_limit = memory_db.get_execution_history(limit=2)
        assert len(history_limit) == 2
        assert history_limit[0]["execution_id"] == "exec-003"
        assert history_limit[1]["execution_id"] == "exec-002"

    def test_campaign_metrics_on_empty_db(self, memory_db: DatabaseManager):
        """Verify campaign metrics on empty database returns zeroed structure with safety invariant."""
        metrics = memory_db.get_campaign_metrics()
        assert metrics["total_runs"] == 0
        assert metrics["total_simulated"] == 0
        assert metrics["actual_sent"] == 0  # Invariant
        assert metrics["simulation_success_rate"] == 0.0
        assert metrics["latest_execution_timestamp"] is None

    def test_campaign_metrics_aggregation(
        self, memory_db: DatabaseManager, sample_execution_report: SchedulerExecutionReport
    ):
        """Verify campaign metrics accurately aggregate multi-run statistics."""
        memory_db.save_execution_report(sample_execution_report)

        # Add a second run with 2 due, 2 simulated, 0 failed
        rep2 = SchedulerExecutionReport(
            execution_id="exec-002",
            execution_timestamp="2026-12-01 12:00:00",
            reference_time="2026-12-01 12:00",
            total_reminders_examined=4,
            total_due=2,
            total_processed=2,
            total_simulated=2,
            total_failed=0,
            total_skipped=2,
            results=[],
        )
        memory_db.save_execution_report(rep2)

        metrics = memory_db.get_campaign_metrics()
        assert metrics["total_runs"] == 2
        assert metrics["total_reminders_examined"] == 7
        assert metrics["total_due"] == 4
        assert metrics["total_processed"] == 4
        assert metrics["total_simulated"] == 3
        assert metrics["total_failed"] == 1
        assert metrics["total_skipped"] == 3
        assert metrics["actual_sent"] == 0  # Strict simulation safety invariant
        assert metrics["simulation_success_rate"] == 75.0  # 3/4 = 75.0%
        assert metrics["latest_execution_timestamp"] == "2026-12-01 12:00:00"

    def test_foreign_key_cascade_delete(
        self, memory_db: DatabaseManager, sample_execution_report: SchedulerExecutionReport
    ):
        """Verify deleting execution_history cascades and deletes reminder_executions."""
        memory_db.save_execution_report(sample_execution_report)
        assert len(memory_db.get_results_for_execution("exec-001")) == 3

        conn = memory_db.get_connection()
        with conn:
            conn.execute("DELETE FROM execution_history WHERE execution_id = 'exec-001';")

        assert memory_db.get_execution_by_id("exec-001") is None
        assert len(memory_db.get_results_for_execution("exec-001")) == 0

    def test_execute_query_helper(
        self, memory_db: DatabaseManager, sample_execution_report: SchedulerExecutionReport
    ):
        """Verify execute_query custom read helper."""
        memory_db.save_execution_report(sample_execution_report)
        rows = memory_db.execute_query(
            "SELECT reminder_id, recipient FROM reminder_executions WHERE processing_status = ?",
            ("simulated",),
        )
        assert len(rows) == 1
        assert rows[0]["reminder_id"] == "1"
        assert rows[0]["recipient"] == "alice@example.com"
