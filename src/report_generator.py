"""
Report Generator Module.

Responsible for aggregating campaign metrics, evaluating execution performance,
and exporting structured summary and detailed CSV reports to the outputs directory.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.database import DatabaseManager
from src.logger_config import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "outputs" / "campaign_reports"


class ReportGeneratorError(Exception):
    """Base exception for report generation errors."""


class ReportGenerator:
    """
    Compiles operational logs and dispatch metrics into summary reports and exports them to CSV.
    """

    def __init__(
        self,
        output_dir: Optional[Union[str, Path]] = None,
        database_manager: Optional[DatabaseManager] = None,
    ) -> None:
        """
        Initialize ReportGenerator.

        Args:
            output_dir: Directory where generated reports will be stored.
                        Defaults to 'outputs/campaign_reports' relative to project root.
            database_manager: Optional initialized DatabaseManager instance.
        """
        if output_dir is None:
            self.output_dir = DEFAULT_REPORTS_DIR
        else:
            self.output_dir = Path(output_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.database_manager = database_manager

        logger.info(
            "ReportGenerator initialized with output_dir: %s (DB manager: %s)",
            self.output_dir,
            "Connected" if self.database_manager else "None",
        )

    def _resolve_db_manager(
        self, db_manager: Optional[DatabaseManager] = None
    ) -> DatabaseManager:
        """Helper to resolve provided or instance DatabaseManager."""
        mgr = db_manager or self.database_manager
        if mgr is None:
            mgr = DatabaseManager()
        return mgr

    def generate_campaign_summary(
        self, database_manager: Optional[DatabaseManager] = None
    ) -> Dict[str, Any]:
        """
        Generate aggregate campaign metrics across all persisted scheduler runs.

        Args:
            database_manager: Optional DatabaseManager override.

        Returns:
            Dict[str, Any]: Aggregated summary metrics.
        """
        mgr = self._resolve_db_manager(database_manager)
        metrics = mgr.get_campaign_metrics()

        # Augment with human-readable summary fields
        total_runs = metrics.get("total_runs", 0)
        total_processed = metrics.get("total_processed", 0)
        total_simulated = metrics.get("total_simulated", 0)
        total_failed = metrics.get("total_failed", 0)

        summary = {
            "total_runs": total_runs,
            "total_reminders_examined": metrics.get("total_reminders_examined", 0),
            "total_due": metrics.get("total_due", 0),
            "total_processed": total_processed,
            "total_simulated": total_simulated,
            "total_failed": total_failed,
            "total_skipped": metrics.get("total_skipped", 0),
            "actual_sent": 0,  # Strict simulation safety invariant
            "simulation_success_rate": metrics.get("simulation_success_rate", 0.0),
            "latest_execution_timestamp": metrics.get("latest_execution_timestamp"),
            "is_campaign_active": total_runs > 0,
        }

        logger.info(
            "Campaign summary generated: %d runs, %d simulated, %d failed, %0.1f%% success rate.",
            summary["total_runs"],
            summary["total_simulated"],
            summary["total_failed"],
            summary["simulation_success_rate"],
        )
        return summary

    def generate_execution_report(
        self, execution_id: str, database_manager: Optional[DatabaseManager] = None
    ) -> Dict[str, Any]:
        """
        Retrieve execution details and individual reminder outcomes for a given execution run.

        Args:
            execution_id: Unique execution identifier.
            database_manager: Optional DatabaseManager override.

        Returns:
            Dict[str, Any]: Execution details and list of reminder outcomes.

        Raises:
            ReportGeneratorError: If execution record is not found.
        """
        mgr = self._resolve_db_manager(database_manager)
        exec_record = mgr.get_execution_by_id(execution_id)

        if not exec_record:
            raise ReportGeneratorError(f"Execution record with ID '{execution_id}' not found.")

        results = mgr.get_results_for_execution(execution_id)

        return {
            "execution": exec_record,
            "results": results,
            "total_results": len(results),
        }

    def export_campaign_report_csv(
        self,
        output_dir: Optional[Union[str, Path]] = None,
        filename: Optional[str] = None,
        database_manager: Optional[DatabaseManager] = None,
    ) -> Path:
        """
        Export a structured campaign execution summary CSV to the outputs directory.

        Filename format: campaign_report_YYYYMMDD_HHMMSS.csv (unless overridden).

        Args:
            output_dir: Optional output directory override.
            filename: Optional filename override.
            database_manager: Optional DatabaseManager override.

        Returns:
            Path: Absolute or resolved Path to the exported CSV file.

        Raises:
            ReportGeneratorError: If exporting fails.
        """
        target_dir = Path(output_dir) if output_dir is not None else self.output_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"campaign_report_{timestamp_str}.csv"

        filepath = target_dir / filename

        mgr = self._resolve_db_manager(database_manager)
        history = mgr.get_execution_history()

        fieldnames = [
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

        try:
            with open(filepath, mode="w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for row in history:
                    processed = row.get("total_processed", 0)
                    simulated = row.get("total_simulated", 0)
                    due = row.get("total_due", 0)
                    failed = row.get("total_failed", 0)

                    if processed > 0:
                        success_rate = round((simulated / processed) * 100, 2)
                    elif due > 0:
                        success_rate = round((simulated / due) * 100, 2)
                    else:
                        success_rate = 100.0 if failed == 0 else 0.0

                    writer.writerow(
                        {
                            "execution_id": row.get("execution_id", ""),
                            "execution_timestamp": row.get("execution_timestamp", ""),
                            "reference_time": row.get("reference_time", ""),
                            "total_reminders_examined": row.get("total_reminders_examined", 0),
                            "total_due": due,
                            "total_processed": processed,
                            "total_simulated": simulated,
                            "total_failed": failed,
                            "total_skipped": row.get("total_skipped", 0),
                            "actual_sent": 0,  # Mandatory simulation-mode indicator
                            "simulation_success_rate_pct": success_rate,
                            "notes": row.get("notes") or "",
                        }
                    )

            logger.info("Exported campaign report CSV with %d rows to: %s", len(history), filepath)
            return filepath

        except Exception as exc:
            logger.error("Failed to export campaign report CSV to %s: %s", filepath, exc)
            raise ReportGeneratorError(f"Failed to export CSV: {exc}") from exc

    def export_detailed_execution_csv(
        self,
        execution_id: str,
        output_dir: Optional[Union[str, Path]] = None,
        filename: Optional[str] = None,
        database_manager: Optional[DatabaseManager] = None,
    ) -> Path:
        """
        Export granular individual reminder outcomes for a specific execution run to CSV.

        Args:
            execution_id: Execution run ID.
            output_dir: Optional output directory override.
            filename: Optional filename override.
            database_manager: Optional DatabaseManager override.

        Returns:
            Path: Path to exported detailed CSV.

        Raises:
            ReportGeneratorError: If export fails or execution not found.
        """
        report_data = self.generate_execution_report(execution_id, database_manager=database_manager)
        results = report_data["results"]

        target_dir = Path(output_dir) if output_dir is not None else self.output_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            filename = f"detailed_execution_{execution_id}.csv"

        filepath = target_dir / filename

        fieldnames = [
            "id",
            "execution_id",
            "reminder_id",
            "contact_id",
            "recipient",
            "subject",
            "scheduled_at",
            "processing_status",
            "delivery_status",
            "error",
            "timestamp",
            "message_id",
        ]

        try:
            with open(filepath, mode="w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for r in results:
                    writer.writerow(
                        {
                            "id": r.get("id", ""),
                            "execution_id": r.get("execution_id", ""),
                            "reminder_id": r.get("reminder_id", ""),
                            "contact_id": r.get("contact_id", ""),
                            "recipient": r.get("recipient", ""),
                            "subject": r.get("subject", ""),
                            "scheduled_at": r.get("scheduled_at", ""),
                            "processing_status": r.get("processing_status", ""),
                            "delivery_status": r.get("delivery_status") or "",
                            "error": r.get("error") or "",
                            "timestamp": r.get("timestamp", ""),
                            "message_id": r.get("message_id") or "",
                        }
                    )

            logger.info("Exported detailed execution CSV (%d items) to %s", len(results), filepath)
            return filepath

        except Exception as exc:
            logger.error("Failed to export detailed execution CSV to %s: %s", filepath, exc)
            raise ReportGeneratorError(f"Failed to export detailed execution CSV: {exc}") from exc

    def format_summary_text(self, summary: Dict[str, Any]) -> str:
        """
        Format campaign summary dictionary into an aligned textual table.

        Args:
            summary: Dictionary returned by generate_campaign_summary().

        Returns:
            str: Pretty formatted textual table.
        """
        lines = [
            "=" * 50,
            " CAMPAIGN SUMMARY METRICS (SIMULATION MODE)",
            "=" * 50,
            f" Total Executions Recorded : {summary.get('total_runs', 0)}",
            f" Total Reminders Evaluated : {summary.get('total_reminders_examined', 0)}",
            f" Total Reminders Due       : {summary.get('total_due', 0)}",
            f" Total Dispatches Processed : {summary.get('total_processed', 0)}",
            f" Total Messages Simulated  : {summary.get('total_simulated', 0)}",
            f" Total Dispatches Failed   : {summary.get('total_failed', 0)}",
            f" Total Reminders Skipped   : {summary.get('total_skipped', 0)}",
            f" Actual Real Emails Sent   : {summary.get('actual_sent', 0)} (Safety Invariant)",
            f" Simulation Success Rate   : {summary.get('simulation_success_rate', 0.0):.1f}%",
            f" Latest Run Timestamp      : {summary.get('latest_execution_timestamp') or 'None'}",
            "=" * 50,
        ]
        return "\n".join(lines)
