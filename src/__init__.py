"""
Email Automation & Reminder System
Package initialization.
"""

from src.contact_manager import (
    ContactDataError,
    ContactFileNotFoundError,
    ContactManager,
    ContactManagerError,
    EmptyFileError,
    validate_email_format,
)
from src.database import (
    DatabaseConnectionError,
    DatabaseError,
    DatabaseManager,
)
from src.email_sender import (
    ConfigurationError,
    DeliveryResult,
    EmailSender,
    EmailSenderError,
    MessageConstructionError,
    SafetyGateError,
)
from src.reminder_manager import (
    ReminderDataError,
    ReminderEmptyFileError,
    ReminderFileNotFoundError,
    ReminderManager,
    ReminderManagerError,
    parse_scheduled_datetime,
)
from src.report_generator import (
    ReportGenerator,
    ReportGeneratorError,
)
from src.scheduler import (
    ReminderScheduler,
    Scheduler,
    SchedulerConfigurationError,
    SchedulerError,
    SchedulerExecutionReport,
    SchedulerReminderResult,
)
from src.template_processor import (
    EmptyTemplateError,
    TemplateNotFoundError,
    TemplateProcessor,
    TemplateProcessorError,
    TemplateValidationError,
)

__version__ = "0.8.0"

__all__ = [
    # Contact Management
    "ContactManager",
    "ContactManagerError",
    "ContactFileNotFoundError",
    "ContactDataError",
    "EmptyFileError",
    "validate_email_format",
    # Reminder Management
    "ReminderManager",
    "ReminderManagerError",
    "ReminderFileNotFoundError",
    "ReminderEmptyFileError",
    "ReminderDataError",
    "parse_scheduled_datetime",
    # Template Processing
    "TemplateProcessor",
    "TemplateProcessorError",
    "TemplateNotFoundError",
    "EmptyTemplateError",
    "TemplateValidationError",
    # Email Sender / Dispatch Engine
    "EmailSender",
    "DeliveryResult",
    "EmailSenderError",
    "MessageConstructionError",
    "ConfigurationError",
    "SafetyGateError",
    # Scheduler / Automation Engine
    "ReminderScheduler",
    "Scheduler",
    "SchedulerError",
    "SchedulerConfigurationError",
    "SchedulerReminderResult",
    "SchedulerExecutionReport",
    # Database Persistence
    "DatabaseManager",
    "DatabaseError",
    "DatabaseConnectionError",
    # Reporting & Analytics
    "ReportGenerator",
    "ReportGeneratorError",
]
