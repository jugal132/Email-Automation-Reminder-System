"""
Unit tests for TemplateProcessor module.

Tests cover:
- Successful template loading
- Missing template file handling
- Empty template file handling (0-byte and whitespace)
- Placeholder detection and parsing
- Repeated placeholder deduplication
- Successful rendering with context substitution
- Multiple variable substitution
- Missing context variable handling (TemplateValidationError)
- Empty required value handling (TemplateValidationError)
- Unresolved placeholder prevention
- Custom template path support
- Special characters in context values
- Template and context error handling
- Context creation from contact and reminder records (build_context)
"""

from pathlib import Path
import pytest

from src.template_processor import (
    EmptyTemplateError,
    TemplateNotFoundError,
    TemplateProcessor,
    TemplateValidationError,
)


class TestTemplateLoading:
    """Tests for file loading and exception handling."""

    def test_successful_template_loading(self, tmp_path: Path) -> None:
        """Verify valid template content is loaded correctly from disk."""
        tpl_path = tmp_path / "valid_template.txt"
        tpl_path.write_text("Hello {{name}}, welcome to {{company}}!", encoding="utf-8")

        processor = TemplateProcessor(template_path=tpl_path)
        content = processor.load_template()

        assert content == "Hello {{name}}, welcome to {{company}}!"

    def test_missing_template_file_raises_error(self, tmp_path: Path) -> None:
        """Verify TemplateNotFoundError is raised when template file does not exist."""
        non_existent = tmp_path / "does_not_exist.txt"
        processor = TemplateProcessor(template_path=non_existent)

        with pytest.raises(TemplateNotFoundError) as exc_info:
            processor.load_template()
        assert "Template file not found" in str(exc_info.value)

    def test_zero_byte_empty_template_raises_error(self, tmp_path: Path) -> None:
        """Verify EmptyTemplateError is raised when template file is 0 bytes."""
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("", encoding="utf-8")

        processor = TemplateProcessor(template_path=empty_file)
        with pytest.raises(EmptyTemplateError) as exc_info:
            processor.load_template()
        assert "empty (0 bytes)" in str(exc_info.value)

    def test_whitespace_only_template_raises_error(self, tmp_path: Path) -> None:
        """Verify EmptyTemplateError is raised when template contains only whitespace."""
        whitespace_file = tmp_path / "whitespace.txt"
        whitespace_file.write_text("   \n\t  \n", encoding="utf-8")

        processor = TemplateProcessor(template_path=whitespace_file)
        with pytest.raises(EmptyTemplateError) as exc_info:
            processor.load_template()
        assert "only whitespace" in str(exc_info.value)

    def test_custom_template_path_argument(self, tmp_path: Path) -> None:
        """Verify load_template supports a custom path argument override."""
        custom_file = tmp_path / "override.txt"
        custom_file.write_text("Notice: {{message}}", encoding="utf-8")

        processor = TemplateProcessor()
        content = processor.load_template(custom_path=custom_file)
        assert content == "Notice: {{message}}"


class TestPlaceholderDetection:
    """Tests for extracting and identifying placeholder variables."""

    def test_placeholder_detection_single_and_multiple(self) -> None:
        """Verify single and multiple placeholder tags are extracted."""
        processor = TemplateProcessor()
        text = "Hello {{name}}, your appointment is at {{time}} for {{service}}."
        placeholders = processor.get_placeholders(template_content=text)

        assert placeholders == ["name", "time", "service"]

    def test_repeated_placeholders_deduplication(self) -> None:
        """Verify repeated placeholders are returned uniquely in order of appearance."""
        processor = TemplateProcessor()
        text = "{{name}} - {{name}}, did you get {{message}}? Thanks {{name}}!"
        placeholders = processor.get_placeholders(template_content=text)

        assert placeholders == ["name", "message"]

    def test_whitespace_inside_placeholder_braces(self) -> None:
        """Verify placeholders with interior whitespace are parsed cleanly."""
        processor = TemplateProcessor()
        text = "Hi {{  name  }}, check {{ subject }}."
        placeholders = processor.get_placeholders(template_content=text)

        assert placeholders == ["name", "subject"]

    def test_template_without_placeholders(self) -> None:
        """Verify template without placeholders returns an empty list."""
        processor = TemplateProcessor()
        text = "Static announcement with no placeholders."
        placeholders = processor.get_placeholders(template_content=text)

        assert placeholders == []


class TestTemplateRendering:
    """Tests for context validation, variable substitution, and rendering safety."""

    def test_successful_rendering_multiple_variables(self, tmp_path: Path) -> None:
        """Verify rendering replaces all occurrences of all context variables."""
        tpl_path = tmp_path / "multi.txt"
        tpl_path.write_text(
            "Hello {{name}},\nSubject: {{subject}}\n{{message}}\nDate: {{scheduled_at}}",
            encoding="utf-8",
        )
        processor = TemplateProcessor(template_path=tpl_path)
        context = {
            "name": "Alice Johnson",
            "subject": "Sprint Review",
            "message": "Please review the PRs.",
            "scheduled_at": "2026-12-01 10:00",
        }
        rendered = processor.render(context)

        expected = (
            "Hello Alice Johnson,\n"
            "Subject: Sprint Review\n"
            "Please review the PRs.\n"
            "Date: 2026-12-01 10:00"
        )
        assert rendered == expected

    def test_repeated_placeholders_rendering(self) -> None:
        """Verify all occurrences of a repeated placeholder are replaced."""
        processor = TemplateProcessor()
        text = "{{name}} is attending. See you there, {{name}}!"
        context = {"name": "Bob"}

        rendered = processor.render(context, template_content=text)
        assert rendered == "Bob is attending. See you there, Bob!"

    def test_missing_context_variable_raises_validation_error(self) -> None:
        """Verify missing context variables raise TemplateValidationError with clear details."""
        processor = TemplateProcessor()
        text = "Hello {{name}}, your code is {{code}}."
        context = {"name": "Charlie"}

        with pytest.raises(TemplateValidationError) as exc_info:
            processor.render(context, template_content=text)
        assert "Missing or empty required context variable(s)" in str(exc_info.value)
        assert "code" in str(exc_info.value)

    def test_empty_string_required_value_raises_validation_error(self) -> None:
        """Verify empty string or whitespace-only context values raise TemplateValidationError."""
        processor = TemplateProcessor()
        text = "Hello {{name}}, welcome!"
        context = {"name": "   "}

        with pytest.raises(TemplateValidationError) as exc_info:
            processor.render(context, template_content=text)
        assert "Missing or empty required context variable(s)" in str(exc_info.value)
        assert "name" in str(exc_info.value)

    def test_none_context_value_raises_validation_error(self) -> None:
        """Verify None is rejected and never formatted as string 'None'."""
        processor = TemplateProcessor()
        text = "Hello {{name}}!"
        context = {"name": None}

        with pytest.raises(TemplateValidationError) as exc_info:
            processor.render(context, template_content=text)
        assert "Missing or empty required context variable(s)" in str(exc_info.value)

    def test_special_characters_in_context_values(self) -> None:
        """Verify values containing special characters, symbols, quotes, and newlines render safely."""
        processor = TemplateProcessor()
        text = "Item: {{item}}\nNote: {{note}}"
        context = {
            "item": "R&D <Tech> & 'Hardware' $100",
            "note": "Line 1\nLine 2 with Café & naïve accents.",
        }

        rendered = processor.render(context, template_content=text)
        assert "R&D <Tech> & 'Hardware' $100" in rendered
        assert "Line 1\nLine 2 with Café & naïve accents." in rendered

    def test_arbitrary_code_not_executed(self) -> None:
        """Verify template placeholders and context strings are not executed as Python expressions."""
        processor = TemplateProcessor()
        text = "Formula: {{code}}"
        context = {"code": "__import__('os').system('echo hack')"}

        rendered = processor.render(context, template_content=text)
        assert rendered == "Formula: __import__('os').system('echo hack')"


class TestContextBuilderIntegration:
    """Tests for build_context integration helper."""

    def test_build_context_from_contact_and_reminder_records(self) -> None:
        """Verify build_context merges contact and reminder attributes cleanly."""
        contact = {
            "contact_id": "1",
            "name": "Alice Johnson",
            "email": "alice@example.com",
            "company": "Acme Corp",
            "status": "active",
        }
        reminder = {
            "reminder_id": "101",
            "contact_id": "1",
            "title": "Quarterly Checkup",
            "subject": "Project Milestones",
            "message": "Let us review deliverable dates.",
            "scheduled_at": "2026-12-01 10:00",
            "status": "pending",
        }

        context = TemplateProcessor.build_context(contact, reminder)

        assert context["name"] == "Alice Johnson"
        assert context["email"] == "alice@example.com"
        assert context["company"] == "Acme Corp"
        assert context["contact_id"] == "1"
        assert context["reminder_id"] == "101"
        assert context["title"] == "Quarterly Checkup"
        assert context["subject"] == "Project Milestones"
        assert context["message"] == "Let us review deliverable dates."
        assert context["scheduled_at"] == "2026-12-01 10:00"

    def test_render_real_project_template_with_built_context(self) -> None:
        """Verify rendering actual project templates/email_template.txt using build_context."""
        processor = TemplateProcessor()
        contact = {
            "contact_id": "5",
            "name": "Emma Watson",
            "email": "emma.watson@example.com",
            "company": "Apex Media",
        }
        reminder = {
            "reminder_id": "5",
            "contact_id": "5",
            "title": "Welcome Onboarding",
            "subject": "Welcome to the Platform",
            "message": "Thank you for joining our partner network.",
            "scheduled_at": "2026-12-12 16:00",
        }
        context = TemplateProcessor.build_context(contact, reminder)
        rendered = processor.render(context)

        assert "Hello Emma Watson," in rendered
        assert "Subject: Welcome to the Platform" in rendered
        assert "Thank you for joining our partner network." in rendered
        assert "Scheduled Time: 2026-12-12 16:00" in rendered
        assert "Best regards," in rendered
