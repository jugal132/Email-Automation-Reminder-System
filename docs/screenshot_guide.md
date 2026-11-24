# Dashboard Screenshot Capture Guide

This guide provides instructions for capturing and embedding professional dashboard screenshots for the **Email Automation & Reminder System** portfolio presentation.

---

## 1. Prerequisites & Clean Data Generation

Before capturing screenshots, ensure the database is populated with clean, representative demonstration data.

### Step 1: Open Terminal in Project Root
```bash
cd "C:\ML\Email Automation & Reminder System"
```

### Step 2: Populate the Database via CLI Demonstration
Run the standard pipeline demonstration. This loads contacts, validates reminders, evaluates due schedules, and records execution records in SQLite:
```bash
python main.py
```

*Expected Terminal Result*:
```
===========================================================================
 EMAIL AUTOMATION & REMINDER SYSTEM
 Version      : 0.8.0
 Status       : Phase 8: Interactive Monitoring Dashboard - INITIALIZED
===========================================================================
...
[SQLITE PERSISTENCE VERIFIED]
 Execution Record in DB     : YES (Found)
 Reminder Outcomes Saved    : 5 records
```

---

## 2. Launching the Dashboard

Launch the Streamlit monitoring interface:
```bash
streamlit run dashboard.py
```
By default, the dashboard opens in your browser at `http://localhost:8501`.

---

## 3. Recommended Browser & Viewport Settings

- **Recommended Resolution**: `1920 × 1080` or `1440 × 900` pixels.
- **Browser Zoom**: Set to `100%` (standard).
- **Theme**: Light Mode (standard Streamlit default ensures high contrast in GitHub Markdown).
- **Sidebar**: Ensure the left sidebar is expanded to show branding, database status (`🟢 Connected`), and safety information.

---

## 4. Required Screenshots & Filenames

Save all screenshots into the directory:
`images/screenshots/`

| Filename | Dashboard Section to Capture | Key Elements to Show |
| :--- | :--- | :--- |
| `dashboard_overview.png` | **Top Section (Header & KPIs)** | Dashboard header, Last Refreshed badge, blue Simulation Safety banner, and all 6 KPI cards (Total Runs, Reminders Evaluated, Simulated, Failed, Skipped, Actual Emails = 0). |
| `dashboard_history.png` | **Visual Analytics & Execution History** | Outcome Status Distribution bar chart, Execution Activity Trends line chart, and the Execution History summary table. |
| `dashboard_details.png` | **Granular Execution Inspection** | Execution ID dropdown selector, metadata summary cards, status filter dropdown, and the individual reminder outcome table. |
| `dashboard_reports.png` | **Sidebar Health Probe & Downloads** | Left sidebar showing `🟢 Connected` DB status, file size, Controls, Download Campaign Summary CSV button, and Download Detailed CSV button. |

---

## 5. How to Capture Screenshots (Step-by-Step)

### Windows Snipping Tool (Recommended)
1. Press `Windows Key + Shift + S`.
2. Select **Window Snip** or **Rectangular Snip**.
3. Capture the designated section cleanly without browser scrollbars or taskbars.
4. Save the file with the designated filename in `images/screenshots/`.

### Chrome DevTools Device Mode (Pixel-Perfect)
1. Press `F12` to open DevTools.
2. Press `Ctrl + Shift + M` to toggle Device Toolbar.
3. Set dimensions to `1440 × 900`.
4. Press `Ctrl + Shift + P`, type `Capture screenshot` or `Capture full size screenshot`, and press `Enter`.
5. Rename the downloaded file to the designated filename and place in `images/screenshots/`.

---

## 6. Privacy & Safety Guidelines

- **Zero Sensitive Data**: Do not enter real personal passwords, API tokens, or confidential client emails. The project uses mock data (`alice.johnson@example.com`, `Acme Corp`, etc.), which is safe for public portfolio display.
- **Clear Safety Invariant**: Ensure the KPI card displaying **Actual Real Emails: 0 (Strict Safety Invariant)** is clearly legible.

---

## 7. Embedding Screenshots in `README.md`

Use relative GitHub Markdown paths:
```markdown
### Dashboard Overview & KPI Metrics
![Dashboard Overview](images/screenshots/dashboard_overview.png)

### Operational Analytics & Execution Trends
![Analytics & History](images/screenshots/dashboard_history.png)

### Granular Reminder-Level Audit Inspection
![Granular Execution Details](images/screenshots/dashboard_details.png)
```

---

## 8. Current Screenshot Status

| Asset Path | Status | Note |
| :--- | :--- | :--- |
| `images/screenshots/dashboard_overview.png` | *Placeholder / Capture Ready* | Follow Section 4 above to capture. |
| `images/screenshots/dashboard_history.png` | *Placeholder / Capture Ready* | Follow Section 4 above to capture. |
| `images/screenshots/dashboard_details.png` | *Placeholder / Capture Ready* | Follow Section 4 above to capture. |
| `images/screenshots/dashboard_reports.png` | *Placeholder / Capture Ready* | Follow Section 4 above to capture. |
