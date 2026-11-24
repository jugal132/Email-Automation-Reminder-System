"""
Template Processor Module.

Responsible for loading email templates, detecting placeholders, validating rendering
context, and safely generating personalized email content.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.logger_config import get_logger

logger = get_logger(__name__)

# Base directory for resolving relative paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Regex matching {{placeholder_name}} with optional whitespace inside braces
# Group 1 captures the identifier name
PLACEHOLDER_REGEX = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class TemplateProcessorError(Exception):
    """Base exception for all TemplateProcessor errors."""


class TemplateNotFoundError(TemplateProcessorError, FileNotFoundError):
    """Raised when the specified template file does not exist."""


class EmptyTemplateError(TemplateProcessorError, ValueError):
    """Raised when a template file is empty (0 bytes or only whitespace)."""


class TemplateValidationError(TemplateProcessorError, ValueError):
    """Raised when required context variables are missing or empty."""


class TemplateProcessor:
    """
    Loads, validates, and renders email templates with dynamic placeholder context.
    """

    def __init__(self, template_path: Optional[str | Path] = None) -> None:
        """
        Initialize TemplateProcessor.

        Args:
            template_path: Path to the template file. If relative, resolved against
                           the project root. Defaults to 'templates/email_template.txt'.
        """
        if template_path is None:
            self.file_path = PROJECT_ROOT / "templates" / "email_template.txt"
        else:
            path_obj = Path(template_path)
            self.file_path = path_obj if path_obj.is_absolute() else PROJECT_ROOT / path_obj

        self._template_content: Optional[str] = None

    def load_template(self, custom_path: Optional[str | Path] = None) -> str:
        """
        Read the template content from disk.

        Args:
            custom_path: Optional override path to a template file.

        Returns:
            str: Raw template string.

        Raises:
            TemplateNotFoundError: If the template file does not exist.
            EmptyTemplateError: If the file is 0 bytes or contains only whitespace.
            TemplateProcessorError: If the file cannot be read.
        """
        target_path = self.file_path
        if custom_path is not None:
            path_obj = Path(custom_path)
            target_path = path_obj if path_obj.is_absolute() else PROJECT_ROOT / path_obj

        if not target_path.exists():
            raise TemplateNotFoundError(
                f"Template file not found at: '{target_path.resolve()}'"
            )

        if target_path.stat().st_size == 0:
            raise EmptyTemplateError(
                f"Template file is empty (0 bytes) at: '{target_path.resolve()}'"
            )

        try:
            content = target_path.read_text(encoding="utf-8")
        except Exception as exc:
            raise TemplateProcessorError(
                f"Failed to read template file '{target_path.resolve()}': {exc}"
            ) from exc

        if not content.strip():
            raise EmptyTemplateError(
                f"Template file contains only whitespace: '{target_path.resolve()}'"
            )

        self._template_content = content
        logger.info("Template loaded successfully from: %s", target_path.name)
        return content

    def get_placeholders(self, template_content: Optional[str] = None) -> List[str]:
        """
        Identify unique placeholder variable names present in the template.

        Repeated placeholders are identified and deduplicated while preserving appearance order.

        Args:
            template_content: Optional raw template content string. If omitted,
                              loads from the configured template file.

        Returns:
            List[str]: Unique list of placeholder names (e.g. ['name', 'subject', 'message']).
        """
        content = template_content if template_content is not None else self.load_template()
        matches = PLACEHOLDER_REGEX.findall(content)
        # Deduplicate while preserving original appearance order
        return list(dict.fromkeys(matches))

    def validate_context(
        self,
        context: Dict[str, Any],
        template_content: Optional[str] = None,
        optional_fields: Optional[Set[str]] = None,
    ) -> List[str]:
        """
        Validate that every placeholder in the template has a corresponding non-null,
        non-empty value in the context.

        Args:
            context: Dictionary containing placeholder replacement values.
            template_content: Optional raw template string.
            optional_fields: Set of placeholder names permitted to be missing or empty.

        Returns:
            List[str]: List of missing or empty placeholder keys (empty if valid).

        Raises:
            TemplateValidationError: If any required placeholder is missing or empty.
        """
        placeholders = self.get_placeholders(template_content)
        optional_set = optional_fields or set()

        missing_or_empty: List[str] = []
        for key in placeholders:
            if key in optional_set:
                continue

            if key not in context:
                missing_or_empty.append(key)
                continue

            val = context[key]
            # Disallow None and whitespace-only empty strings for required placeholders
            if val is None:
                missing_or_empty.append(key)
            elif isinstance(val, str) and not val.strip():
                missing_or_empty.append(key)

        if missing_or_empty:
            sorted_keys = sorted(list(dict.fromkeys(missing_or_empty)))
            raise TemplateValidationError(
                f"Missing or empty required context variable(s): {', '.join(sorted_keys)}"
            )

        return missing_or_empty

    def render(
        self,
        context: Dict[str, Any],
        template_content: Optional[str] = None,
        optional_fields: Optional[Set[str]] = None,
    ) -> str:
        """
        Render the template by substituting placeholder tags with context values.

        Ensures:
            - Context is strictly validated before substitution.
            - All occurrences of each placeholder are replaced safely as text.
            - No arbitrary code or expressions are evaluated.
            - No unresolved placeholders are left behind in the output.

        Args:
            context: Mapping of placeholder names to text values.
            template_content: Optional raw template string to render.
            optional_fields: Set of placeholder names that may be omitted.

        Returns:
            str: Fully rendered personalized email content.

        Raises:
            TemplateValidationError: If context is invalid or unresolved tags remain.
        """
        content = template_content if template_content is not None else self.load_template()

        # Validate that context satisfies all placeholders
        self.validate_context(context, content, optional_fields=optional_fields)

        # Safe regex replacement
        def replacer(match: re.Match) -> str:
            key = match.group(1)
            if key in context and context[key] is not None:
                return str(context[key])
            if optional_fields and key in optional_fields:
                return ""
            raise TemplateValidationError(f"Missing context value for placeholder '{key}'")

        rendered = PLACEHOLDER_REGEX.sub(replacer, content)

        # Guard against unresolved placeholders
        unresolved = PLACEHOLDER_REGEX.findall(rendered)
        if unresolved:
            raise TemplateValidationError(
                f"Unresolved placeholders remaining in rendered template: {unresolved}"
            )

        return rendered

    @staticmethod
    def build_context(contact: Dict[str, Any], reminder: Dict[str, Any]) -> Dict[str, Any]:
        """
        Construct a standardized rendering context from validated contact and reminder records.

        Args:
            contact: Contact record dictionary (from ContactManager).
            reminder: Reminder record dictionary (from ReminderManager).

        Returns:
            Dict[str, Any]: Standard context containing name, email, company, contact_id,
                            reminder_id, title, subject, message, and scheduled_at.
        """
        contact_id = str(contact.get("contact_id", "")).strip()
        reminder_id = str(reminder.get("reminder_id", "")).strip()

        context: Dict[str, Any] = {
            "name": str(contact.get("name", "")).strip(),
            "email": str(contact.get("email", "")).strip(),
            "company": str(contact.get("company", "")).strip(),
            "contact_id": contact_id,
            "reminder_id": reminder_id,
            "title": str(reminder.get("title", "")).strip(),
            "subject": str(reminder.get("subject", "")).strip(),
            "message": str(reminder.get("message", "")).strip(),
            "scheduled_at": str(reminder.get("scheduled_at", "")).strip(),
        }

        # Also preserve any extra custom fields from raw_data if available
        if "raw_data" in contact and isinstance(contact["raw_data"], dict):
            for k, v in contact["raw_data"].items():
                if k not in context and v is not None:
                    context[k] = str(v).strip()

        if "raw_data" in reminder and isinstance(reminder["raw_data"], dict):
            for k, v in reminder["raw_data"].items():
                if k not in context and v is not None:
                    context[k] = str(v).strip()

        return context
