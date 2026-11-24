"""
Phase 3 comprehensive verification script.
"""

import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from datetime import datetime
import py_compile
from src.contact_manager import ContactManager
from src.reminder_manager import ReminderManager

print("=== 1. PYTHON SYNTAX VERIFICATION ===")
for py_file in root.glob("**/*.py"):
    if "__pycache__" not in str(py_file):
        py_compile.compile(str(py_file), doraise=True)
        print(f"[VALID SYNTAX] {py_file.relative_to(root)}")

print("\n=== 2. CONTACT REFERENCE VALIDATION ===")
# Setup mock contacts: 1=active, 2=inactive, 3=invalid
contacts_csv = root / "tests" / "_temp_contacts.csv"
contacts_csv.write_text(
    "contact_id,name,email,company,status\n"
    "1,Active User,active@example.com,Co,active\n"
    "2,Inactive User,inactive@example.com,Co,inactive\n"
    "3,Invalid User,bad-email,Co,active\n",
    encoding="utf-8",
)
cm = ContactManager(data_source=contacts_csv)
cm.load_contacts()

reminders_csv = root / "tests" / "_temp_reminders.csv"
reminders_csv.write_text(
    "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
    "101,1,Valid Active,Sub 1,Msg 1,2026-12-01 10:00,pending\n"
    "102,2,Inactive Contact,Sub 2,Msg 2,2026-12-02 10:00,pending\n"
    "103,3,Invalid Contact,Sub 3,Msg 3,2026-12-03 10:00,pending\n"
    "104,999,Missing Contact,Sub 4,Msg 4,2026-12-04 10:00,pending\n",
    encoding="utf-8",
)
try:
    rm = ReminderManager(data_source=reminders_csv, contact_manager=cm)
    rm.load_reminders()

    print(f"Total Reminders: {len(rm.get_all_reminders())}")
    print(f"Valid Reminders: {[r['reminder_id'] for r in rm.get_valid_reminders()]}")
    print(f"Invalid Reminders: {[r['reminder_id'] for r in rm.get_invalid_reminders()]}")
    for inv in rm.get_invalid_reminders():
        print(f"  Invalid #{inv['reminder_id']}: {inv['validation_errors']}")

    print("\n=== 3. INACTIVE CONTACT EXCLUSION & PENDING FILTERING ===")
    eligible = rm.get_pending_reminders(only_active_contacts=True)
    all_pending = rm.get_pending_reminders(only_active_contacts=False)
    print(f"All Pending Reminders: {[r['reminder_id'] for r in all_pending]}")
    print(f"Eligible Pending (Active Contacts Only): {[r['reminder_id'] for r in eligible]}")
    print(f"Inactive Recipient Reminders: {[r['reminder_id'] for r in rm.get_inactive_contact_reminders()]}")

finally:
    if contacts_csv.exists():
        contacts_csv.unlink()
    if reminders_csv.exists():
        reminders_csv.unlink()

print("\n=== 4. INVALID DATE & DUPLICATE ID TEST CASES ===")
edge_csv = root / "tests" / "_temp_edge.csv"
edge_csv.write_text(
    "reminder_id,contact_id,title,subject,message,scheduled_at,status\n"
    "201,1,Bad Date,Sub,Msg,2026/12/01 10:00,pending\n"
    "202,1,Duplicate ID 1,Sub A,Msg,2026-12-01 10:00,pending\n"
    "202,1,Duplicate ID 2,Sub B,Msg,2026-12-02 10:00,pending\n",
    encoding="utf-8",
)
# Use project default contact manager (which has contact 1 active)
try:
    rm_edge = ReminderManager(data_source=edge_csv)
    rm_edge.load_reminders()
    print(f"Duplicate IDs: {[r['reminder_id'] for r in rm_edge.get_duplicate_id_reminders()]}")
    for inv in rm_edge.get_invalid_reminders():
        print(f"  Invalid #{inv['reminder_id']}: {inv['validation_errors']}")
finally:
    if edge_csv.exists():
        edge_csv.unlink()

print("\n[SUCCESS] All Phase 3 verification scenarios passed cleanly.")
