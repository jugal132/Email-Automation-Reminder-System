"""
Phase 5 verification script.
"""

import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from unittest.mock import MagicMock, patch
import py_compile
from src.email_sender import EmailSender

print("=== 1. PYTHON SYNTAX VERIFICATION ===")
for py_file in root.glob("**/*.py"):
    if "__pycache__" not in str(py_file):
        py_compile.compile(str(py_file), doraise=True)
        print(f"[VALID SYNTAX] {py_file.relative_to(root)}")

print("\n=== 2. SIMULATION MODE VERIFICATION ===")
sim_sender = EmailSender(mode="simulation")
with patch("smtplib.SMTP") as mock_smtp, patch("smtplib.SMTP_SSL") as mock_ssl:
    res_sim = sim_sender.send_email(
        recipient="simulated.user@example.com",
        subject="Simulation Verification",
        body="This is a safe test email body.",
    )
    assert mock_smtp.call_count == 0, "Error: SMTP was called in simulation mode!"
    assert mock_ssl.call_count == 0, "Error: SMTP_SSL was called in simulation mode!"
    print(f"Simulation Status : {res_sim.status}")
    print(f"Simulation Success: {res_sim.success}")
    print(f"Simulation Recip  : {res_sim.recipient}")
    print(f"Simulation Msg ID : {res_sim.message_id}")
    print("[PASS] Verified simulation mode performs zero network connections.")

print("\n=== 3. SAFETY GATE LOCK VERIFICATION ===")
# Case A: Live mode requested, but ALLOW_REAL_EMAILS is default/false
live_sender_blocked = EmailSender(
    mode="live",
    config={
        "ALLOW_REAL_EMAILS": "false",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": 587,
        "SMTP_USERNAME": "test_user",
        "SMTP_PASSWORD": "test_password",
    },
)
res_blocked = live_sender_blocked.send_email(
    recipient="victim@example.com",
    subject="Attempted Live Send",
    body="Should be blocked",
)
assert res_blocked.status == "blocked", f"Expected blocked, got {res_blocked.status}"
assert res_blocked.success is False
print(f"Blocked Status : {res_blocked.status}")
print(f"Blocked Reason : {res_blocked.error}")
print("[PASS] Verified safety lock halts live sending when ALLOW_REAL_EMAILS is false.")

print("\n=== 4. MOCKED SMTP VERIFICATION ===")
live_sender_optin = EmailSender(
    mode="live",
    config={
        "ALLOW_REAL_EMAILS": "true",
        "SMTP_HOST": "smtp.testserver.com",
        "SMTP_PORT": 587,
        "SMTP_USERNAME": "mock_login@testserver.com",
        "SMTP_PASSWORD": "mock_password_secret",
        "SMTP_SENDER": "noreply@testserver.com",
    },
)
with patch("smtplib.SMTP") as mock_smtp:
    mock_server = MagicMock()
    mock_smtp.return_value = mock_server

    res_mocked = live_sender_optin.send_email(
        recipient="client@example.com",
        subject="Mocked Delivery Check",
        body="Mocked Body",
    )

    assert mock_smtp.call_count == 1
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("mock_login@testserver.com", "mock_password_secret")
    mock_server.send_message.assert_called_once()
    mock_server.quit.assert_called_once()
    print(f"Mocked SMTP Status : {res_mocked.status}")
    print(f"Mocked SMTP Success: {res_mocked.success}")
    print("[PASS] Verified isolated mock SMTP lifecycle (STARTTLS, login, send_message, quit).")

print("\n=== 5. CREDENTIAL LEAKAGE PREVENTION ===")
with patch("smtplib.SMTP") as mock_smtp:
    mock_server = MagicMock()
    mock_smtp.return_value = mock_server
    secret_pwd = "super_secret_credentials_never_leak"
    import smtplib
    mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")

    leak_sender = EmailSender(
        mode="live",
        config={
            "ALLOW_REAL_EMAILS": "true",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": 587,
            "SMTP_USERNAME": "user",
            "SMTP_PASSWORD": secret_pwd,
            "SMTP_SENDER": "user@example.com",
        },
    )
    res_leak_check = leak_sender.send_email("test@example.com", "Sub", "Body")
    assert secret_pwd not in str(res_leak_check.error), "SECURITY ALERT: Password leaked in error!"
    assert res_leak_check.status == "failed"
    print(f"Error Diagnostic : {res_leak_check.error}")
    print("[PASS] Verified zero credentials leaked during authentication failure.")

print("\n[SUCCESS] All Phase 5 verification scenarios passed cleanly.")
