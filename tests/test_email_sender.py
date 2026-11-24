"""
Unit tests for EmailSender module.

Tests cover:
- Message construction (MIME headers, body, special characters, error handling)
- Simulation mode behavior (no network calls, structured result)
- Configuration validation (missing/invalid fields)
- Safety gate controls (blocking live mode unless opted in via ALLOW_REAL_EMAILS=true)
- Mocked SMTP connections (SSL and STARTTLS, authentication, timeouts, exceptions, cleanup)
- Zero credential leakage in errors and logs
- DeliveryResult structure and status representations
"""

import smtplib
import socket
from unittest.mock import MagicMock, patch
import pytest

from src.email_sender import (
    ConfigurationError,
    DeliveryResult,
    EmailSender,
    MessageConstructionError,
)


class TestMessageConstruction:
    """Tests for EmailMessage creation and MIME header formatting."""

    def test_valid_message_construction(self) -> None:
        """Verify message is created with expected From, To, Subject, and body."""
        sender = EmailSender(mode="simulation")
        msg = sender.create_message(
            recipient="test@example.com",
            subject="Test Subject",
            body="Hello World Body",
            sender="custom@example.com",
        )

        assert msg["To"] == "test@example.com"
        assert msg["Subject"] == "Test Subject"
        assert msg["From"] == "custom@example.com"
        assert msg.get_content().strip() == "Hello World Body"
        assert "Message-ID" in msg

    def test_default_sender_fallback(self) -> None:
        """Verify message creation falls back to configured sender if sender argument is None."""
        sender = EmailSender(
            mode="simulation",
            config={"SMTP_SENDER": "default.sender@example.com"},
        )
        msg = sender.create_message(
            recipient="user@example.com",
            subject="Default Sender Test",
            body="Content",
        )
        assert msg["From"] == "default.sender@example.com"

    def test_special_characters_and_unicode_in_message(self) -> None:
        """Verify emojis, quotes, accents, and special symbols are safely encoded."""
        sender = EmailSender(mode="simulation")
        subject = "Important: Q1 Update & Highlights 🚀 (50% Off)"
        body = "Hello René,\nSpecial characters: <tag> & 'quote' $100.\nUnicode: नमस्ते / 你好"

        msg = sender.create_message(
            recipient="rene@example.com",
            subject=subject,
            body=body,
        )

        assert msg["Subject"] == subject
        assert "50% Off" in msg["Subject"]
        assert "René" in msg.get_content()
        assert "<tag> & 'quote' $100" in msg.get_content()

    def test_empty_recipient_raises_construction_error(self) -> None:
        """Verify empty recipient raises MessageConstructionError."""
        sender = EmailSender(mode="simulation")
        with pytest.raises(MessageConstructionError) as exc_info:
            sender.create_message(recipient="   ", subject="Subject", body="Body")
        assert "Recipient email address must be non-empty" in str(exc_info.value)

    def test_empty_subject_raises_construction_error(self) -> None:
        """Verify empty subject raises MessageConstructionError."""
        sender = EmailSender(mode="simulation")
        with pytest.raises(MessageConstructionError) as exc_info:
            sender.create_message(recipient="user@example.com", subject="   ", body="Body")
        assert "subject line must be non-empty" in str(exc_info.value).lower()

    def test_none_body_raises_construction_error(self) -> None:
        """Verify None body raises MessageConstructionError."""
        sender = EmailSender(mode="simulation")
        with pytest.raises(MessageConstructionError) as exc_info:
            sender.create_message(recipient="user@example.com", subject="Subject", body=None)  # type: ignore
        assert "body cannot be None" in str(exc_info.value)


class TestSimulationMode:
    """Tests for safe simulation mode behavior."""

    @patch("smtplib.SMTP")
    @patch("smtplib.SMTP_SSL")
    def test_simulation_never_attempts_network_connection(
        self, mock_smtp_ssl: MagicMock, mock_smtp: MagicMock
    ) -> None:
        """Verify that simulation mode never touches smtplib or opens network sockets."""
        sender = EmailSender(mode="simulation")
        result = sender.send_email(
            recipient="alice@example.com",
            subject="Simulation Check",
            body="Simulated message content",
            metadata={"source": "test"},
        )

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0

        assert result.success is True
        assert result.mode == "simulation"
        assert result.status == "simulated"
        assert result.recipient == "alice@example.com"
        assert result.subject == "Simulation Check"
        assert result.error is None
        assert result.metadata == {"source": "test"}
        assert result.timestamp != ""
        assert result.message_id is not None

    def test_simulation_without_credentials_succeeds(self) -> None:
        """Verify simulation mode executes successfully even when zero SMTP credentials are provided."""
        sender = EmailSender(
            mode="simulation",
            config={
                "SMTP_HOST": "",
                "SMTP_USERNAME": "",
                "SMTP_PASSWORD": "",
            },
        )
        result = sender.send_email(
            recipient="bob@example.com",
            subject="No Credentials Needed",
            body="Testing clean simulation",
        )
        assert result.status == "simulated"
        assert result.success is True


class TestConfigurationAndSafetyGate:
    """Tests for configuration validation and the safety lock."""

    def test_invalid_mode_raises_configuration_error(self) -> None:
        """Verify initializing with an unknown mode raises ConfigurationError."""
        with pytest.raises(ConfigurationError) as exc_info:
            EmailSender(mode="unsupported_mode")
        assert "Unsupported email mode" in str(exc_info.value)

    def test_validate_smtp_config_identifies_missing_settings(self) -> None:
        """Verify missing host, port, credentials, and sender are flagged."""
        sender = EmailSender(
            mode="simulation",
            config={
                "SMTP_HOST": "",
                "SMTP_PORT": "invalid_port",
                "SMTP_USERNAME": "",
                "SMTP_PASSWORD": "",
                "SMTP_SENDER": "",
                "EMAIL_FROM": "",
            },
        )
        is_valid, errors = sender.validate_smtp_config()
        assert is_valid is False
        assert any("SMTP_HOST" in e for e in errors)
        assert any("SMTP_PORT" in e for e in errors)
        assert any("SMTP_USERNAME" in e for e in errors)
        assert any("SMTP_PASSWORD" in e for e in errors)
        assert any("SMTP_SENDER" in e for e in errors)

    def test_safety_gate_blocks_live_when_allow_real_emails_is_false(self) -> None:
        """Verify live mode is blocked when ALLOW_REAL_EMAILS is false."""
        sender = EmailSender(
            mode="live",
            config={
                "ALLOW_REAL_EMAILS": "false",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": 587,
                "SMTP_USERNAME": "user@example.com",
                "SMTP_PASSWORD": "secret_password",
            },
        )
        assert sender.is_safety_gate_open() is False

        result = sender.send_email(
            recipient="target@example.com",
            subject="Blocked Test",
            body="This should not send",
        )

        assert result.status == "blocked"
        assert result.success is False
        assert "blocked by safety lock" in result.error.lower()

    def test_safety_gate_blocks_live_when_allow_real_emails_is_omitted(self) -> None:
        """Verify live mode is blocked by default when ALLOW_REAL_EMAILS is absent."""
        sender = EmailSender(
            mode="live",
            config={
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": 587,
                "SMTP_USERNAME": "user@example.com",
                "SMTP_PASSWORD": "secret_password",
            },
        )
        assert sender.is_safety_gate_open() is False

        result = sender.send_email(
            recipient="target@example.com",
            subject="Omitted Gate Test",
            body="Blocked",
        )
        assert result.status == "blocked"
        assert result.success is False

    def test_safety_gate_blocks_when_mode_is_simulation_even_if_allow_is_true(self) -> None:
        """Verify simulation mode is never treated as live sending even if ALLOW_REAL_EMAILS is true."""
        sender = EmailSender(
            mode="simulation",
            config={"ALLOW_REAL_EMAILS": "true"},
        )
        assert sender.is_safety_gate_open() is False
        result = sender.send_email(
            recipient="test@example.com",
            subject="Simulation Prevails",
            body="Content",
        )
        assert result.status == "simulated"


class TestMockedSMTPDelivery:
    """Tests for isolated, mocked SMTP delivery scenarios."""

    @patch("smtplib.SMTP")
    def test_successful_mocked_smtp_starttls_send(self, mock_smtp_class: MagicMock) -> None:
        """Verify successful connection, STARTTLS, login, and send on port 587."""
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        sender = EmailSender(
            mode="live",
            config={
                "ALLOW_REAL_EMAILS": "true",
                "SMTP_HOST": "smtp.mockserver.com",
                "SMTP_PORT": 587,
                "SMTP_USERNAME": "mock_user@mockserver.com",
                "SMTP_PASSWORD": "mock_password_123",
                "SMTP_SENDER": "noreply@mockserver.com",
                "SMTP_TIMEOUT": 5.0,
            },
        )
        assert sender.is_safety_gate_open() is True

        result = sender.send_email(
            recipient="customer@example.com",
            subject="Invoice #101",
            body="Your invoice is ready.",
        )

        # Assert SMTP lifecycle
        mock_smtp_class.assert_called_once_with(host="smtp.mockserver.com", port=587, timeout=5.0)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("mock_user@mockserver.com", "mock_password_123")
        mock_server.send_message.assert_called_once()
        mock_server.quit.assert_called_once()

        assert result.status == "sent"
        assert result.success is True
        assert result.error is None
        assert result.recipient == "customer@example.com"

    @patch("smtplib.SMTP_SSL")
    def test_successful_mocked_smtp_ssl_send(self, mock_ssl_class: MagicMock) -> None:
        """Verify port 465 employs SMTP_SSL directly."""
        mock_server = MagicMock()
        mock_ssl_class.return_value = mock_server

        sender = EmailSender(
            mode="live",
            config={
                "ALLOW_REAL_EMAILS": "true",
                "SMTP_HOST": "smtp.sslserver.com",
                "SMTP_PORT": 465,
                "SMTP_USERNAME": "ssl_user@sslserver.com",
                "SMTP_PASSWORD": "ssl_password_456",
                "SMTP_SENDER": "ssl@sslserver.com",
            },
        )

        result = sender.send_email(
            recipient="client@example.com",
            subject="SSL Subject",
            body="SSL Content",
        )

        assert mock_ssl_class.call_count == 1
        mock_server.login.assert_called_once_with("ssl_user@sslserver.com", "ssl_password_456")
        mock_server.send_message.assert_called_once()
        mock_server.quit.assert_called_once()

        assert result.status == "sent"
        assert result.success is True

    @patch("smtplib.SMTP")
    def test_mocked_smtp_authentication_failure(self, mock_smtp_class: MagicMock) -> None:
        """Verify authentication failure returns status 'failed' without leaking password."""
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server
        secret = "ultra_secret_password_xyz"
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")

        sender = EmailSender(
            mode="live",
            config={
                "ALLOW_REAL_EMAILS": "true",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": 587,
                "SMTP_USERNAME": "test_user",
                "SMTP_PASSWORD": secret,
                "SMTP_SENDER": "noreply@example.com",
            },
        )

        result = sender.send_email(
            recipient="test@example.com",
            subject="Auth Test",
            body="Body",
        )

        assert result.status == "failed"
        assert result.success is False
        assert "authentication failed" in result.error.lower()
        # Security Assertion: password must never be in error message
        assert secret not in str(result.error)
        mock_server.quit.assert_called_once()

    @patch("smtplib.SMTP")
    def test_mocked_smtp_connection_failure(self, mock_smtp_class: MagicMock) -> None:
        """Verify connection error returns status 'failed' cleanly."""
        mock_smtp_class.side_effect = smtplib.SMTPConnectError(421, b"Connection refused")

        sender = EmailSender(
            mode="live",
            config={
                "ALLOW_REAL_EMAILS": "true",
                "SMTP_HOST": "unreachable.smtp.com",
                "SMTP_PORT": 587,
                "SMTP_USERNAME": "test_user",
                "SMTP_PASSWORD": "password",
                "SMTP_SENDER": "noreply@example.com",
            },
        )

        result = sender.send_email(
            recipient="test@example.com",
            subject="Connect Error Test",
            body="Body",
        )

        assert result.status == "failed"
        assert result.success is False
        assert "failed to connect" in result.error.lower()

    @patch("smtplib.SMTP")
    def test_mocked_smtp_timeout(self, mock_smtp_class: MagicMock) -> None:
        """Verify socket timeout returns status 'failed'."""
        mock_smtp_class.side_effect = socket.timeout("Timed out waiting for response")

        sender = EmailSender(
            mode="live",
            config={
                "ALLOW_REAL_EMAILS": "true",
                "SMTP_HOST": "slow.smtp.com",
                "SMTP_PORT": 587,
                "SMTP_USERNAME": "test_user",
                "SMTP_PASSWORD": "password",
                "SMTP_SENDER": "noreply@example.com",
                "SMTP_TIMEOUT": 3.0,
            },
        )

        result = sender.send_email(
            recipient="test@example.com",
            subject="Timeout Test",
            body="Body",
        )

        assert result.status == "failed"
        assert result.success is False
        assert "timed out" in result.error.lower()

    @patch("smtplib.SMTP")
    def test_mocked_smtp_generic_exception(self, mock_smtp_class: MagicMock) -> None:
        """Verify generic SMTPException is captured and reported."""
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server
        mock_server.send_message.side_effect = smtplib.SMTPException("Mailbox full")

        sender = EmailSender(
            mode="live",
            config={
                "ALLOW_REAL_EMAILS": "true",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": 587,
                "SMTP_USERNAME": "user",
                "SMTP_PASSWORD": "pwd",
                "SMTP_SENDER": "noreply@example.com",
            },
        )

        result = sender.send_email(
            recipient="test@example.com",
            subject="Protocol Error Test",
            body="Body",
        )

        assert result.status == "failed"
        assert result.success is False
        assert "protocol error" in result.error.lower()
        mock_server.quit.assert_called_once()


class TestDeliveryResultStructure:
    """Tests for DeliveryResult data structure and representation."""

    def test_delivery_result_dictionary_and_subscript_access(self) -> None:
        """Verify to_dict and subscript access work as expected."""
        res = DeliveryResult(
            success=True,
            mode="simulation",
            status="simulated",
            recipient="user@example.com",
            subject="Test Sub",
            timestamp="2026-11-24 12:00:00",
            message_id="<test-id@example.com>",
            error=None,
            metadata={"key": "val"},
        )

        d = res.to_dict()
        assert d["success"] is True
        assert d["status"] == "simulated"
        assert d["metadata"] == {"key": "val"}

        # Subscript access
        assert res["recipient"] == "user@example.com"
        assert res["status"] == "simulated"
        assert res["message_id"] == "<test-id@example.com>"
