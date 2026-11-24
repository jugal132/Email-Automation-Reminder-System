"""
Database Persistence Module.

Provides SQLite persistence for scheduler execution history, reminder outcomes,
and campaign metrics with strict relational integrity, parameterization, and fault tolerance.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.logger_config import get_logger

logger = get_logger(__name__)

# Base project directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "email_automation.db"


class DatabaseError(Exception):
    """Base exception for database operations."""


class DatabaseConnectionError(DatabaseError):
    """Raised when establishing or managing a database connection fails."""


class DatabaseManager:
    """
    Manages SQLite database connections, schema lifecycle, and transaction management
    for scheduler execution history and individual reminder delivery outcomes.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        """
        Initialize DatabaseManager.

        Args:
            db_path: Path to SQLite database file, or ':memory:' for an in-memory database.
                     Defaults to 'data/email_automation.db' relative to project root.
        """
        if db_path is None:
            self.db_path = str(DEFAULT_DB_PATH)
        else:
            self.db_path = str(db_path)

        self._connection: Optional[sqlite3.Connection] = None
        self._is_memory = self.db_path == ":memory:"

        # Ensure parent directory exists for filesystem databases
        if not self._is_memory:
            path_obj = Path(self.db_path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)

        logger.info("DatabaseManager initialized with db_path: %s", self.db_path)

    def get_connection(self) -> sqlite3.Connection:
        """
        Retrieve or establish an active SQLite connection.
        Enforces foreign key constraints and dictionary-like row access.

        Returns:
            sqlite3.Connection: Active database connection.

        Raises:
            DatabaseConnectionError: If connection cannot be established.
        """
        try:
            if self._connection is None:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON;")
                self._connection = conn
            return self._connection
        except sqlite3.Error as exc:
            logger.error("Failed to connect to SQLite database at %s: %s", self.db_path, exc)
            raise DatabaseConnectionError(f"Database connection error: {exc}") from exc

    def close(self) -> None:
        """Close the active database connection if open."""
        if self._connection is not None:
            try:
                self._connection.close()
                logger.info("Database connection closed for: %s", self.db_path)
            except sqlite3.Error as exc:
                logger.warning("Error while closing database connection: %s", exc)
            finally:
                self._connection = None

    def __enter__(self) -> "DatabaseManager":
        """Context manager entry point."""
        self.get_connection()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit point; closes connection."""
        self.close()

    def init_db(self) -> None:
        """
        Initialize database tables and indexes idempotently.

        Creates:
            1. execution_history: Tracks overall scheduler runs.
            2. reminder_executions: Tracks outcomes for individual reminders evaluated per run.
            3. Associated indexes for performant lookups and foreign keys.

        Raises:
            DatabaseError: If schema creation fails.
        """
        create_execution_history_sql = """
        CREATE TABLE IF NOT EXISTS execution_history (
            execution_id TEXT PRIMARY KEY,
            execution_timestamp TEXT NOT NULL,
            reference_time TEXT NOT NULL,
            total_reminders_examined INTEGER NOT NULL,
            total_due INTEGER NOT NULL,
            total_processed INTEGER NOT NULL,
            total_simulated INTEGER NOT NULL,
            total_failed INTEGER NOT NULL,
            total_skipped INTEGER NOT NULL,
            notes TEXT
        );
        """

        create_reminder_executions_sql = """
        CREATE TABLE IF NOT EXISTS reminder_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT NOT NULL,
            reminder_id TEXT NOT NULL,
            contact_id TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            processing_status TEXT NOT NULL,
            delivery_status TEXT,
            error TEXT,
            timestamp TEXT NOT NULL,
            message_id TEXT,
            FOREIGN KEY (execution_id) REFERENCES execution_history(execution_id) ON DELETE CASCADE
        );
        """

        create_indexes_sql = [
            "CREATE INDEX IF NOT EXISTS idx_reminder_executions_execution_id ON reminder_executions(execution_id);",
            "CREATE INDEX IF NOT EXISTS idx_reminder_executions_reminder_id ON reminder_executions(reminder_id);",
            "CREATE INDEX IF NOT EXISTS idx_reminder_executions_contact_id ON reminder_executions(contact_id);",
        ]

        conn = self.get_connection()
        try:
            with conn:
                conn.execute(create_execution_history_sql)
                conn.execute(create_reminder_executions_sql)
                for index_sql in create_indexes_sql:
                    conn.execute(index_sql)
            logger.info("Database schema and indexes initialized successfully for: %s", self.db_path)
        except sqlite3.Error as exc:
            logger.error("Failed to initialize database schema: %s", exc)
            raise DatabaseError(f"Schema initialization failed: {exc}") from exc

    def save_execution_report(
        self,
        report: Any,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Persist a scheduler execution report and all of its individual reminder outcomes
        atomically within a single database transaction.

        If any error occurs during insertion, the transaction is rolled back completely.

        Args:
            report: SchedulerExecutionReport dataclass instance or dictionary.
            notes: Optional descriptive notes for the execution run.

        Returns:
            bool: True if persistence succeeded.

        Raises:
            DatabaseError: If insertion fails or transaction rolls back.
        """
        # Ensure schema exists
        self.init_db()

        # Normalize input to dictionary or object attributes
        if hasattr(report, "to_dict"):
            data = report.to_dict()
        elif isinstance(report, dict):
            data = report
        else:
            raise DatabaseError("Invalid report type: must be SchedulerExecutionReport or dict")

        execution_id = str(data.get("execution_id", ""))
        if not execution_id:
            raise DatabaseError("Execution report is missing required 'execution_id'")

        exec_timestamp = str(data.get("execution_timestamp", ""))
        reference_time = str(data.get("reference_time", ""))
        total_examined = int(data.get("total_reminders_examined", 0))
        total_due = int(data.get("total_due", 0))
        total_processed = int(data.get("total_processed", 0))
        total_simulated = int(data.get("total_simulated", 0))
        total_failed = int(data.get("total_failed", 0))
        total_skipped = int(data.get("total_skipped", 0))
        results = data.get("results", [])

        conn = self.get_connection()

        insert_history_sql = """
        INSERT INTO execution_history (
            execution_id, execution_timestamp, reference_time,
            total_reminders_examined, total_due, total_processed,
            total_simulated, total_failed, total_skipped, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """

        insert_result_sql = """
        INSERT INTO reminder_executions (
            execution_id, reminder_id, contact_id, recipient,
            subject, scheduled_at, processing_status, delivery_status,
            error, timestamp, message_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """

        try:
            with conn:
                # 1. Insert execution history record
                conn.execute(
                    insert_history_sql,
                    (
                        execution_id,
                        exec_timestamp,
                        reference_time,
                        total_examined,
                        total_due,
                        total_processed,
                        total_simulated,
                        total_failed,
                        total_skipped,
                        notes,
                    ),
                )

                # 2. Insert each reminder execution record
                for res in results:
                    if hasattr(res, "to_dict"):
                        res_dict = res.to_dict()
                    elif isinstance(res, dict):
                        res_dict = res
                    else:
                        continue

                    # Extract message_id from metadata if present
                    meta = res_dict.get("metadata") or {}
                    msg_id = meta.get("message_id") if isinstance(meta, dict) else None

                    conn.execute(
                        insert_result_sql,
                        (
                            execution_id,
                            str(res_dict.get("reminder_id", "")),
                            str(res_dict.get("contact_id", "")),
                            str(res_dict.get("recipient", "")),
                            str(res_dict.get("subject", "")),
                            str(res_dict.get("scheduled_at", "")),
                            str(res_dict.get("processing_status", "")),
                            res_dict.get("delivery_status"),
                            res_dict.get("error"),
                            str(res_dict.get("timestamp", "")),
                            msg_id,
                        ),
                    )

            logger.info(
                "Persisted execution report %s with %d reminder results to SQLite.",
                execution_id,
                len(results),
            )
            return True

        except sqlite3.Error as exc:
            logger.error("Database transaction failed for execution %s: %s", execution_id, exc)
            raise DatabaseError(f"Failed to persist execution report: {exc}") from exc

    def get_execution_by_id(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single execution history record by its execution_id.

        Args:
            execution_id: Unique execution identifier.

        Returns:
            Optional[Dict[str, Any]]: Execution dictionary if found, else None.
        """
        self.init_db()
        conn = self.get_connection()
        query = "SELECT * FROM execution_history WHERE execution_id = ?;"
        try:
            cursor = conn.execute(query, (execution_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as exc:
            logger.error("Query failed for execution_id %s: %s", execution_id, exc)
            raise DatabaseError(f"Query error: {exc}") from exc

    def get_execution_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve all execution history records ordered by execution_timestamp descending.

        Args:
            limit: Optional maximum number of records to return.

        Returns:
            List[Dict[str, Any]]: List of execution history records.
        """
        self.init_db()
        conn = self.get_connection()
        query = "SELECT * FROM execution_history ORDER BY rowid DESC"
        params: Tuple[Any, ...] = ()
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params = (limit,)
        query += ";"

        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Failed to query execution history: %s", exc)
            raise DatabaseError(f"Query error: {exc}") from exc

    def get_results_for_execution(self, execution_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all individual reminder outcomes for a given execution_id.

        Args:
            execution_id: Unique execution identifier.

        Returns:
            List[Dict[str, Any]]: List of reminder execution dictionaries.
        """
        self.init_db()
        conn = self.get_connection()
        query = "SELECT * FROM reminder_executions WHERE execution_id = ? ORDER BY id ASC;"
        try:
            cursor = conn.execute(query, (execution_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Query failed for results of execution %s: %s", execution_id, exc)
            raise DatabaseError(f"Query error: {exc}") from exc

    def get_all_reminder_executions(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve all reminder execution outcomes across all scheduler runs.

        Args:
            limit: Optional maximum number of records to retrieve.

        Returns:
            List[Dict[str, Any]]: List of reminder execution outcome records.
        """
        self.init_db()
        conn = self.get_connection()
        query = "SELECT * FROM reminder_executions ORDER BY id DESC"
        params: Tuple[Any, ...] = ()
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params = (limit,)
        query += ";"

        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Failed to query all reminder executions: %s", exc)
            raise DatabaseError(f"Query error: {exc}") from exc

    def get_campaign_metrics(self) -> Dict[str, Any]:
        """
        Aggregate operational campaign metrics across all persisted scheduler runs.

        Returns:
            Dict[str, Any]: Summary metrics containing total runs, reminders examined,
                            due count, simulated count, failed count, skipped count,
                            actual_sent count (guaranteed 0 under simulation safety),
                            and success rate percentage.
        """
        self.init_db()
        conn = self.get_connection()

        query = """
        SELECT
            COUNT(*) as total_runs,
            COALESCE(SUM(total_reminders_examined), 0) as total_examined,
            COALESCE(SUM(total_due), 0) as total_due,
            COALESCE(SUM(total_processed), 0) as total_processed,
            COALESCE(SUM(total_simulated), 0) as total_simulated,
            COALESCE(SUM(total_failed), 0) as total_failed,
            COALESCE(SUM(total_skipped), 0) as total_skipped,
            MAX(execution_timestamp) as latest_execution_timestamp
        FROM execution_history;
        """

        try:
            cursor = conn.execute(query)
            row = cursor.fetchone()
            if not row or row["total_runs"] == 0:
                return {
                    "total_runs": 0,
                    "total_reminders_examined": 0,
                    "total_due": 0,
                    "total_processed": 0,
                    "total_simulated": 0,
                    "total_failed": 0,
                    "total_skipped": 0,
                    "actual_sent": 0,  # Strict simulation safety invariant
                    "simulation_success_rate": 0.0,
                    "latest_execution_timestamp": None,
                }

            total_sim = int(row["total_simulated"])
            total_due = int(row["total_due"])
            total_failed = int(row["total_failed"])
            total_processed = int(row["total_processed"])

            # Success rate based on processed/due simulated vs failures
            if total_processed > 0:
                success_rate = round((total_sim / total_processed) * 100, 2)
            elif total_due > 0:
                success_rate = round((total_sim / total_due) * 100, 2)
            else:
                success_rate = 100.0 if total_failed == 0 and int(row["total_runs"]) > 0 else 0.0

            return {
                "total_runs": int(row["total_runs"]),
                "total_reminders_examined": int(row["total_examined"]),
                "total_due": total_due,
                "total_processed": total_processed,
                "total_simulated": total_sim,
                "total_failed": total_failed,
                "total_skipped": int(row["total_skipped"]),
                "actual_sent": 0,  # Zero real emails sent under simulation mode
                "simulation_success_rate": success_rate,
                "latest_execution_timestamp": row["latest_execution_timestamp"],
            }
        except sqlite3.Error as exc:
            logger.error("Failed to calculate campaign metrics: %s", exc)
            raise DatabaseError(f"Metrics aggregation error: {exc}") from exc

    def execute_query(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
        """
        Execute an arbitrary parameterized read query against the database.

        Args:
            query: SQL query string.
            params: Optional tuple of query parameters.

        Returns:
            List[Dict[str, Any]]: Query result rows as dictionaries.
        """
        self.init_db()
        conn = self.get_connection()
        try:
            cursor = conn.execute(query, params or ())
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Failed to execute query '%s': %s", query, exc)
            raise DatabaseError(f"Query execution failed: {exc}") from exc
