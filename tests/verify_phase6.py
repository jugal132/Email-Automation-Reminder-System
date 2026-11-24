"""
Phase 6 verification script.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from unittest.mock import MagicMock, patch
import py_compile
from src.contact_manager import ContactManager
from src.email_sender import EmailSender
from src.reminder_manager import ReminderManager
from src.scheduler import ReminderScheduler
from src.template_processor import TemplateProcessor

print("=== 1. PYTHON SYNTAX VERIFICATION ===")
for py_file in root.glob("**/*.py"):
    if "__pycache__" not in str(py_file):
        py_compile.compile(str(py_file), doraise=True)
        print(f"[VALID SYNTAX] {py_file.relative_to(root)}")

print("\n=== 2. DUE VS FUTURE REMINDER DETECTION EVIDENCE ===")
cm = ContactManager()
cm.load_contacts()
rm = ReminderManager(contact_manager=cm)
rm.load_reminders()

eval_time = datetime(2026, 12, 1, 12, 0)
scheduler = ReminderScheduler(
    reminder_manager=rm,
    contact_manager=cm,
    template_processor=TemplateProcessor(),
    reference_time=eval_time,
)

due = scheduler.get_due_reminders(reference_time=eval_time)
print(f"Evaluation Reference Time : {eval_time.strftime('%Y-%m-%d %H:%M')}")
print(f"Due Reminders Count       : {len(due)}")
for d in due:
    print(f"  Due Reminder #{d['reminder_id']} | Schedule: {d['scheduled_at']} | Recipient: {d['contact_details']['email']}")

assert len(due) == 1, f"Expected exactly 1 due reminder at {eval_time}, got {len(due)}"
assert due[0]["reminder_id"] == "1"
print("[PASS] Due reminder detection verified.")

print("\n=== 3. SIMULATION-ONLY SAFETY UNDER LIVE CONFIGURATION ===")
with patch("smtplib.SMTP") as mock_smtp, patch("smtplib.SMTP_SSL") as mock_ssl:
    # Inject live environment settings
    live_env = {
        "EMAIL_MODE": "live",
        "ALLOW_REAL_EMAILS": "true",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "test@gmail.com",
        "SMTP_PASSWORD": "secret_password",
    }
    with patch.dict(os.environ, live_env):
        # Even with live EmailSender passed
        sender_live = EmailSender(mode="live")
        assert sender_live.mode == "live"
        safe_scheduler = ReminderScheduler(
            reminder_manager=rm,
            contact_manager=cm,
            email_sender=sender_live,
            reference_time=eval_time,
        )
        assert safe_scheduler.email_sender.mode == "simulation"
        report = safe_scheduler.run_once(reference_time=eval_time)

        # Verify zero SMTP calls occurred
        assert mock_smtp.call_count == 0, "SECURITY BREACH: smtplib.SMTP was called!"
        assert mock_ssl.call_count == 0, "SECURITY BREACH: smtplib.SMTP_SSL was called!"
        assert report.total_simulated == 1
        print(f"Simulated dispatches count : {report.total_simulated}")
        print(f"SMTP Mock Call Count       : {mock_smtp.call_count + mock_ssl.call_count}")
        print("[PASS] Verified absolute simulation-only safety: live settings did not invoke SMTP.")

print("\n=== 4. SOURCE CSV FILE IMMUTABILITY CHECK ===")
csv_path = root / "data" / "reminders.csv"
content_before = csv_path.read_text(encoding="utf-8")
scheduler.run_once(reference_time=eval_time)
content_after = csv_path.read_text(encoding="utf-8")
assert content_before == content_after, "ERROR: data/reminders.csv was modified during simulation!"
print("[PASS] Verified data/reminders.csv remained completely unchanged.")

print("\n[SUCCESS] All Phase 6 verification scenarios passed cleanly.")
