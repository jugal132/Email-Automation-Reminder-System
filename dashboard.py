"""
Interactive Monitoring Dashboard for Email Automation & Reminder System.

A read-only Streamlit monitoring application providing:
- Key Performance Indicator (KPI) cards with simulation safety metrics
- Real-time and historical execution analytics and outcome charts
- Detailed per-run scheduler inspection and reminder-level outcomes
- Filterable execution tables and granular audit trails
- Standardized CSV campaign and detailed execution report downloads
- System and database health indicators

Launch command:
    streamlit run dashboard.py
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import streamlit as st

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database import DEFAULT_DB_PATH, DatabaseError, DatabaseManager
from src.logger_config import get_logger
from src.report_generator import ReportGenerator

logger = get_logger("dashboard")

APP_VERSION = "0.8.0"


# -----------------------------------------------------------------------------
# Data Access & Transformation Layer (Testable & Read-Only)
# -----------------------------------------------------------------------------

def resolve_db_path(custom_path: Optional[Union[str, Path]] = None) -> Path:
    """
    Resolve the absolute path to the SQLite database file.

    Args:
        custom_path: Optional custom path override.

    Returns:
        Path: Resolved Path object.
    """
    if custom_path:
        return Path(custom_path).resolve()
    return Path(DEFAULT_DB_PATH).resolve()


def check_database_status(db_path: Path) -> Dict[str, Any]:
    """
    Inspect the database file existence, accessibility, and size.

    Args:
        db_path: Path to the SQLite database.

    Returns:
        Dict[str, Any]: Status dictionary containing exists, size_kb, readable, and error.
    """
    if not db_path.exists():
        return {
            "exists": False,
            "path": str(db_path),
            "size_kb": 0.0,
            "readable": False,
            "error": "Database file not found. Run 'python main.py' to initialize and populate data.",
        }

    try:
        size_bytes = db_path.stat().st_size
        size_kb = round(size_bytes / 1024, 2)
        # Attempt a read-only probe
        uri_path = f"file:{db_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri_path, uri=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]

        return {
            "exists": True,
            "path": str(db_path),
            "size_kb": size_kb,
            "readable": True,
            "tables": tables,
            "error": None,
        }
    except Exception as exc:
        return {
            "exists": True,
            "path": str(db_path),
            "size_kb": 0.0,
            "readable": False,
            "error": f"Database read check failed: {exc}",
        }


def get_read_only_db_manager(db_path: Path) -> DatabaseManager:
    """
    Construct a DatabaseManager pointing to the specified database.

    Args:
        db_path: Path to the SQLite database.

    Returns:
        DatabaseManager: Initialized manager instance.
    """
    return DatabaseManager(db_path=str(db_path))


def fetch_campaign_metrics(db_mgr: DatabaseManager) -> Dict[str, Any]:
    """
    Retrieve aggregated campaign metrics safely.

    Args:
        db_mgr: DatabaseManager instance.

    Returns:
        Dict[str, Any]: Campaign metrics dictionary.
    """
    try:
        return db_mgr.get_campaign_metrics()
    except Exception as exc:
        logger.error("Error fetching campaign metrics: %s", exc)
        return {
            "total_runs": 0,
            "total_reminders_examined": 0,
            "total_due": 0,
            "total_processed": 0,
            "total_simulated": 0,
            "total_failed": 0,
            "total_skipped": 0,
            "actual_sent": 0,
            "simulation_success_rate": 0.0,
            "latest_execution_timestamp": None,
            "error": str(exc),
        }


def fetch_execution_history(
    db_mgr: DatabaseManager, limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve stored execution history records.

    Args:
        db_mgr: DatabaseManager instance.
        limit: Optional maximum rows to return.

    Returns:
        List[Dict[str, Any]]: List of execution records.
    """
    try:
        return db_mgr.get_execution_history(limit=limit)
    except Exception as exc:
        logger.error("Error fetching execution history: %s", exc)
        return []


def fetch_execution_results(
    db_mgr: DatabaseManager, execution_id: str
) -> List[Dict[str, Any]]:
    """
    Retrieve individual reminder outcomes for a specified execution.

    Args:
        db_mgr: DatabaseManager instance.
        execution_id: Execution run ID.

    Returns:
        List[Dict[str, Any]]: List of reminder outcomes.
    """
    try:
        return db_mgr.get_results_for_execution(execution_id)
    except Exception as exc:
        logger.error("Error fetching execution results for %s: %s", execution_id, exc)
        return []


def format_outcome_distribution(results: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Transform a list of reminder execution records into an aggregated DataFrame
    suitable for bar or pie chart visualization.

    Args:
        results: List of reminder execution dictionaries.

    Returns:
        pd.DataFrame: DataFrame with columns ['Outcome Status', 'Count', 'Percentage'].
    """
    if not results:
        return pd.DataFrame(columns=["Outcome Status", "Count", "Percentage"])

    counts: Dict[str, int] = {}
    total = len(results)

    for item in results:
        status = item.get("processing_status", "unknown").capitalize()
        counts[status] = counts.get(status, 0) + 1

    rows = []
    for status, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        pct = round((count / total) * 100, 1) if total > 0 else 0.0
        rows.append({"Outcome Status": status, "Count": count, "Percentage": pct})

    return pd.DataFrame(rows)


def format_history_trends(history: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Transform execution history records into a chronological DataFrame for trend charting.

    Args:
        history: List of execution history dictionaries.

    Returns:
        pd.DataFrame: Chronological trend data.
    """
    if not history:
        return pd.DataFrame()

    # Create chronological sequence (oldest to newest)
    sorted_history = sorted(history, key=lambda x: x.get("execution_timestamp", ""))

    data = []
    for item in sorted_history:
        ts = item.get("execution_timestamp", "")
        # Shorten timestamp for chart label if needed
        label = ts[5:16] if len(ts) >= 16 else item.get("execution_id", "")
        data.append({
            "Run": label,
            "Execution ID": item.get("execution_id", ""),
            "Simulated": item.get("total_simulated", 0),
            "Failed": item.get("total_failed", 0),
            "Skipped": item.get("total_skipped", 0),
            "Due": item.get("total_due", 0),
        })

    return pd.DataFrame(data)


def generate_campaign_csv_buffer(db_mgr: DatabaseManager) -> io.BytesIO:
    """
    Generate an in-memory CSV buffer for campaign summary export.

    Args:
        db_mgr: DatabaseManager instance.

    Returns:
        io.BytesIO: In-memory binary buffer containing UTF-8 encoded CSV.
    """
    history = fetch_execution_history(db_mgr)
    fieldnames = [
        "execution_id",
        "execution_timestamp",
        "reference_time",
        "total_reminders_examined",
        "total_due",
        "total_processed",
        "total_simulated",
        "total_failed",
        "total_skipped",
        "actual_sent",
        "simulation_success_rate_pct",
        "notes",
    ]

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()

    for row in history:
        processed = row.get("total_processed", 0)
        simulated = row.get("total_simulated", 0)
        due = row.get("total_due", 0)
        failed = row.get("total_failed", 0)

        if processed > 0:
            success_rate = round((simulated / processed) * 100, 2)
        elif due > 0:
            success_rate = round((simulated / due) * 100, 2)
        else:
            success_rate = 100.0 if failed == 0 else 0.0

        writer.writerow({
            "execution_id": row.get("execution_id", ""),
            "execution_timestamp": row.get("execution_timestamp", ""),
            "reference_time": row.get("reference_time", ""),
            "total_reminders_examined": row.get("total_reminders_examined", 0),
            "total_due": due,
            "total_processed": processed,
            "total_simulated": simulated,
            "total_failed": failed,
            "total_skipped": row.get("total_skipped", 0),
            "actual_sent": 0,  # Mandatory simulation safety invariant
            "simulation_success_rate_pct": success_rate,
            "notes": row.get("notes") or "",
        })

    return io.BytesIO(out.getvalue().encode("utf-8"))


def generate_detailed_csv_buffer(
    db_mgr: DatabaseManager, execution_id: str
) -> io.BytesIO:
    """
    Generate an in-memory CSV buffer for a specific execution run.

    Args:
        db_mgr: DatabaseManager instance.
        execution_id: Unique execution identifier.

    Returns:
        io.BytesIO: In-memory binary buffer containing UTF-8 encoded CSV.
    """
    results = fetch_execution_results(db_mgr, execution_id)
    fieldnames = [
        "id",
        "execution_id",
        "reminder_id",
        "contact_id",
        "recipient",
        "subject",
        "scheduled_at",
        "processing_status",
        "delivery_status",
        "error",
        "timestamp",
        "message_id",
    ]

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()

    for r in results:
        writer.writerow({
            "id": r.get("id", ""),
            "execution_id": r.get("execution_id", ""),
            "reminder_id": r.get("reminder_id", ""),
            "contact_id": r.get("contact_id", ""),
            "recipient": r.get("recipient", ""),
            "subject": r.get("subject", ""),
            "scheduled_at": r.get("scheduled_at", ""),
            "processing_status": r.get("processing_status", ""),
            "delivery_status": r.get("delivery_status") or "",
            "error": r.get("error") or "",
            "timestamp": r.get("timestamp", ""),
            "message_id": r.get("message_id") or "",
        })

    return io.BytesIO(out.getvalue().encode("utf-8"))


# -----------------------------------------------------------------------------
# Streamlit UI Rendering Functions
# -----------------------------------------------------------------------------

def render_sidebar(db_status: Dict[str, Any], metrics: Dict[str, Any]) -> None:
    """Render the responsive sidebar with branding, connection status, and safety card."""
    with st.sidebar:
        st.markdown("### 📬 Email Automation")
        st.caption(f"System Monitoring Dashboard v{APP_VERSION}")
        st.divider()

        # Database Connection Status
        st.markdown("#### 🗄️ Database Status")
        if db_status["exists"] and db_status["readable"]:
            st.success("🟢 Connected (Read-Only)")
            st.caption(f"**Path**: `{Path(db_status['path']).name}`")
            st.caption(f"**Size**: `{db_status['size_kb']} KB`")
            st.caption(f"**Total Runs Stored**: `{metrics.get('total_runs', 0)}`")
        else:
            st.warning("🟡 Database Missing / Uninitialized")
            st.caption("Please run `python main.py` in the terminal to initialize and populate data.")

        # Refresh Control
        st.divider()
        st.markdown("#### 🔄 Controls")
        if st.button("Refresh Dashboard Data", use_container_width=True):
            st.rerun()

        # Simulation Safety Policy Card
        st.divider()
        st.markdown("#### 🛡️ Safety & Policy")
        st.info(
            "**SIMULATION ONLY ENVIRONMENT**\n\n"
            "• Read-only monitoring interface\n"
            "• Zero real emails are sent\n"
            "• Actual email count is strictly **0**\n"
            "• No SMTP or network transmission triggered"
        )


def render_header(metrics: Dict[str, Any]) -> None:
    """Render the dashboard top header and refresh timestamp."""
    col_title, col_time = st.columns([3, 1])

    with col_title:
        st.title("Email Automation & Reminder System")
        st.markdown(
            "##### Monitoring, Execution History & Campaign Analytics"
        )

    with col_time:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.caption(f"🕒 **Last Refreshed**\n{now_str}")


def render_safety_banner() -> None:
    """Render prominent simulation-only safety banner."""
    st.markdown(
        """
        <div style="background-color: #f0f7ff; border-left: 5px solid #0066cc; padding: 12px 16px; border-radius: 4px; margin-bottom: 20px;">
            <strong style="color: #004085;">🛡️ SYSTEM STATUS: SIMULATION ONLY MODE ACTIVE</strong><br/>
            <span style="font-size: 0.9em; color: #333333;">
                This dashboard is a <strong>read-only monitoring view</strong>. No outbound email connections or SMTP deliveries are executed.
                Source CSV records and database tables are protected from mutation.
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpis(metrics: Dict[str, Any]) -> None:
    """Render KPI metric cards across a 6-column layout."""
    st.markdown("### 📊 Campaign Performance Highlights")

    kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)

    with kpi1:
        st.metric(
            label="Total Runs",
            value=metrics.get("total_runs", 0),
            help="Total completed scheduler execution batches",
        )

    with kpi2:
        st.metric(
            label="Reminders Evaluated",
            value=metrics.get("total_reminders_examined", 0),
            help="Total reminder records evaluated across all runs",
        )

    with kpi3:
        success_rate = metrics.get("simulation_success_rate", 0.0)
        st.metric(
            label="Simulated (Success)",
            value=metrics.get("total_simulated", 0),
            delta=f"{success_rate:.1f}% rate",
            help="Successfully simulated deliveries dispatched to mock queue",
        )

    with kpi4:
        st.metric(
            label="Dispatches Failed",
            value=metrics.get("total_failed", 0),
            help="Processing or rendering failures encountered",
        )

    with kpi5:
        st.metric(
            label="Reminders Skipped",
            value=metrics.get("total_skipped", 0),
            help="Reminders skipped due to future schedules, inactive contacts, or non-pending statuses",
        )

    with kpi6:
        st.metric(
            label="Actual Real Emails",
            value="0",
            delta="Strict Safety Invariant",
            delta_color="off",
            help="Guaranteed 0 real emails sent under simulation mode",
        )


def render_charts_and_analytics(
    history: List[Dict[str, Any]], all_results: List[Dict[str, Any]]
) -> None:
    """Render visual analytics charts for outcome distribution and execution trends."""
    st.markdown("### 📈 Operational Analytics")

    if not history or not all_results:
        st.info("ℹ️ No historical execution data available to generate charts. Run `python main.py` to populate data.")
        return

    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.markdown("#### Outcome Status Distribution")
        df_outcomes = format_outcome_distribution(all_results)
        if not df_outcomes.empty:
            chart_data = df_outcomes.set_index("Outcome Status")["Count"]
            st.bar_chart(chart_data, color="#1f77b4")
            st.dataframe(
                df_outcomes,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No outcome records found.")

    with col_chart2:
        st.markdown("#### Execution Activity Trends")
        df_trends = format_history_trends(history)
        if not df_trends.empty:
            trend_data = df_trends.set_index("Run")[["Simulated", "Failed", "Skipped"]]
            st.line_chart(trend_data)
            st.caption("Chronological progression across recorded scheduler execution runs.")
        else:
            st.caption("Insufficient historical data for trend analysis.")


def render_execution_history_section(
    history: List[Dict[str, Any]], db_mgr: DatabaseManager
) -> Optional[str]:
    """
    Render the execution history table, CSV export button, and execution selector.

    Args:
        history: List of execution history dictionaries.
        db_mgr: DatabaseManager instance.

    Returns:
        Optional[str]: Selected execution_id for inspection, if any.
    """
    st.markdown("### 📜 Scheduler Execution History")

    if not history:
        st.warning("No execution history recorded in the database.")
        return None

    # Format history into clean display DataFrame
    display_rows = []
    for h in history:
        processed = h.get("total_processed", 0)
        simulated = h.get("total_simulated", 0)
        due = h.get("total_due", 0)
        failed = h.get("total_failed", 0)

        if processed > 0:
            rate = round((simulated / processed) * 100, 1)
        elif due > 0:
            rate = round((simulated / due) * 100, 1)
        else:
            rate = 100.0 if failed == 0 else 0.0

        display_rows.append({
            "Execution ID": h.get("execution_id", ""),
            "Executed At": h.get("execution_timestamp", ""),
            "Reference Time": h.get("reference_time", ""),
            "Evaluated": h.get("total_reminders_examined", 0),
            "Due": due,
            "Simulated": simulated,
            "Failed": failed,
            "Skipped": h.get("total_skipped", 0),
            "Success Rate": f"{rate:.1f}%",
            "Notes": h.get("notes") or "-",
        })

    df_history = pd.DataFrame(display_rows)
    st.dataframe(df_history, use_container_width=True, hide_index=True)

    # Download Campaign Report CSV
    col_dl, col_space = st.columns([1, 2])
    with col_dl:
        csv_buffer = generate_campaign_csv_buffer(db_mgr)
        st.download_button(
            label="📥 Download Campaign Summary CSV",
            data=csv_buffer.getvalue(),
            file_name=f"campaign_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # Execution Selection for Granular Inspection
    st.markdown("---")
    st.markdown("### 🔍 Granular Execution Inspection")

    exec_options = [h.get("execution_id", "") for h in history if h.get("execution_id")]
    if not exec_options:
        return None

    selected_exec_id = st.selectbox(
        "Select an Execution ID to inspect reminder-level outcomes:",
        options=exec_options,
        index=0,
    )

    return selected_exec_id


def render_execution_details_section(
    execution_id: str, db_mgr: DatabaseManager
) -> None:
    """Render granular reminder outcomes and filters for the selected execution."""
    st.markdown(f"#### Execution Details: `{execution_id}`")

    exec_record = db_mgr.get_execution_by_id(execution_id)
    results = fetch_execution_results(db_mgr, execution_id)

    if not exec_record or not results:
        st.info("No detailed outcomes found for this execution.")
        return

    # Metadata cards
    meta1, meta2, meta3, meta4 = st.columns(4)
    with meta1:
        st.caption("Execution Timestamp")
        st.write(f"**{exec_record.get('execution_timestamp', '-')}**")
    with meta2:
        st.caption("Reference Time Evaluated")
        st.write(f"**{exec_record.get('reference_time', '-')}**")
    with meta3:
        st.caption("Due vs Simulated")
        st.write(f"**{exec_record.get('total_due', 0)} due / {exec_record.get('total_simulated', 0)} simulated**")
    with meta4:
        st.caption("Skipped / Not Due")
        st.write(f"**{exec_record.get('total_skipped', 0)} skipped**")

    # Status filter
    status_options = ["All"] + sorted(list({r.get("processing_status", "") for r in results if r.get("processing_status")}))
    chosen_status = st.selectbox("Filter outcomes by processing status:", options=status_options)

    filtered_results = results
    if chosen_status != "All":
        filtered_results = [r for r in results if r.get("processing_status") == chosen_status]

    # Format into table
    table_rows = []
    for r in filtered_results:
        table_rows.append({
            "Reminder ID": r.get("reminder_id", ""),
            "Contact ID": r.get("contact_id", ""),
            "Recipient": r.get("recipient", ""),
            "Subject": r.get("subject", ""),
            "Scheduled Time": r.get("scheduled_at", ""),
            "Processing Status": r.get("processing_status", "").upper(),
            "Delivery Status": r.get("delivery_status", "-") or "-",
            "Diagnostic / Reason": r.get("error", "-") or "Processed successfully",
            "Message ID": r.get("message_id", "-") or "-",
        })

    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # Download Detailed Run CSV
    detailed_csv = generate_detailed_csv_buffer(db_mgr, execution_id)
    st.download_button(
        label=f"📥 Download Detailed CSV for {execution_id}",
        data=detailed_csv.getvalue(),
        file_name=f"detailed_execution_{execution_id}.csv",
        mime="text/csv",
    )


def render_empty_state_guide() -> None:
    """Render helpful instructions when no database or execution history is present."""
    st.info(
        "### 🚀 Welcome to the Email Automation & Reminder System Dashboard!\n\n"
        "No historical execution records were found in the database. To populate the system:\n\n"
        "1. Open your terminal in the project directory:\n"
        "   ```bash\n"
        "   cd \"C:\\ML\\Email Automation & Reminder System\"\n"
        "   ```\n"
        "2. Run the pipeline demonstration:\n"
        "   ```bash\n"
        "   python main.py\n"
        "   ```\n"
        "3. Click **Refresh Dashboard Data** in the sidebar to view the populated analytics."
    )


# -----------------------------------------------------------------------------
# Main Application Entry Point
# -----------------------------------------------------------------------------

def main() -> None:
    """Configure page and orchestrate dashboard UI components."""
    # Set page config must be the first Streamlit command
    st.set_page_config(
        page_title="Email Automation Monitoring Dashboard",
        page_icon="📬",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    db_path = resolve_db_path()
    db_status = check_database_status(db_path)

    # If database file doesn't exist or isn't readable
    if not db_status["exists"] or not db_status["readable"]:
        render_sidebar(db_status, {})
        render_header({})
        render_safety_banner()
        render_empty_state_guide()
        return

    # Database is readable: query metrics and execution data
    db_mgr = get_read_only_db_manager(db_path)
    metrics = fetch_campaign_metrics(db_mgr)
    history = fetch_execution_history(db_mgr)
    all_results = db_mgr.get_all_reminder_executions()

    # Render UI
    render_sidebar(db_status, metrics)
    render_header(metrics)
    render_safety_banner()

    if metrics.get("total_runs", 0) == 0:
        render_empty_state_guide()
        return

    render_kpis(metrics)
    st.divider()

    render_charts_and_analytics(history, all_results)
    st.divider()

    selected_exec_id = render_execution_history_section(history, db_mgr)

    if selected_exec_id:
        st.divider()
        render_execution_details_section(selected_exec_id, db_mgr)


if __name__ == "__main__":
    main()
