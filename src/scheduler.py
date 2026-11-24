"""
Scheduler & Automation Engine Module.

Responsible for identifying due reminders, orchestrating the end-to-end
personalization and dispatch pipeline, and enforcing strict simulation-only
safety controls for the Email Automation & Reminder System.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from src.contact_manager import ContactManager
from src.database import DatabaseManager
from src.email_sender import DeliveryResult, EmailSender
from src.logger_config import get_logger
from src.reminder_manager import ReminderManager, parse_scheduled_datetime
from src.template_processor import TemplateProcessor, TemplateValidationError

logger = get_logger(__name__)


class SchedulerError(Exception):
    """Base exception for scheduler operations."""


class SchedulerConfigurationError(SchedulerError, ValueError):
    """Raised when scheduler dependencies or configurations are invalid."""


@dataclass
class SchedulerReminderResult:
    """
    Detailed execution outcome for an individual reminder evaluated by the scheduler.
    """

    reminder_id: str
    contact_id: str
    recipient: str
    subject: str
    scheduled_at: str
    processing_status: str  # 'simulated', 'failed', 'skipped', 'not_due'
    delivery_status: Optional[str]  # 'simulated', 'failed', or None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "reminder_id": self.reminder_id,
            "contact_id": self.contact_id,
            "recipient": self.recipient,
            "subject": self.subject,
            "scheduled_at": self.scheduled_at,
            "processing_status": self.processing_status,
            "delivery_status": self.delivery_status,
            "error": self.error,
            "timestamp": self.timestamp,
            "metadata": self.metadata or {},
        }

    def __getitem__(self, item: str) -> Any:
        """Allow subscript access for convenience."""
        return self.to_dict()[item]


@dataclass
class SchedulerExecutionReport:
    """
    Comprehensive report generated from a scheduler execution run.
    """

    execution_id: str
    execution_timestamp: str
    reference_time: str
    total_reminders_examined: int
    total_due: int
    total_processed: int
    total_simulated: int
    total_failed: int
    total_skipped: int
    results: List[SchedulerReminderResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary representation."""
        return {
            "execution_id": self.execution_id,
            "execution_timestamp": self.execution_timestamp,
            "reference_time": self.reference_time,
            "total_reminders_examined": self.total_reminders_examined,
            "total_due": self.total_due,
            "total_processed": self.total_processed,
            "total_simulated": self.total_simulated,
            "total_failed": self.total_failed,
            "total_skipped": self.total_skipped,
            "results": [r.to_dict() for r in self.results],
        }

    def __getitem__(self, item: str) -> Any:
        """Allow subscript access for convenience."""
        return self.to_dict()[item]


class ReminderScheduler:
    """
    Evaluates due reminders, coordinates contact mapping and template rendering,
    and dispatches simulated messages under strict safety boundaries.
    """

    def __init__(
        self,
        reminder_manager: Optional[ReminderManager] = None,
        contact_manager: Optional[ContactManager] = None,
        template_processor: Optional[TemplateProcessor] = None,
        email_sender: Optional[EmailSender] = None,
        reference_time: Optional[datetime] = None,
        database_manager: Optional[DatabaseManager] = None,
    ) -> None:
        """
        Initialize the ReminderScheduler with dependency injection.

        MANDATORY SAFETY BOUNDARY:
            The scheduler strictly enforces simulation-only execution. Even if
            the environment or passed EmailSender contains live SMTP settings,
            the scheduler forces mode='simulation' and only invokes simulation paths.

        Args:
            reminder_manager: Optional initialized ReminderManager.
            contact_manager: Optional initialized ContactManager.
            template_processor: Optional initialized TemplateProcessor.
            email_sender: Optional EmailSender instance (strictly forced to simulation mode).
            reference_time: Optional default datetime for time-based evaluations.
            database_manager: Optional DatabaseManager for persisting execution history.
        """
        # Resolve ContactManager
        self.contact_manager = contact_manager or ContactManager()

        # Resolve ReminderManager
        self.reminder_manager = reminder_manager or ReminderManager(contact_manager=self.contact_manager)

        # Resolve TemplateProcessor
        self.template_processor = template_processor or TemplateProcessor()

        # Resolve EmailSender: STRICTLY ENFORCE SIMULATION ONLY
        if email_sender is not None:
            # Force simulation mode to guarantee real emails are never dispatched
            email_sender.mode = "simulation"
            self.email_sender = email_sender
        else:
            self.email_sender = EmailSender(mode="simulation")

        self.reference_time = reference_time
        self.database_manager = database_manager
        logger.info(
            "ReminderScheduler initialized (Simulation-only enforcement active, Reference time: %s, Database persistence: %s).",
            self.reference_time,
            "Enabled" if self.database_manager else "Disabled",
        )

    def set_reference_time(self, ref_time: datetime) -> None:
        """Update the scheduler default reference time."""
        self.reference_time = ref_time

    def get_due_reminders(
        self, reference_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Inspect and retrieve reminders currently due and eligible for dispatch.

        Eligibility Criteria:
            1. Reminder data is valid (is_valid == True).
            2. Status is 'pending'.
            3. Scheduled datetime <= reference_time.
            4. Referenced contact exists in contact directory.
            5. Referenced contact is valid.
            6. Referenced contact is active (status == 'active').

        Args:
            reference_time: Optional evaluation timestamp (defaults to instance reference_time or now).

        Returns:
            List[Dict[str, Any]]: List of due, eligible reminder dictionaries.
        """
        eval_time = reference_time or self.reference_time or datetime.now()
        all_reminders = self.reminder_manager.get_all_reminders()

        due_reminders: List[Dict[str, Any]] = []
        for r in all_reminders:
            if not r.get("is_valid", False):
                continue
            if r.get("status", "").lower() != "pending":
                continue
            if r.get("has_missing_contact", False) or r.get("has_invalid_contact", False):
                continue
            if r.get("has_inactive_contact", False):
                continue

            # Check parsed datetime
            parsed_dt = r.get("parsed_datetime")
            if parsed_dt is None:
                parsed_dt, _ = parse_scheduled_datetime(r.get("scheduled_at"))

            if parsed_dt is not None and parsed_dt <= eval_time:
                due_reminders.append(r)

        return due_reminders

    def run_once(
        self, reference_time: Optional[datetime] = None
    ) -> SchedulerExecutionReport:
        """
        Execute a single controlled evaluation and simulated dispatch cycle.

        Processes all reminders that are due as of reference_time, safely personalizing
        and dispatching them via simulation only.

        Args:
            reference_time: Evaluation datetime. Defaults to instance reference_time or datetime.now().

        Returns:
            SchedulerExecutionReport: Comprehensive structured summary of the execution run.
        """
        eval_time = reference_time or self.reference_time or datetime.now()
        eval_time_str = eval_time.strftime("%Y-%m-%d %H:%M")
        execution_id = f"exec-{uuid.uuid4().hex[:8]}"
        exec_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        logger.info(
            "Starting scheduler run_once [Execution ID: %s, Reference Time: %s]",
            execution_id,
            eval_time_str,
        )

        all_reminders = self.reminder_manager.get_all_reminders()

        total_examined = 0
        total_due = 0
        total_processed = 0
        total_simulated = 0
        total_failed = 0
        total_skipped = 0

        # Execution-local tracking for duplicate processing prevention
        processed_reminder_ids: Set[str] = set()
        reminder_results: List[SchedulerReminderResult] = []

        for r in all_reminders:
            total_examined += 1
            reminder_id = str(r.get("reminder_id", "")).strip()
            contact_id = str(r.get("contact_id", "")).strip()
            subject = str(r.get("subject", "")).strip()
            scheduled_at = str(r.get("scheduled_at", "")).strip()
            status = str(r.get("status", "")).strip().lower()

            # Contact resolution
            contact = r.get("contact_details")
            recipient_email = contact.get("email", "") if contact else ""

            # Check validity
            if not r.get("is_valid", False):
                err_msg = f"Reminder record is invalid: {'; '.join(r.get('validation_errors', []))}"
                total_skipped += 1
                reminder_results.append(
                    SchedulerReminderResult(
                        reminder_id=reminder_id,
                        contact_id=contact_id,
                        recipient=recipient_email,
                        subject=subject,
                        scheduled_at=scheduled_at,
                        processing_status="skipped",
                        delivery_status=None,
                        error=err_msg,
                    )
                )
                continue

            # Check status eligibility (only 'pending' is eligible)
            if status != "pending":
                total_skipped += 1
                reminder_results.append(
                    SchedulerReminderResult(
                        reminder_id=reminder_id,
                        contact_id=contact_id,
                        recipient=recipient_email,
                        subject=subject,
                        scheduled_at=scheduled_at,
                        processing_status="skipped",
                        delivery_status=None,
                        error=f"Reminder status '{status}' is not eligible for scheduling (must be 'pending')",
                    )
                )
                continue

            # Check contact integrity
            if r.get("has_missing_contact", False):
                total_skipped += 1
                reminder_results.append(
                    SchedulerReminderResult(
                        reminder_id=reminder_id,
                        contact_id=contact_id,
                        recipient=recipient_email,
                        subject=subject,
                        scheduled_at=scheduled_at,
                        processing_status="skipped",
                        delivery_status=None,
                        error=f"Referenced contact_id '{contact_id}' does not exist",
                    )
                )
                continue

            if r.get("has_invalid_contact", False):
                total_skipped += 1
                reminder_results.append(
                    SchedulerReminderResult(
                        reminder_id=reminder_id,
                        contact_id=contact_id,
                        recipient=recipient_email,
                        subject=subject,
                        scheduled_at=scheduled_at,
                        processing_status="skipped",
                        delivery_status=None,
                        error=f"Referenced contact_id '{contact_id}' is invalid",
                    )
                )
                continue

            if r.get("has_inactive_contact", False):
                total_skipped += 1
                reminder_results.append(
                    SchedulerReminderResult(
                        reminder_id=reminder_id,
                        contact_id=contact_id,
                        recipient=recipient_email,
                        subject=subject,
                        scheduled_at=scheduled_at,
                        processing_status="skipped",
                        delivery_status=None,
                        error=f"Referenced contact_id '{contact_id}' has status 'inactive' (ineligible for automated dispatch)",
                    )
                )
                continue

            # Evaluate scheduled time
            parsed_dt = r.get("parsed_datetime")
            if parsed_dt is None:
                parsed_dt, _ = parse_scheduled_datetime(scheduled_at)

            if parsed_dt is None:
                total_skipped += 1
                reminder_results.append(
                    SchedulerReminderResult(
                        reminder_id=reminder_id,
                        contact_id=contact_id,
                        recipient=recipient_email,
                        subject=subject,
                        scheduled_at=scheduled_at,
                        processing_status="skipped",
                        delivery_status=None,
                        error="Cannot evaluate schedule: unparseable datetime format",
                    )
                )
                continue

            if parsed_dt > eval_time:
                # Scheduled in future -> Not due
                total_skipped += 1
                reminder_results.append(
                    SchedulerReminderResult(
                        reminder_id=reminder_id,
                        contact_id=contact_id,
                        recipient=recipient_email,
                        subject=subject,
                        scheduled_at=scheduled_at,
                        processing_status="not_due",
                        delivery_status=None,
                        error=f"Scheduled in future ({scheduled_at} > {eval_time_str})",
                    )
                )
                continue

            # Reminder is due
            total_due += 1

            # In-memory duplicate processing protection
            if reminder_id in processed_reminder_ids:
                total_skipped += 1
                err_dup = (
                    f"Duplicate execution prevented: reminder #{reminder_id} "
                    f"has already been processed in execution {execution_id}"
                )
                logger.warning(err_dup)
                reminder_results.append(
                    SchedulerReminderResult(
                        reminder_id=reminder_id,
                        contact_id=contact_id,
                        recipient=recipient_email,
                        subject=subject,
                        scheduled_at=scheduled_at,
                        processing_status="skipped",
                        delivery_status=None,
                        error=err_dup,
                    )
                )
                continue

            # Register into execution tracking set
            processed_reminder_ids.add(reminder_id)

            # Process due reminder through pipeline
            try:
                # 1. Ensure contact details are populated
                if not contact:
                    raise SchedulerError(f"Missing contact details for contact_id '{contact_id}'")

                # 2. Build personalization context
                context = self.template_processor.build_context(contact, r)

                # 3. Render template
                rendered_body = self.template_processor.render(context)
                target_recipient = str(context["email"])
                target_subject = str(context["subject"])

                # 4. Construct message
                message = self.email_sender.create_message(
                    recipient=target_recipient,
                    subject=target_subject,
                    body=rendered_body,
                )

                # 5. Dispatch via SIMULATION ONLY
                delivery_res: DeliveryResult = self.email_sender.send_simulated(
                    message=message,
                    metadata={"execution_id": execution_id, "reminder_id": reminder_id},
                )

                total_processed += 1
                total_simulated += 1

                logger.info(
                    "Scheduler simulated dispatch for reminder #%s -> %s [Subject: %s]",
                    reminder_id,
                    target_recipient,
                    target_subject,
                )

                reminder_results.append(
                    SchedulerReminderResult(
                        reminder_id=reminder_id,
                        contact_id=contact_id,
                        recipient=target_recipient,
                        subject=target_subject,
                        scheduled_at=scheduled_at,
                        processing_status="simulated",
                        delivery_status=delivery_res.status,
                        error=None,
                        metadata={
                            "message_id": delivery_res.message_id,
                            "execution_id": execution_id,
                        },
                    )
                )

            except Exception as exc:
                total_processed += 1
                total_failed += 1
                err_detail = f"Processing pipeline failed for reminder #{reminder_id}: {exc}"
                logger.error("%s", err_detail)
                reminder_results.append(
                    SchedulerReminderResult(
                        reminder_id=reminder_id,
                        contact_id=contact_id,
                        recipient=recipient_email,
                        subject=subject,
                        scheduled_at=scheduled_at,
                        processing_status="failed",
                        delivery_status="failed",
                        error=err_detail,
                    )
                )

        report = SchedulerExecutionReport(
            execution_id=execution_id,
            execution_timestamp=exec_timestamp,
            reference_time=eval_time_str,
            total_reminders_examined=total_examined,
            total_due=total_due,
            total_processed=total_processed,
            total_simulated=total_simulated,
            total_failed=total_failed,
            total_skipped=total_skipped,
            results=reminder_results,
        )

        # Fault-tolerant persistence integration
        if self.database_manager is not None:
            try:
                self.database_manager.save_execution_report(report)
                logger.info("Persisted execution report %s to database.", execution_id)
            except Exception as exc:
                # Isolate failure: persistence failure must never crash the in-memory execution pipeline
                logger.error(
                    "Failed to persist execution report %s to database: %s. Continuing in-memory execution.",
                    execution_id,
                    exc,
                )

        logger.info(
            "Scheduler run completed: %d examined, %d due, %d simulated, %d failed, %d skipped.",
            total_examined,
            total_due,
            total_simulated,
            total_failed,
            total_skipped,
        )

        return report


# Provide alias for flexible naming conventions
Scheduler = ReminderScheduler
