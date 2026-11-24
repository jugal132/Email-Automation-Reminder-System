# Project Architecture & Technical Documentation

## 1. System Overview

The **Email Automation & Reminder System** provides an automated, reliable pipeline for scheduling, formatting, and dispatching personalized emails. It is structured to maintain strict separation of concerns, enabling testing in simulation mode without risking unintended real-world email dispatch.

```
                    ┌─────────────────────────┐
                    │      Configuration      │
                    │   (.env / .env.example) │
                    └────────────┬────────────┘
                                 │
                                 ▼
┌─────────────────┐      ┌───────────────┐
│   Data Source   │ ───► │ ContactManager│ ──────┐
│ (contacts.csv)  │      └───────┬───────┘      │
└─────────────────┘              │              │
                                 ▼              ▼
┌─────────────────┐      ┌───────────────┐   ┌─────────────────────┐
│ Reminders Queue │ ───► │ReminderManager│ ─►│  TemplateProcessor  │
│ (reminders.csv) │      └───────┬───────┘   │ (templates/txt/html)│
└─────────────────┘              │           └──────────┬──────────┘
                                 ▼                      │
                         ┌───────────────┐              │
                         │   Scheduler   │ ◄────────────┘
                         └───────┬───────┘
                                 │
                                 ▼
                         ┌───────────────┐      ┌─────────────────┐
                         │  EmailSender  │ ◄─── │ DatabaseManager │
                         │(Simulation/SMTP)     │    (SQLite)     │
                         └───────┬───────┘      └─────────────────┘
                                 │
                                 ▼
                         ┌───────────────┐
                         │ReportGenerator│
                         │  (outputs/)   │
                         └───────────────┘
```

---

## 2. Module Responsibilities (`src/`)

### 2.1 `logger_config.py`
- **Purpose**: Centralized logging setup for all modules.
- **Responsibilities**:
  - Configures timestamped, leveled log formats (`[timestamp] [level] [module]: message`).
  - Supports console output stream and optional file-based log handlers in `logs/`.
  - Ensures uniform logging style across all packages.

### 2.2 `contact_manager.py`
- **Purpose**: Ingestion, validation, and querying of contact data.
- **Responsibilities**:
  - Read contacts from `data/contacts.csv` using `pathlib.Path`.
  - Validate required fields (`contact_id`, `name`, `email`, `status`).
  - Validate email formats via standard RFC 5322 regex.
  - Perform case-insensitive email deduplication, preserving the primary record.
  - Filter contacts by status (`active`, `inactive`).

### 2.3 `reminder_manager.py`
- **Purpose**: Ingestion, validation, contact reference checking, and scheduling qualification.
- **Responsibilities**:
  - Load reminders from `data/reminders.csv` using `pathlib.Path`.
  - Validate required fields (`reminder_id`, `contact_id`, `title`, `subject`, `message`, `scheduled_at`, `status`).
  - Verify `reminder_id` uniqueness (duplicate IDs are rejected with reasons).
  - Cross-reference `contact_id` against `ContactManager`:
    - Flags missing contact references (`has_missing_contact`).
    - Flags invalid contact references (`has_invalid_contact`).
    - Flags inactive contact recipients (`has_inactive_contact`) and excludes them from automated dispatch.
  - Parse date/time strings (`YYYY-MM-DD HH:MM`) and identify overdue jobs without marking valid past records as malformed.
  - Detect potential duplicate content based on `(contact_id, subject, scheduled_at)` tuples.

### 2.4 `template_processor.py`
- **Purpose**: Template file ingestion, placeholder detection, context validation, and personalized rendering.
- **Responsibilities**:
  - Read template files from disk using `pathlib.Path` (`templates/email_template.txt`).
  - Detect dynamic placeholder tags matching syntax `{{placeholder_name}}`.
  - Deduplicate repeated placeholders while preserving appearance order.
  - Validate context mappings: verifies every placeholder has an associated non-null, non-empty value.
  - Safe substitution: replaces placeholders purely as strings without executing code (`eval` is prohibited).
  - Guard against unresolved placeholders in rendered content.
  - Expose helper `build_context(contact, reminder)` to construct standardized rendering contexts.

### 2.5 `email_sender.py`
- **Purpose**: Email preparation, simulation dispatch, and secure SMTP transport.
- **Responsibilities**:
  - Construct MIME-compliant plain-text messages using Python's standard `email.message.EmailMessage`.
  - Simulation Mode (default): generates delivery metadata, message ID, and logs actions without network communication.
  - Live SMTP Mode: supports STARTTLS (port 587) and direct SSL (port 465) using `smtplib` and `ssl`.
  - Safety Lock enforcement: blocks live dispatch unless `ALLOW_REAL_EMAILS=true` is explicitly provided.
  - Zero Credential Leakage: sanitizes all exceptions and logs, ensuring passwords and auth tokens are never recorded.
  - Produces consistent `DeliveryResult` records with statuses: `simulated`, `sent`, `failed`, `blocked`.

### 2.6 `scheduler.py`
- **Purpose**: Time-based evaluation, due reminder identification, and automation orchestration.
- **Responsibilities**:
  - Identifies due eligible reminders based on reference time comparison (`scheduled_at <= reference_time`).
  - Enforces recipient qualification: requires valid, active contacts.
  - Orchestrates the full pipeline: Reminder $\rightarrow$ Contact $\rightarrow$ TemplateProcessor $\rightarrow$ EmailSender.
  - Strictly enforces Simulation-Only mode: live SMTP is unconditionally prohibited during automated scheduling.
  - In-memory duplicate protection: prevents identical reminders from being dispatched multiple times per execution run.
  - Fault isolation: isolates reminder-level processing failures so remaining eligible reminders continue uninterrupted.
  - Generates structured `SchedulerExecutionReport` capturing aggregate metrics and individual reminder outcomes.

### 2.7 `report_generator.py`
- **Purpose**: Analytics, campaign metrics compilation, and CSV reporting.
- **Responsibilities**:
  - Calculate aggregate delivery and operational metrics (total runs, reminders evaluated, due count, processed count, simulated count, failed count, skipped count, success rate).
  - Enforce strict simulation safety invariant: reports `actual_sent: 0` to prevent misrepresenting simulation activity.
  - Generate single execution outcome reports with individual reminder details.
  - Export structured, Excel-compatible UTF-8 CSV campaign reports (`outputs/campaign_reports/campaign_report_YYYYMMDD_HHMMSS.csv`).
  - Export granular reminder execution CSVs (`detailed_execution_<execution_id>.csv`).

### 2.8 `database.py`
- **Purpose**: Persistence layer for audit trails, execution history, and individual reminder outcomes.
- **Responsibilities**:
  - Manage connection pooling, lifecycle, and `:memory:` mode for local SQLite database (`data/email_automation.db`).
  - Idempotent schema initialization for `execution_history` and `reminder_executions` tables.
  - Relational integrity: enforces foreign keys (`PRAGMA foreign_keys = ON;`) with cascading deletes.
  - Atomic transactions: commits on success and rolls back completely on any failure during batch insertion.
  - Parameterized queries preventing SQL injection vulnerabilities.

---

## 3. Reminder Data Validation Rules & Architecture

### 3.1 Schema & Types
| Field | Type | Required | Constraints |
| :--- | :--- | :--- | :--- |
| `reminder_id` | String | Yes | Unique identifier; duplicate IDs flagged as invalid |
| `contact_id` | String | Yes | Must reference a valid contact in `ContactManager` |
| `title` | String | Yes | Non-empty short title |
| `subject` | String | Yes | Non-empty email subject line |
| `message` | String | Yes | Non-empty body template/text |
| `scheduled_at`| String | Yes | Format: `YYYY-MM-DD HH:MM` (naive local datetime) |
| `status` | String | Yes | One of: `pending`, `sent`, `failed`, `cancelled` |

### 3.2 Contact Reference Integrity
1. **Missing Contact**: If `contact_id` is not found in the contact directory, the reminder is marked invalid (`has_missing_contact = True`).
2. **Invalid Contact**: If `contact_id` exists but failed contact validation, the reminder is marked invalid (`has_invalid_contact = True`).
3. **Inactive Contact**: If `contact_id` exists and is valid, but has status `inactive`, the reminder record itself is structurally valid, but flagged with `has_inactive_contact = True` and excluded from `get_pending_reminders(only_active_contacts=True)`.

---

## 4. Scheduling & Automation Engine Architecture (`src/scheduler.py`)

### 4.1 Due Reminder Qualification
A reminder qualifies as due for processing when:
- It is valid (`is_valid == True`).
- Its status is `"pending"`.
- `scheduled_at <= reference_time`.
- The referenced contact is valid and active (`status == 'active'`).
- It has not already been processed in the active execution batch.

### 4.2 Mandatory Simulation-Only Safety
The scheduler contains an absolute safety boundary:
- Automated scheduling strictly forces simulation mode (`self.email_sender.mode = 'simulation'`) and directly dispatches via `send_simulated()`.
- Even if `EMAIL_MODE=live` and `ALLOW_REAL_EMAILS=true` are set in the environment, the scheduler will not execute real SMTP calls.

### 4.3 In-Memory Duplicate Protection
Within a single `run_once()` invocation, the scheduler maintains an in-memory set of processed `reminder_id`s. Any repeated reminder record encountered in the same batch is recorded as `skipped` to prevent duplicate dispatches.
*Limitation*: Because database persistence is not yet implemented, this duplicate protection is execution-local and does not persist across application restarts.

### 4.4 Execution Report Schema
`SchedulerExecutionReport`:
- `execution_id` (str)
- `execution_timestamp` (str)
- `reference_time` (str)
- `total_reminders_examined` (int)
- `total_due` (int)
- `total_processed` (int)
- `total_simulated` (int)
- `total_failed` (int)
- `total_skipped` (int)
- `results`: List of `SchedulerReminderResult` records (`reminder_id`, `recipient`, `subject`, `processing_status`, `delivery_status`, `error`, `timestamp`).

---

## 5. Database Persistence & Campaign Reporting Architecture (Phase 7)

### 5.1 SQLite Schema Design

#### Table: `execution_history`
Tracks aggregate execution runs executed by the scheduler:
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `execution_id` | TEXT | PRIMARY KEY | Unique execution run identifier (e.g., `exec-30983c16`) |
| `execution_timestamp` | TEXT | NOT NULL | Real-world execution timestamp (`YYYY-MM-DD HH:MM:SS`) |
| `reference_time` | TEXT | NOT NULL | Reference evaluation timestamp used for schedule comparison |
| `total_reminders_examined` | INTEGER | NOT NULL | Total reminders inspected from dataset |
| `total_due` | INTEGER | NOT NULL | Total eligible reminders identified as due |
| `total_processed` | INTEGER | NOT NULL | Total due reminders processed |
| `total_simulated` | INTEGER | NOT NULL | Total reminders simulated |
| `total_failed` | INTEGER | NOT NULL | Total failures encountered |
| `total_skipped` | INTEGER | NOT NULL | Total skipped reminders (ineligible, inactive, future) |
| `notes` | TEXT | NULL | Optional execution notes |

#### Table: `reminder_executions`
Tracks granular dispatch outcomes for each reminder examined per run:
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique record ID |
| `execution_id` | TEXT | NOT NULL, FK | References `execution_history(execution_id)` ON DELETE CASCADE |
| `reminder_id` | TEXT | NOT NULL | Identifier of the evaluated reminder |
| `contact_id` | TEXT | NOT NULL | Identifier of the recipient contact |
| `recipient` | TEXT | NOT NULL | Email address of the recipient |
| `subject` | TEXT | NOT NULL | Rendered subject line |
| `scheduled_at` | TEXT | NOT NULL | Scheduled timestamp from reminder record |
| `processing_status` | TEXT | NOT NULL | Outcome: `simulated`, `failed`, `skipped`, `not_due` |
| `delivery_status` | TEXT | NULL | Delivery outcome: `simulated`, `failed`, or `None` |
| `error` | TEXT | NULL | Error diagnostics if processing failed or was skipped |
| `timestamp` | TEXT | NOT NULL | Outcome timestamp (`YYYY-MM-DD HH:MM:SS`) |
| `message_id` | TEXT | NULL | Simulated message ID (e.g. `sim-msg-...`) |

#### Indexes
- `idx_reminder_executions_execution_id` on `reminder_executions(execution_id)`
- `idx_reminder_executions_reminder_id` on `reminder_executions(reminder_id)`
- `idx_reminder_executions_contact_id` on `reminder_executions(contact_id)`

### 5.2 Transaction Atomicity & Rollback
All inserts for an execution run (`execution_history` record and all associated `reminder_executions` records) are executed within a single SQLite transaction context (`with conn:`). If any child record insertion fails or an unexpected exception occurs, the transaction is rolled back completely. No partial execution data is committed.

### 5.3 Fault Isolation in Scheduler
The scheduler decouples in-memory pipeline execution from persistence:
- If `database_manager` persistence fails (e.g., disk full, database lock), `ReminderScheduler.run_once()` logs a diagnostic error but does not raise an exception or crash.
- The in-memory `SchedulerExecutionReport` is returned to the caller intact, preserving application resilience.

### 5.4 Campaign Reporting & Export Architecture
The `ReportGenerator` provides:
1. **Campaign Summary**: Aggregates totals across all persisted runs in `execution_history`. Enforces `actual_sent: 0` to reflect strict simulation safety.
2. **CSV Campaign Export**: Writes timestamped summary to `outputs/campaign_reports/campaign_report_YYYYMMDD_HHMMSS.csv` with standard headers and UTF-8 encoding.
3. **Detailed Execution Export**: Writes granular reminder-level results to `outputs/campaign_reports/detailed_execution_<execution_id>.csv`.

---

## 6. Interactive Monitoring Dashboard Architecture (`dashboard.py`)

### 6.1 Purpose & Role
The interactive dashboard serves as a **read-only monitoring and audit interface** built using Streamlit. It connects directly to the local SQLite database (`data/email_automation.db`), transforming persisted audit records into intuitive visual analytics, execution history tables, and exportable reports.

```
                    ┌─────────────────────────┐
                    │  SQLite Database File   │
                    │(data/email_automation.db)
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ DatabaseManager (Read)  │
                    └────────────┬────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       ┌───────────────────┐           ┌───────────────────┐
       │ Campaign Metrics  │           │ Execution History │
       │ (Totals / Rates)  │           │ & Reminder Detail │
       └─────────┬─────────┘           └─────────┬─────────┘
                 │                               │
                 ▼                               ▼
       ┌───────────────────┐           ┌───────────────────┐
       │   KPI Summary     │           │ Interactive Visual│
       │   Metric Cards    │           │ Analytics Charts  │
       └───────────────────┘           └───────────────────┘
```

### 6.2 Component Architecture & Data Flow
1. **Status Probing (`check_database_status`)**:
   - Inspects file existence, file size, readability, and table definitions.
   - If the database file is missing or uninitialized, displays a user-friendly setup guide with instructions to run `python main.py` rather than failing.
2. **Metrics & KPI Aggregation (`fetch_campaign_metrics`)**:
   - Calculates cumulative runs, reminders examined, due, simulated, failed, and skipped.
   - Enforces `actual_sent: 0` as a strict simulation safety indicator.
3. **Data Transformation for Charts**:
   - `format_outcome_distribution`: Groups reminder-level outcomes into categorical counts (`Simulated`, `Failed`, `Skipped`, `Not Due`) and percentages for bar charts.
   - `format_history_trends`: Orders execution records chronologically for multi-series trend lines (`Simulated`, `Failed`, `Skipped`).
4. **Granular Per-Run Inspection (`render_execution_details_section`)**:
   - Allows users to select any historical `execution_id`.
   - Filters individual reminder results by `processing_status`.
   - Displays recipient, subject, scheduled time, delivery status, and diagnostic error logs.
5. **Report Downloads (`generate_campaign_csv_buffer`, `generate_detailed_csv_buffer`)**:
   - Generates RFC 4180-compliant, UTF-8 encoded in-memory CSV buffers on demand via `st.download_button`.
   - Eliminates unnecessary filesystem clutter.

### 6.3 Read-Only & Safety Guardrails
- **No Dispatch Capabilities**: The dashboard contains no email-sending buttons, no SMTP triggers, and no invocations of `EmailSender.send()`.
- **Database Non-Mutation**: The dashboard performs exclusively `SELECT` queries and never executes `INSERT`, `UPDATE`, or `DELETE`.
- **Source File Immutability**: Neither `data/contacts.csv` nor `data/reminders.csv` are accessed for write operations.

### 6.4 Known Limitations
- Local Streamlit application running on localhost (`http://localhost:8501`).
- Single-tenant monitoring view without authentication (by design for this development phase).
- Data is updated via the "Refresh Dashboard Data" button or page reload.

---

## 7. Security Guardrails & Safety Compliance

1. **Simulation-Only Automation**: The scheduler cannot trigger external network calls or SMTP delivery.
2. **Zero Credential Exposure**: No passwords or secrets are ever logged or serialized.
3. **Offline Verification**: All unit tests run completely offline with mocked dependencies.
4. **Source Immutability**: Simulated executions and dashboard views do NOT modify source `data/reminders.csv` or `data/contacts.csv` files.
5. **Persistence Isolation**: Database failures never crash operational in-memory workflows.
6. **Dashboard Read-Only Enforcement**: The monitoring interface cannot trigger executions, send emails, or alter database records.
