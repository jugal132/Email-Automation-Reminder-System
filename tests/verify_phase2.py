"""
Phase 2 manual verification script.
"""

import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import py_compile
from src.contact_manager import ContactManager

print("=== 1. PYTHON SYNTAX VERIFICATION ===")
for py_file in root.glob("**/*.py"):
    if "__pycache__" not in str(py_file):
        py_compile.compile(str(py_file), doraise=True)
        print(f"[VALID SYNTAX] {py_file.relative_to(root)}")

print("\n=== 2. VERIFICATION WITH DELIBERATELY INVALID TEST RECORDS ===")
invalid_csv_data = """contact_id,name,email,company,status
,Missing ID,valid1@example.com,Co,active
102,,valid2@example.com,Co,active
103,Missing Email,,Co,active
104,Bad Email,not-an-email,Co,active
105,Missing Status,valid3@example.com,Co,
"""
test_file = root / "tests" / "_temp_invalid_test.csv"
test_file.write_text(invalid_csv_data, encoding="utf-8")
try:
    mgr = ContactManager(data_source=test_file)
    mgr.load_contacts()
    invalid_list = mgr.get_invalid_contacts()
    print(f"Total invalid records detected: {len(invalid_list)}")
    for rec in invalid_list:
        print(f"  Row {rec['row_index']}: ID='{rec['contact_id']}', Name='{rec['name']}' -> Errors: {rec['validation_errors']}")
finally:
    if test_file.exists():
        test_file.unlink()

print("\n=== 3. VERIFICATION OF CASE-INSENSITIVE DUPLICATE DETECTION ===")
dup_csv_data = """contact_id,name,email,company,status
1,First User,TestUser@Example.COM,Alpha,active
2,Second User (Dup Upper),testuser@example.com,Beta,active
3,Third User (Dup Spaced),  TESTUSER@EXAMPLE.COM  ,Gamma,active
4,Distinct User,another@example.com,Delta,active
"""
dup_test_file = root / "tests" / "_temp_dup_test.csv"
dup_test_file.write_text(dup_csv_data, encoding="utf-8")
try:
    dup_mgr = ContactManager(data_source=dup_test_file)
    dup_mgr.load_contacts()
    print(f"Valid contacts: {[c['email'] for c in dup_mgr.get_valid_contacts()]}")
    print(f"Duplicates detected: {len(dup_mgr.get_duplicate_contacts())}")
    for d in dup_mgr.get_duplicate_contacts():
        print(f"  Duplicate ID: {d['contact_id']} ({d['name']}) -> Reason: {d['validation_errors']}")
finally:
    if dup_test_file.exists():
        dup_test_file.unlink()

print("\n=== 4. VERIFICATION THAT INACTIVE CONTACTS ARE EXCLUDED FROM ACTIVE ===")
status_csv_data = """contact_id,name,email,company,status
1,Active Person,person1@example.com,Co,active
2,Active Person Upper,person2@example.com,Co,  ACTIVE  
3,Inactive Person,person3@example.com,Co,inactive
4,Draft Person,person4@example.com,Co,draft
5,Suspended Person,person5@example.com,Co,suspended
"""
status_test_file = root / "tests" / "_temp_status_test.csv"
status_test_file.write_text(status_csv_data, encoding="utf-8")
try:
    status_mgr = ContactManager(data_source=status_test_file)
    status_mgr.load_contacts()
    active_contacts = status_mgr.get_active_contacts()
    print(f"Active contacts count: {len(active_contacts)}")
    for ac in active_contacts:
        print(f"  Active Contact: ID={ac['contact_id']}, Name={ac['name']}, Status={ac['status']}")
finally:
    if status_test_file.exists():
        status_test_file.unlink()

print("\n[SUCCESS] All verification scenarios executed successfully.")
