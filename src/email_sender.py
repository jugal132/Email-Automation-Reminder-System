"""
Email Sender Module.

Responsible for creating MIME-compliant email messages and executing dispatch
via Simulation Mode or a secure, safety-gated SMTP delivery interface.
"""

from __future__ import annotations

import os
import smtplib
import socket
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from src.logger_config import get_logger

logger = get_logger(__name__)

# Supported operating modes
SUPPORTED_MODES = {"simulation", "live", "smtp"}

# Load environment variables from .env file if available
load_dotenv()


class EmailSenderError(Exception):
    """Base exception for EmailSender operations."""


class MessageConstructionError(EmailSenderError, ValueError):
    """Raised when message fields are invalid or missing."""


class ConfigurationError(EmailSenderError, ValueError):
    """Raised when email sender or SMTP configuration is invalid."""


class SafetyGateError(EmailSenderError, PermissionError):
    """Raised when live transmission is blocked by safety controls."""


@dataclass
class DeliveryResult:
    """
    Structured outcome of an email dispatch operation.

    Attributes:
        success: Whether the operation completed successfully (or simulated successfully).
        mode: Operational mode employed ('simulation', 'live', or 'smtp').
        status: Delivery status ('simulated', 'sent', 'failed', 'blocked').
        recipient: Target recipient email address.
        subject: Email subject line.
        timestamp: Timestamp of the dispatch attempt (ISO format).
        message_id: Unique Message-ID identifier if generated.
        error: Descriptive error message when status is 'failed' or 'blocked'.
        metadata: Optional dictionary with operational context.
    """

    success: bool
    mode: str
    status: str
    recipient: str
    subject: str
    timestamp: str
    message_id: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "success": self.success,
            "mode": self.mode,
            "status": self.status,
            "recipient": self.recipient,
            "subject": self.subject,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
            "error": self.error,
            "metadata": self.metadata or {},
        }

    def __getitem__(self, item: str) -> Any:
        """Provide dictionary-style subscript access for backwards compatibility."""
        return self.to_dict()[item]


class EmailSender:
    """
    Manages email message preparation and transmission in simulation or SMTP mode.
    """

    def __init__(
        self,
        mode: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize EmailSender.

        Args:
            mode: Operational mode ('simulation' or 'live'). Defaults to environment
                  variable EMAIL_MODE, or 'simulation' if not specified.
            config: Optional configuration dictionary overriding environment variables.
        """
        self._raw_config = config or {}

        # Resolve mode
        raw_mode = mode or self._raw_config.get("EMAIL_MODE") or os.getenv("EMAIL_MODE", "simulation")
        self.mode = str(raw_mode).strip().lower()

        if self.mode not in SUPPORTED_MODES:
            raise ConfigurationError(
                f"Unsupported email mode '{raw_mode}'. Supported modes: {', '.join(sorted(SUPPORTED_MODES))}"
            )

        # Resolve configuration values
        self.smtp_host = str(self._get_config("SMTP_HOST", "")).strip()
        raw_port = self._get_config("SMTP_PORT", "587")
        try:
            self.smtp_port = int(str(raw_port).strip())
        except (ValueError, TypeError):
            self.smtp_port = 0

        self.smtp_username = str(self._get_config("SMTP_USERNAME", "")).strip()
        self.smtp_password = str(self._get_config("SMTP_PASSWORD", "")).strip()

        # Sender resolution (checks SMTP_SENDER first, then EMAIL_FROM)
        sender_val = self._get_config("SMTP_SENDER")
        if sender_val is None or str(sender_val).strip() == "":
            sender_val = self._get_config("EMAIL_FROM")

        self.smtp_sender = str(sender_val).strip() if sender_val is not None else ""

        raw_timeout = self._get_config("SMTP_TIMEOUT", "10.0")
        try:
            self.smtp_timeout = float(raw_timeout)
        except (ValueError, TypeError):
            self.smtp_timeout = 10.0

        # Safety control variable
        self.allow_real_emails = str(
            self._get_config("ALLOW_REAL_EMAILS", os.getenv("ALLOW_REAL_EMAILS", "false"))
        ).strip().lower()

        logger.info(
            "EmailSender initialized in '%s' mode (Safety gate ALLOW_REAL_EMAILS: %s).",
            self.mode,
            self.allow_real_emails,
        )

    def _get_config(self, key: str, default: Optional[str] = None) -> Any:
        """Retrieve value from configuration dictionary or environment variables."""
        if key in self._raw_config:
            val = self._raw_config[key]
            if val is not None:
                return val
        return os.getenv(key, default)

    def is_safety_gate_open(self) -> bool:
        """
        Evaluate whether safety requirements allow live email transmission.

        Requires BOTH:
            1. Explicit live/smtp operational mode ('live' or 'smtp').
            2. Explicit opt-in configuration variable ALLOW_REAL_EMAILS='true'.

        Returns:
            bool: True if live sending is explicitly authorized; False otherwise.
        """
        is_live_mode = self.mode in ("live", "smtp")
        is_opted_in = self.allow_real_emails in ("true", "1", "yes")
        return is_live_mode and is_opted_in

    def validate_smtp_config(self) -> Tuple[bool, List[str]]:
        """
        Validate completeness and correctness of SMTP configuration settings.

        Returns:
            Tuple[bool, List[str]]: (is_valid, list of error messages)
        """
        errors: List[str] = []

        if not self.smtp_host:
            errors.append("Missing required SMTP_HOST")
        if self.smtp_port <= 0 or self.smtp_port > 65535:
            errors.append(f"Invalid SMTP_PORT: '{self.smtp_port}'. Must be between 1 and 65535")
        if not self.smtp_username:
            errors.append("Missing required SMTP_USERNAME")
        if not self.smtp_password:
            errors.append("Missing required SMTP_PASSWORD")
        if not self.smtp_sender:
            errors.append("Missing required SMTP_SENDER / EMAIL_FROM")

        return len(errors) == 0, errors

    def create_message(
        self,
        recipient: str,
        subject: str,
        body: str,
        sender: Optional[str] = None,
    ) -> EmailMessage:
        """
        Construct a structurally valid EmailMessage.

        Args:
            recipient: Target recipient email address.
            subject: Email subject line.
            body: Plain-text email body.
            sender: Optional sender address override. Defaults to configured sender.

        Returns:
            EmailMessage: Populated standard MIME email message.

        Raises:
            MessageConstructionError: If recipient or subject is empty or invalid.
        """
        if not recipient or not str(recipient).strip():
            raise MessageConstructionError("Recipient email address must be non-empty.")
        if not subject or not str(subject).strip():
            raise MessageConstructionError("Email subject line must be non-empty.")
        if body is None:
            raise MessageConstructionError("Email body cannot be None.")

        clean_recipient = str(recipient).strip()
        clean_subject = str(subject).strip()
        fallback_sender = self.smtp_sender if self.smtp_sender else "noreply@example.com"
        clean_sender = str(sender or fallback_sender).strip()

        msg = EmailMessage()
        msg["From"] = clean_sender
        msg["To"] = clean_recipient
        msg["Subject"] = clean_subject

        # Generate a unique Message-ID
        domain = clean_sender.split("@")[-1] if "@" in clean_sender else "localhost"
        msg["Message-ID"] = f"<{uuid.uuid4()}@{domain}>"

        # Assign plain text body content
        msg.set_content(body)
        return msg

    def send_email(
        self,
        recipient: str,
        subject: str,
        body: str,
        metadata: Optional[Dict[str, Any]] = None,
        sender: Optional[str] = None,
    ) -> DeliveryResult:
        """
        Prepare and dispatch an email via simulation or SMTP depending on configured mode.

        Args:
            recipient: Recipient email address.
            subject: Email subject line.
            body: Plain-text email body content.
            metadata: Optional dictionary with operational metadata.
            sender: Optional sender override.

        Returns:
            DeliveryResult: Structured delivery record.
        """
        try:
            msg = self.create_message(recipient=recipient, subject=subject, body=body, sender=sender)
        except MessageConstructionError as exc:
            logger.error("Message construction failed for %s: %s", recipient, exc)
            return DeliveryResult(
                success=False,
                mode=self.mode,
                status="failed",
                recipient=str(recipient),
                subject=str(subject),
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                error=f"Message construction error: {exc}",
                metadata=metadata,
            )

        if self.mode == "simulation":
            return self.send_simulated(msg, metadata=metadata)
        elif self.mode in ("live", "smtp"):
            return self.send_via_smtp(msg, metadata=metadata)
        else:
            return DeliveryResult(
                success=False,
                mode=self.mode,
                status="failed",
                recipient=str(msg["To"]),
                subject=str(msg["Subject"]),
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                message_id=str(msg.get("Message-ID")),
                error=f"Unsupported email mode '{self.mode}'",
                metadata=metadata,
            )

    def send_simulated(
        self,
        message: EmailMessage,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DeliveryResult:
        """
        Execute simulated delivery.

        No network connections are attempted, no credentials are required, and no emails are sent.

        Args:
            message: Formatted EmailMessage.
            metadata: Optional operational metadata.

        Returns:
            DeliveryResult: Structured outcome with status 'simulated'.
        """
        recipient = str(message["To"])
        subject = str(message["Subject"])
        message_id = str(message.get("Message-ID"))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        logger.info("[SIMULATED] Email prepared for %s [Subject: %s]", recipient, subject)

        return DeliveryResult(
            success=True,
            mode="simulation",
            status="simulated",
            recipient=recipient,
            subject=subject,
            timestamp=timestamp,
            message_id=message_id,
            error=None,
            metadata=metadata,
        )

    def send_via_smtp(
        self,
        message: EmailMessage,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DeliveryResult:
        """
        Execute SMTP delivery under strict safety controls.

        Safety Gate Check:
            If ALLOW_REAL_EMAILS is not 'true' or mode is not 'live'/'smtp',
            dispatch is immediately blocked without attempting network connection.

        Args:
            message: Formatted EmailMessage.
            metadata: Optional operational metadata.

        Returns:
            DeliveryResult: Outcome with status 'sent', 'failed', or 'blocked'.
        """
        recipient = str(message["To"])
        subject = str(message["Subject"])
        message_id = str(message.get("Message-ID"))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Safety Lock Evaluation
        if not self.is_safety_gate_open():
            reason = (
                "Live email dispatch blocked by safety lock: "
                "ALLOW_REAL_EMAILS is not set to 'true' or mode is not 'live'."
            )
            logger.warning("[SAFETY BLOCK] %s. Recipient: %s", reason, recipient)
            return DeliveryResult(
                success=False,
                mode=self.mode,
                status="blocked",
                recipient=recipient,
                subject=subject,
                timestamp=timestamp,
                message_id=message_id,
                error=reason,
                metadata=metadata,
            )

        # 2. Configuration Validation
        is_valid, config_errors = self.validate_smtp_config()
        if not is_valid:
            error_msg = f"Invalid SMTP configuration: {'; '.join(config_errors)}"
            logger.error("[CONFIG ERROR] %s", error_msg)
            return DeliveryResult(
                success=False,
                mode=self.mode,
                status="failed",
                recipient=recipient,
                subject=subject,
                timestamp=timestamp,
                message_id=message_id,
                error=error_msg,
                metadata=metadata,
            )

        # 3. Connection and Dispatch
        server = None
        try:
            ssl_context = ssl.create_default_context()

            if self.smtp_port == 465:
                # SSL direct connection
                server = smtplib.SMTP_SSL(
                    host=self.smtp_host,
                    port=self.smtp_port,
                    timeout=self.smtp_timeout,
                    context=ssl_context,
                )
            else:
                # STARTTLS connection (typically port 587)
                server = smtplib.SMTP(
                    host=self.smtp_host,
                    port=self.smtp_port,
                    timeout=self.smtp_timeout,
                )
                server.starttls(context=ssl_context)

            server.login(self.smtp_username, self.smtp_password)
            server.send_message(message)

            logger.info(
                "Email accepted by SMTP server for transmission to %s [Subject: %s]",
                recipient,
                subject,
            )
            return DeliveryResult(
                success=True,
                mode=self.mode,
                status="sent",
                recipient=recipient,
                subject=subject,
                timestamp=timestamp,
                message_id=message_id,
                error=None,
                metadata=metadata,
            )

        except smtplib.SMTPAuthenticationError:
            err = f"SMTP Authentication failed for user '{self.smtp_username}'"
            logger.error("%s", err)
            return DeliveryResult(
                success=False,
                mode=self.mode,
                status="failed",
                recipient=recipient,
                subject=subject,
                timestamp=timestamp,
                message_id=message_id,
                error=err,
                metadata=metadata,
            )
        except (TimeoutError, socket.timeout):
            err = f"SMTP connection timed out after {self.smtp_timeout} seconds"
            logger.error("%s", err)
            return DeliveryResult(
                success=False,
                mode=self.mode,
                status="failed",
                recipient=recipient,
                subject=subject,
                timestamp=timestamp,
                message_id=message_id,
                error=err,
                metadata=metadata,
            )
        except smtplib.SMTPConnectError as exc:
            err = f"Failed to connect to SMTP server '{self.smtp_host}:{self.smtp_port}': {exc.__class__.__name__}"
            logger.error("%s", err)
            return DeliveryResult(
                success=False,
                mode=self.mode,
                status="failed",
                recipient=recipient,
                subject=subject,
                timestamp=timestamp,
                message_id=message_id,
                error=err,
                metadata=metadata,
            )
        except smtplib.SMTPException as exc:
            err = f"SMTP protocol error: {exc.__class__.__name__} ({str(exc).strip()})"
            logger.error("%s", err)
            return DeliveryResult(
                success=False,
                mode=self.mode,
                status="failed",
                recipient=recipient,
                subject=subject,
                timestamp=timestamp,
                message_id=message_id,
                error=err,
                metadata=metadata,
            )
        except (ConnectionError, OSError) as exc:
            err = f"Failed to connect to SMTP server '{self.smtp_host}:{self.smtp_port}': {exc.__class__.__name__}"
            logger.error("%s", err)
            return DeliveryResult(
                success=False,
                mode=self.mode,
                status="failed",
                recipient=recipient,
                subject=subject,
                timestamp=timestamp,
                message_id=message_id,
                error=err,
                metadata=metadata,
            )
        except Exception as exc:
            err = f"Unexpected error during email transmission: {exc.__class__.__name__}"
            logger.error("%s", err)
            return DeliveryResult(
                success=False,
                mode=self.mode,
                status="failed",
                recipient=recipient,
                subject=subject,
                timestamp=timestamp,
                message_id=message_id,
                error=err,
                metadata=metadata,
            )
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    try:
                        server.close()
                    except Exception:
                        pass
