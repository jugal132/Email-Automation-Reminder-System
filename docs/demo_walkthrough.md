# Demonstration Video & Presentation Script

**Project:** Email Automation & Reminder System  
**Target Duration:** 4 to 5 Minutes  
**Audience:** Technical Recruiters, Hiring Managers, Code Reviewers  
**Author:** Student Portfolio Developer  

---

## Overview Timeline

```
[0:00 - 0:30]  Introduction & Problem Statement
[0:30 - 1:00]  Architecture & Clean Separation of Concerns
[1:00 - 1:30]  CLI Demonstration (Validation & Personalized Preview)
[1:30 - 2:00]  Scheduler Engine & Mandatory Simulation Safety
[2:00 - 2:45]  SQLite Persistence & Automated Campaign Reporting
[2:45 - 3:45]  Interactive Streamlit Monitoring Dashboard
[3:45 - 4:30]  Automated Testing Suite (124 Passing Tests)
[4:30 - 5:00]  Conclusion, Engineering Takeaways & Next Steps
```

---

## Segment 1: Introduction (0:00 – 0:30)

### What to Show
- Screen showing project root directory in VS Code or terminal:
  `C:\ML\Email Automation & Reminder System`
- Clean `README.md` open with project title and banner.

### What to Say
> *"Hello! Today I'm excited to present the **Email Automation & Reminder System**, a modular Python project designed to automate scheduled outreach, validate recipient data, safely personalize email bodies, and record auditable dispatch analytics.*
> 
> *In many organizations, notification scripts either fail silently when recipient data is missing or accidentally spam users when duplicate records exist. I designed this system with defensive programming and a safety-first mindset: it guarantees zero real emails can ever leak during testing while offering enterprise software engineering patterns like atomic database persistence and interactive dashboard monitoring."*

### Key Concepts to Highlight
- Defensive software engineering
- Automated notification workflows
- Simulation safety

---

## Segment 2: Architecture & Design Philosophy (0:30 – 1:00)

### What to Show
- Display the project folder structure in the editor file tree:
  ```
  src/
    contact_manager.py
    reminder_manager.py
    template_processor.py
    email_sender.py
    scheduler.py
    database.py
    report_generator.py
  ```
- Briefly show the Mermaid architecture diagram from `README.md`.

### What to Say
> *"The project follows a strict separation of concerns across decoupled modules:*
> 
> *`ContactManager` and `ReminderManager` ingest CSV datasets, enforce RFC 5322 regex email validation, and check relational integrity between contacts and reminders. Inactive or missing contacts are automatically filtered out.*
> 
> *`TemplateProcessor` detects `{{placeholder}}` tokens and replaces them using pure string substitution without dangerous `eval()` calls. `EmailSender` handles message construction, and `ReminderScheduler` orchestrates the pipeline.*
> 
> *All operational data is persisted to an SQLite database by `DatabaseManager`, summarized by `ReportGenerator`, and monitored via a Streamlit dashboard."*

### Key Concepts to Highlight
- Modularity and single-responsibility principle
- Cross-referencing relational integrity
- Safe templating (avoiding code injection vulnerabilities)

---

## Segment 3: CLI Demonstration (1:00 – 1:30)

### What to Show
- Open PowerShell / Terminal.
- Type and run:
  ```bash
  python main.py
  ```
- Scroll through Section 1 (Contact Summary), Section 2 (Reminder Summary), and Section 3 (Template Preview).

### What to Say
> *"Let's run the CLI pipeline demonstration using `python main.py`.*
> 
> *First, `ContactManager` ingests our 5 contacts: 4 are active, and 1 is inactive. Whitespace is trimmed, and email addresses are normalized.*
> 
> *Next, `ReminderManager` validates our 5 reminders. Notice how it flags reminder #3 because its recipient is inactive—excluding it from dispatch. It also identifies reminder #4 as already sent.*
> 
> *In Section 3, `TemplateProcessor` selects the first eligible pending reminder and dynamically injects the recipient's name, subject, and scheduled time into `templates/email_template.txt`. This provides a complete rendered preview before any dispatch occurs."*

### Expected Output
- Section 1: Contact summary (5 total, 4 active, 1 inactive).
- Section 2: Reminder summary (5 total, 4 pending, 1 sent, 1 overdue).
- Section 3: Rendered template preview for Alice Johnson.

---

## Segment 4: Scheduler Engine & Simulation Safety (1:30 – 2:00)

### What to Show
- Scroll down in terminal to Section 4:
  `4. SCHEDULER AUTOMATION & PERSISTENCE (SIMULATION-ONLY)`
- Point out:
  - Evaluation Reference Time: `2026-12-01 12:00`
  - Due reminders evaluated
  - Simulation queue outcome

### What to Say
> *"Now we see the `ReminderScheduler` in action. We evaluate schedules against a deterministic reference time—December 1st at 12:00 PM.*
> 
> *Out of 5 reminders, exactly 1 is due: reminder #1 scheduled for 10:00 AM. Reminder #2 and #5 are scheduled in the future and marked `NOT_DUE`. Reminder #3 is skipped because the contact is inactive, and reminder #4 is skipped because it is already sent.*
> 
> *Crucially, look at the safety banner: **Simulation Only**. The scheduler hard-locks the dispatch engine to simulation mode. It generates realistic delivery metadata and UUID-based message IDs, but **zero network sockets or SMTP connections are opened**. The source CSV files remain 100% untouched."*

### Key Concepts to Highlight
- Reference-time scheduling comparison
- Elimination of race conditions
- Mandatory simulation safety invariant (`actual_sent = 0`)

---

## Segment 5: SQLite Persistence & Campaign Reporting (2:00 – 2:45)

### What to Show
- Scroll to Section 5 in terminal:
  `5. DATABASE PERSISTENCE & CAMPAIGN REPORTING`
- Point out SQLite verification output and exported CSV paths in `outputs/campaign_reports/`.

### What to Say
> *"Next is our persistence and reporting subsystem.*
> 
> *In Section 5, `DatabaseManager` commits the entire run into SQLite. It inserts the parent run into `execution_history` and all 5 individual reminder outcomes into `reminder_executions` inside a single atomic transaction. If an error had occurred midway, SQLite would trigger a complete rollback, guaranteeing zero orphaned records.*
> 
> *`ReportGenerator` then calculates campaign metrics across all historical runs and exports a timestamped CSV summary and detailed execution report into the `outputs/campaign_reports/` directory."*

### Expected Output
- SQLite persistence confirmed.
- Campaign metrics displayed (100% simulation success rate).
- Exported CSV file paths printed.

---

## Segment 6: Interactive Streamlit Monitoring Dashboard (2:45 – 3:45)

### What to Show
- Switch to terminal and run:
  ```bash
  streamlit run dashboard.py
  ```
- Open browser at `http://localhost:8501`.
- Walk through the visual elements:
  1. **Sidebar**: Show `🟢 Connected` database status, file size, and Refresh button.
  2. **Header & Banner**: Point out the blue "SIMULATION ONLY MODE ACTIVE" banner.
  3. **KPI Cards**: Highlight Total Runs, Evaluated, Simulated, and **Actual Real Emails: 0 (Strict Safety Invariant)**.
  4. **Charts**: Hover over the Outcome Status Distribution bar chart and Activity Trends line chart.
  5. **Granular Inspection**: Select an Execution ID from the dropdown, filter by status, and show the detailed table.
  6. **Download Button**: Click "Download Campaign Summary CSV" to show instant in-memory download.

### What to Say
> *"Now let's launch our interactive monitoring dashboard using `streamlit run dashboard.py`.*
> 
> *The dashboard is a **read-only monitoring console**. In the sidebar, you see our live SQLite database probe confirming a healthy connection, file size, and total recorded runs.*
> 
> *At the top, our KPI cards show cumulative metrics. Notice the sixth metric card: 'Actual Real Emails: 0'. This reinforces our safety invariant across the entire stack.*
> 
> *Below the KPIs, we have dynamic charts: a bar chart displaying outcome distributions across simulated, failed, and future items, and a line chart tracking activity trends over historical runs.*
> 
> *Further down, the user can select any historical run to inspect reminder-level outcomes—including recipient, subject, scheduled time, and diagnostic error reasons. Finally, users can download structured CSV reports directly in memory with one click."*

---

## Segment 7: Testing & Security Audit (3:45 – 4:30)

### What to Show
- Switch back to terminal.
- Run:
  ```bash
  pytest -v
  ```
- Let the 124 tests run and display the green pass bar:
  `124 passed in X.XXs`

### What to Say
> *"Quality assurance is central to this project. We run our automated test suite using `pytest -v`.*
> 
> *All 124 tests pass in under 5 seconds. Our tests cover email regex edge cases, contact deduplication, missing context errors in templates, isolated failure handling in the scheduler, foreign key cascade deletions, atomic transaction rollbacks using SQLite triggers, and Streamlit dashboard rendering.*
> 
> *Furthermore, `.env` is gitignored, credentials are never logged, and all source CSV files are verified to remain completely immutable."*

### Expected Output
- `124 passed` across 8 test modules.

---

## Segment 8: Conclusion & Roadmap (4:30 – 5:00)

### What to Show
- Return to the browser showing the clean Streamlit dashboard or project README.

### What to Say
> *"To summarize: this project demonstrates that automated notification systems can be modular, auditable, test-driven, and completely safe.*
> 
> *For future development, the natural next steps would be integrating timezone-aware scheduling via Python's `zoneinfo`, adding asynchronous background workers with Celery, and introducing user authentication on the dashboard.*
> 
> *Thank you for your time! The complete source code, test suites, and documentation are available on GitHub."*

---

## Presenter Preparation Checklist
- [ ] Terminal open at `C:\ML\Email Automation & Reminder System`.
- [ ] Virtual environment activated (`.\.venv\Scripts\Activate.ps1`).
- [ ] Database populated by running `python main.py` once beforehand.
- [ ] Browser window open and sized to `1920 × 1080` or `1440 × 900`.
- [ ] Font size in terminal and browser adjusted for crisp presentation.
