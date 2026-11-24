"""
Email Automation & Reminder System
Main entry point for project orchestration, pipeline verification, scheduler automation,
database persistence, and campaign reporting demonstration.
"""

import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is in sys.path when running main.py directly
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.contact_manager import ContactManager
from src.database import DatabaseManager
from src.email_sender import EmailSender
from src.logger_config import get_logger
from src.reminder_manager import ReminderManager
from src.report_generator import ReportGenerator
from src.scheduler import ReminderScheduler
from src.template_processor import TemplateProcessor

PROJECT_NAME = "Email Automation & Reminder System"
VERSION = "0.8.0"
CURRENT_PHASE = "Phase 8: Interactive Monitoring Dashboard"


def display_startup_banner() -> None:
    """Print the formatted project startup banner."""
    separator = "=" * 75
    print(separator)
    print(f" {PROJECT_NAME.upper()}")
    print(f" Version      : {VERSION}")
    print(f" Status       : {CURRENT_PHASE} - INITIALIZED")
    print(f" Root Path    : {BASE_DIR}")
    print(separator)


def run_pipeline_demonstration() -> None:
    """Orchestrate and demonstrate the complete Phase 1-7 pipeline."""
    logger = get_logger("main")
    logger.info("Starting complete Phase 1-7 demonstration pipeline.")

    # 1. Ingest and validate contacts
    contact_manager = ContactManager()
    contact_manager.load_contacts()
    contact_summary = contact_manager.get_validation_summary()

    # 2. Ingest and validate reminders with contact context
    reminder_manager = ReminderManager(contact_manager=contact_manager)
    reminder_manager.load_reminders()
    reminder_summary = reminder_manager.get_validation_summary()

    separator = "-" * 75

    # 3. Display Contact Validation Summary
    print(separator)
    print(" 1. CONTACT VALIDATION SUMMARY")
    print(separator)
    print(f"  Total Contacts Ingested  : {contact_summary['total_records']}")
    print(f"  Valid Contacts           : {contact_summary['valid_records']}")
    print(f"  Invalid Contacts         : {contact_summary['invalid_records']}")
    print(f"  Duplicate Contacts       : {contact_summary['duplicate_records']}")
    print(f"  Active Contacts          : {contact_summary['active_records']}")
    print(f"  Inactive Contacts        : {contact_summary['inactive_records']}")

    # 4. Display Reminder Validation Summary
    print(separator)
    print(" 2. REMINDER VALIDATION SUMMARY")
    print(separator)
    print(f"  Total Reminders Ingested : {reminder_summary['total_reminders']}")
    print(f"  Valid Reminders          : {reminder_summary['valid_reminders']}")
    print(f"  Invalid Reminders        : {reminder_summary['invalid_reminders']}")
    print(f"  Duplicate Reminder IDs   : {reminder_summary['duplicate_id_reminders']}")
    print(f"  Potential Duplicate Dups : {reminder_summary['potential_duplicate_reminders']}")
    print(f"  Missing Contact References: {reminder_summary['missing_contact_reminders']}")
    print(f"  Inactive Recipient Dups  : {reminder_summary['inactive_recipient_reminders']}")
    print(f"  Pending Reminders        : {reminder_summary['pending_reminders']}")
    print(f"  Sent Reminders           : {reminder_summary['sent_reminders']}")
    print(f"  Failed Reminders         : {reminder_summary['failed_reminders']}")
    print(f"  Cancelled Reminders      : {reminder_summary['cancelled_reminders']}")
    print(f"  Overdue Reminders        : {reminder_summary['overdue_reminders']}")

    # 5. Personalized Email Preview
    print(separator)
    print(" 3. PERSONALIZED EMAIL TEMPLATE PREVIEW")
    print(separator)

    eligible_pending = [
        r for r in reminder_manager.get_pending_reminders(only_active_contacts=True)
        if not r["is_overdue"]
    ]

    if eligible_pending:
        selected_reminder = eligible_pending[0]
        selected_contact = selected_reminder.get("contact_details")

        if selected_contact:
            template_processor = TemplateProcessor()
            template_processor.load_template()
            context = template_processor.build_context(selected_contact, selected_reminder)
            rendered_body = template_processor.render(context)

            print(f"  [PREVIEW RECIPIENT] : {context['name']} <{context['email']}>")
            print(f"  [PREVIEW SUBJECT]   : {context['subject']}")
            print(f"  [SCHEDULED TIME]    : {context['scheduled_at']}")
            print("-" * 75)
            print("  --- BEGIN RENDERED EMAIL BODY ---")
            for line in rendered_body.splitlines():
                print(f"  {line}")
            print("  --- END RENDERED EMAIL BODY ---")
            print("  [PREVIEW NOTE] Display only. Template personalization validated.")
    else:
        print("  (No eligible pending reminders available for template preview)")

    # 6. Scheduler Simulation-Only Execution with Database Persistence
    print(separator)
    print(" 4. SCHEDULER AUTOMATION & PERSISTENCE (SIMULATION-ONLY)")
    print(separator)

    # Initialize SQLite Database persistence layer
    db_manager = DatabaseManager()
    db_manager.init_db()

    # Use a deterministic reference time to predictably demonstrate due and future schedules
    demo_reference_time = datetime(2026, 12, 1, 12, 0)
    print(f"  [DATABASE PATH]             : {db_manager.db_path}")
    print(f"  [EVALUATION REFERENCE TIME] : {demo_reference_time.strftime('%Y-%m-%d %H:%M')}")
    print("  [EVALUATION MODE]           : SIMULATION ONLY (Guaranteed zero network/SMTP calls)")

    scheduler = ReminderScheduler(
        reminder_manager=reminder_manager,
        contact_manager=contact_manager,
        template_processor=TemplateProcessor(),
        email_sender=EmailSender(mode="simulation"),
        reference_time=demo_reference_time,
        database_manager=db_manager,
    )

    report = scheduler.run_once(reference_time=demo_reference_time)

    print("-" * 75)
    print(f"  SCHEDULER RUN SUMMARY (Execution ID: {report.execution_id}):")
    print(f"   Total Reminders Evaluated : {report.total_reminders_examined}")
    print(f"   Due Reminders Identified  : {report.total_due}")
    print(f"   Successfully Simulated    : {report.total_simulated}")
    print(f"   Failed Dispatches         : {report.total_failed}")
    print(f"   Skipped / Not Due         : {report.total_skipped}")

    print("-" * 75)
    print("  INDIVIDUAL REMINDER SCHEDULING OUTCOMES:")
    for idx, item in enumerate(report.results, start=1):
        status_label = item.processing_status.upper()
        if item.processing_status == "simulated":
            details = f"Delivered to simulation queue for {item.recipient}"
        else:
            details = item.error or "Not processed"
        print(f"   [{idx}] Reminder #{item.reminder_id} | Status: {status_label:<9} | {details}")

    # 7. Database Persistence Verification & Campaign Reporting
    print(separator)
    print(" 5. DATABASE PERSISTENCE & CAMPAIGN REPORTING")
    print(separator)

    persisted_exec = db_manager.get_execution_by_id(report.execution_id)
    persisted_results = db_manager.get_results_for_execution(report.execution_id)

    print(f"  [SQLITE PERSISTENCE VERIFIED]")
    print(f"   Execution Record in DB     : {'YES (Found)' if persisted_exec else 'NO'}")
    print(f"   Reminder Outcomes Saved    : {len(persisted_results)} records")

    report_generator = ReportGenerator(database_manager=db_manager)
    campaign_summary = report_generator.generate_campaign_summary()

    print("-" * 75)
    print("  CAMPAIGN AGGREGATE METRICS:")
    print(f"   Total Scheduler Runs      : {campaign_summary['total_runs']}")
    print(f"   Total Reminders Evaluated : {campaign_summary['total_reminders_examined']}")
    print(f"   Total Reminders Due       : {campaign_summary['total_due']}")
    print(f"   Total Dispatches Processed: {campaign_summary['total_processed']}")
    print(f"   Total Messages Simulated  : {campaign_summary['total_simulated']}")
    print(f"   Total Dispatches Failed   : {campaign_summary['total_failed']}")
    print(f"   Total Reminders Skipped   : {campaign_summary['total_skipped']}")
    print(f"   Actual Real Emails Sent   : {campaign_summary['actual_sent']} (Strict Safety Invariant)")
    print(f"   Simulation Success Rate   : {campaign_summary['simulation_success_rate']:.1f}%")

    # Export campaign summary CSV
    csv_report_path = report_generator.export_campaign_report_csv()
    detailed_report_path = report_generator.export_detailed_execution_csv(report.execution_id)

    print("-" * 75)
    print(f"  CAMPAIGN REPORT EXPORTED    : {csv_report_path}")
    print(f"  DETAILED REPORT EXPORTED    : {detailed_report_path}")

    print(separator)
    print(" [MANDATORY SAFETY STATEMENT]")
    print("  - The scheduler operates strictly in SIMULATION-ONLY mode.")
    print("  - Zero real emails were sent.")
    print("  - Zero SMTP connections were opened.")
    print("  - Source CSV data remains untouched.")
    print("=" * 75)


def main() -> None:
    """Main execution entry point."""
    display_startup_banner()
    run_pipeline_demonstration()


if __name__ == "__main__":
    main()
