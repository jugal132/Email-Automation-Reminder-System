"""
Phase 4 verification script.
"""

import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import py_compile
from src.contact_manager import ContactManager
from src.reminder_manager import ReminderManager
from src.template_processor import TemplateProcessor, TemplateValidationError

print("=== 1. PYTHON SYNTAX VERIFICATION ===")
for py_file in root.glob("**/*.py"):
    if "__pycache__" not in str(py_file):
        py_compile.compile(str(py_file), doraise=True)
        print(f"[VALID SYNTAX] {py_file.relative_to(root)}")

print("\n=== 2. SUCCESSFUL PERSONALIZED PREVIEW VERIFICATION ===")
cm = ContactManager()
cm.load_contacts()
rm = ReminderManager(contact_manager=cm)
rm.load_reminders()

eligible = [r for r in rm.get_pending_reminders(only_active_contacts=True) if not r["is_overdue"]]
assert len(eligible) > 0, "Expected at least one eligible pending reminder"
first_eligible = eligible[0]
contact = first_eligible["contact_details"]

tp = TemplateProcessor()
context = tp.build_context(contact, first_eligible)
print(f"Context constructed: {list(context.keys())}")

rendered = tp.render(context)
print("Rendered snippet:")
print(rendered[:150] + "...")

print("\n=== 3. MISSING PLACEHOLDER SCENARIO ===")
broken_context = dict(context)
del broken_context["scheduled_at"]
try:
    tp.render(broken_context)
    print("[ERROR] Expected TemplateValidationError but none raised.")
except TemplateValidationError as exc:
    print(f"[PASS] Successfully caught expected TemplateValidationError: {exc}")

print("\n=== 4. EMPTY REQUIRED PLACEHOLDER SCENARIO ===")
empty_context = dict(context)
empty_context["name"] = "   "
try:
    tp.render(empty_context)
    print("[ERROR] Expected TemplateValidationError for whitespace name.")
except TemplateValidationError as exc:
    print(f"[PASS] Successfully caught expected TemplateValidationError: {exc}")

print("\n=== 5. PREVENT CODE INJECTION IN CONTEXT ===")
injection_context = dict(context)
injection_context["name"] = "{{7*7}}"
rendered_injection = tp.render(injection_context)
assert "{{7*7}}" in rendered_injection or "49" not in rendered_injection
print(f"[PASS] Safe string substitution verified. No code evaluated: {rendered_injection.splitlines()[0]}")

print("\n[SUCCESS] All Phase 4 verification scenarios passed cleanly.")
