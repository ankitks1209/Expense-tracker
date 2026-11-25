"""Cashflow, budgets, and transaction history for Enma."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta, datetime
import sqlite3
from html import escape
from io import BytesIO, StringIO

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

from db import (
    init_db,
    monthly_budgets,
    set_monthly_budget,
    get_all_expenses,
    delete_expense,
    insert_expense_row,
    insert_expense_rows,
    save_chat_entries,
    DuplicateExpense,
    get_repayments,
    update_repayment,
    settle_repayment,
    remove_repayment,
    move_expense_to_repayments,
    undo_move_to_repayments,
    get_expense_by_id,
)
from ai_extractor import ALL_CATEGORIES
from dashboard_utils import budget_progress, calculate_period_comparison, prepare_export_frame
from enma_ui import apply_theme, page_header
from ledger_access import require_ledger_access

st.set_page_config(page_title="Dashboard · Enma", page_icon=":material/monitoring:", layout="wide", initial_sidebar_state="collapsed")

palette = apply_theme()
require_ledger_access()
init_db()

RECEIVED_COLOR = palette["income"]
SPENT_COLOR = palette["expense-bar"]
GRID_C = palette["border"]
TEXT_C = palette["muted"]


def chart_style(fig, height=260):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Mono, monospace", color=TEXT_C, size=11),
        title=dict(text=""),
        margin=dict(l=16, r=40, t=8, b=32),
        height=height,
        hovermode="x unified",
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT_C, size=11),
            orientation="h", y=-0.16,
        ),
        xaxis=dict(
            gridcolor=GRID_C,
            zerolinecolor=GRID_C,
            tickfont=dict(color=TEXT_C, size=10),
            showline=False,
            automargin=True,
        ),
        yaxis=dict(
            gridcolor=GRID_C,
            zerolinecolor=GRID_C,
            tickfont=dict(color=TEXT_C, size=10),
            showline=False,
            automargin=True,
        ),
    )
    return fig


# ── Original helper functions (unchanged) ─────────────────────────────────────
def reset_dashboard_filters():
    st.session_state.dash_preset = "Last 30 days"
    st.session_state.dash_chart_mode = "Overview"
    st.session_state.dash_search = ""
    st.session_state.dash_type_filter = "all"
    st.session_state.dash_cat_filter = "all categories"

def toggle_export_panel():
    st.session_state.export_panel = not st.session_state.get("export_panel", False)


def set_dash_undo(action_type, payload, label):
    st.session_state.dash_undo_action = {
        "type": action_type,
        "payload": payload,
        "label": label,
    }
    st.toast(label)

def render_repayments():
    if notice := st.session_state.pop("repayment_notice", None):
        st.success(notice)
    reminders = get_repayments()
    to_collect = sum(row["amount"] for row in reminders if row["direction"] == "collect")
    to_pay = sum(row["amount"] for row in reminders if row["direction"] == "pay")
    with st.expander(f"Repayments · To collect ₹{to_collect:,.2f} · To pay ₹{to_pay:,.2f}", expanded=bool(reminders)):
        collect_total, pay_total = st.columns(2)
        collect_total.metric("Others owe you", f"₹{to_collect:,.2f}")
        pay_total.metric("You owe others", f"₹{to_pay:,.2f}")
        st.caption("These amounts enter your ledger when you mark them received or paid.")
        today = date.today()
        for row in reminders:
            collect = row["direction"] == "collect"
            person = row["person"] or "Name needed"
            if person.casefold() in {"जिसमें", "जिसमे", "उसमें", "someone"}:
                person = "Name needs review"
            amount = f"₹{row['amount']:,.2f}".removesuffix(".00")
            title = f"{person} owes you {amount}" if collect else f"You owe {person} {amount}"
            with st.container(border=True):
                st.text(title)
                if row["note"]:
                    st.text(row["note"])
                if row["due_date"]:
                    due = date.fromisoformat(row["due_date"])
                    label = "Overdue" if due < today else "Due today" if due == today else "Due"
                    st.caption(f"{label} · {due.strftime('%d %b %Y').lstrip('0')}")
                else:
                    st.caption("Waiting to be received" if collect else "Waiting to be paid")
                settle, remove = st.columns(2)
                if settle.button("Mark received" if collect else "Mark paid", key=f"settle_repayment_{row['id']}"):
                    try:
                        settlement_id = settle_repayment(row["id"])
                    except (sqlite3.Error, ValueError):
                        st.error("Could not record the payment. Try again.")
                    else:
                        if settlement_id:
                            set_dash_undo("repayment", {"id": settlement_id}, "Repayment recorded")
                        st.rerun()
                with remove.popover("Remove reminder"):
                    st.caption("Remove this from Repayments?")
                    if st.button("Remove", key=f"remove_repayment_{row['id']}"):
                        try:
                            remove_repayment(row["id"])
                        except sqlite3.Error:
                            st.error("Could not remove the reminder. Try again.")
                        else:
                            st.session_state.repayment_notice = "Reminder removed."
                            st.rerun()
                with st.popover("Edit name or due date"):
                    with st.form(f"edit_repayment_{row['id']}"):
                        name = st.text_input("Name", value=row["person"])
                        due_date = st.date_input("Due date (optional)", value=date.fromisoformat(row["due_date"]) if row["due_date"] else None)
                        if st.form_submit_button("Save changes"):
                            try:
                                update_repayment(row["id"], name, due_date.isoformat() if due_date else None)
                            except (sqlite3.Error, ValueError):
                                st.error("Could not update the reminder. Try again.")
                            else:
                                st.session_state.repayment_notice = "Reminder updated."
                                st.rerun()
        with st.form("repayment_form"):
            st.markdown("**Add a reminder**")
            direction = st.radio("Who owes the money?", ["Someone owes me", "I owe someone"], horizontal=True)
            person = st.text_input("Name")
            amount = st.number_input("Amount in rupees", min_value=0.01, value=None, step=1.0, format="%.2f")
            note = st.text_input("What was it for? (optional)")
            due = st.date_input("Due date (optional)", value=None)
            if st.form_submit_button("Add reminder", type="primary"):
                if not person.strip() or amount is None:
                    st.warning("Enter a name and an amount.")
                else:
                    try:
                        reminder = {"direction": "collect" if direction == "Someone owes me" else "pay",
                                    "person": person, "amount": amount, "note": note,
                                    "due_date": due.isoformat() if due else None}
                        save_chat_entries([], [reminder], check_duplicates=True)
                    except DuplicateExpense:
                        st.session_state.duplicate_reminder = reminder
                    except (sqlite3.Error, ValueError):
                        st.error("Could not add the reminder. Check the amount and try again.")
                    else:
                        st.session_state.repayment_notice = "Reminder added."
                        st.rerun()


        if reminder := st.session_state.get("duplicate_reminder"):
            st.warning(f"A matching ₹{reminder['amount']:,.2f} reminder for {reminder['person']} exists.")
            keep, cancel = st.columns(2)
            if keep.button("Add as a separate debt"):
                save_chat_entries([], [reminder])
                st.session_state.pop("duplicate_reminder")
                st.rerun()
            if cancel.button("Cancel duplicate reminder"):
                st.session_state.pop("duplicate_reminder")
                st.rerun()


# ── Budget & Export helpers ────────────────────────────────────────────────────
def export_to_csv(df_data, filename="expense_report.csv"):
    """Generate CSV export"""
    csv_buffer = StringIO()
    df_data.to_csv(csv_buffer, index=False)
    return csv_buffer.getvalue()


def generate_pdf_report(title, kpis_dict, df_data):
    """Generate PDF report (requires reportlab)"""
    if not HAS_REPORTLAB:
        return None

    pdf_buffer = BytesIO()
    try:
        doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles = getSampleStyleSheet()

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#141416'),
            spaceAfter=12,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph(title, title_style))
        elements.append(Spacer(1, 0.2*inch))

        # KPIs as table
        kpi_data = [['Metric', 'Value']]
        for k, v in kpis_dict.items():
            kpi_data.append([str(k), str(v)])

        kpi_table = Table(kpi_data, colWidths=[3*inch, 2*inch])
        kpi_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366f1')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(kpi_table)
        elements.append(Spacer(1, 0.2*inch))

        # Transaction table
        if not df_data.empty:
            tx_data = [df_data.columns.tolist()]
            for _, row in df_data.head(50).iterrows():
                tx_data.append([str(x) for x in row])

            tx_table = Table(tx_data, colWidths=[1*inch]*len(df_data.columns))
            tx_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ede9e2')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey)
            ]))
            elements.append(Paragraph("Recent Transactions", styles['Heading2']))
            elements.append(tx_table)

        doc.build(elements)
        pdf_buffer.seek(0)
        return pdf_buffer
    except Exception as e:
        return None


page_header(page="dashboard")
st.html("""
    <div class="enma-heading">
        <h1>Dashboard</h1>
        <p>See what came in, what went out, and where you spent it.</p>
    </div>
""")

st.session_state.setdefault("confirm_reset_all", False)
st.session_state.setdefault("dash_undo_action", None)
budget_month = date.today().strftime("%Y-%m")
for category, amount in st.session_state.pop("budgets", {}).items():
    if category not in monthly_budgets(budget_month):
        set_monthly_budget(budget_month, category, amount)
st.session_state.setdefault("export_panel", False)
undo_state = st.session_state.dash_undo_action
if undo_state:
    undo_hint = "Undo reopens the reminder." if undo_state["type"] == "repayment" else "Undo restores the entries."
    st.caption(f"{undo_state['label']}. {undo_hint} Dismiss keeps the change.")
    undo_col, dismiss_col = st.columns(2)
    if undo_col.button("Undo", key="dash_undo", icon=":material/undo:"):
        if undo_state["type"] == "delete":
            insert_expense_row(undo_state["payload"]["row"])
        elif undo_state["type"] == "reset":
            insert_expense_rows(undo_state["payload"]["rows"])
        elif undo_state["type"] == "repayment":
            delete_expense(undo_state["payload"]["id"])
        elif undo_state["type"] == "move_to_repayments":
            try:
                undo_move_to_repayments(undo_state["payload"])
            except (ValueError, sqlite3.Error) as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else "Could not undo the correction. Try again.")
                st.stop()
        st.session_state.dash_undo_action = None
        st.rerun()
    if dismiss_col.button("Dismiss", key="dash_undo_dismiss"):
        st.session_state.dash_undo_action = None
        st.rerun()

render_repayments()

all_rows = get_all_expenses()
if not all_rows:
    st.html("""
        <section class="enma-empty-state">
            <h2>No transactions yet</h2>
            <p>Log a transaction in chat to see your cashflow here.</p>
        </section>
    """)
    st.stop()

df = pd.DataFrame(all_rows, columns=["id", "amount", "category", "transaction_type", "date", "note", "raw_input", "created_at"])
df["recorded_date"] = df["date"]
df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
today = date.today()
if df["date"].isna().any():
    st.warning("Some saved transactions have invalid dates. Find those entries under All time in the transaction log.")

# ── Filters (original session-state logic unchanged) ─────────────────────────
with st.container(key="dashboard_filters"):
    fc1, fc2, fc3, fc4 = st.columns([2, 2, 1.2, 1], vertical_alignment="bottom")
    with fc1:
        st.session_state.setdefault("dash_preset", "Last 30 days")
        preset = st.selectbox("Date range", ["Last 30 days","Last 7 days","This month","Last 3 months","All time"],
                              key="dash_preset")
    with fc2:
        st.session_state.setdefault("dash_chart_mode", "Overview")
        chart_mode = st.selectbox("Chart view", ["Overview","Credit vs Debit","Income only","Expense only"],
                                  key="dash_chart_mode", format_func={"Overview": "Money in and out", "Credit vs Debit": "Compare received and spent", "Income only": "Money received only", "Expense only": "Money spent only"}.get)
    with fc3:
        st.button("Reset filters", key="dash_reset_filters", on_click=reset_dashboard_filters, width="stretch")
    with fc4:
        st.button("Export", key="export_toggle", icon=":material/download:", on_click=toggle_export_panel, width="stretch")

# ── Export dialog ─────────────────────────────────────────────────────────────
if st.session_state.get("export_panel"):
    with st.expander("Download reports", expanded=True):
        export_frame = prepare_export_frame(df)

        kpis = {
            "Total Transactions": len(df),
            "Total Income": f"₹{df[df['transaction_type']=='credit']['amount'].sum():,.2f}",
            "Total Expenses": f"₹{df[df['transaction_type']=='debit']['amount'].sum():,.2f}",
            "Net": f"₹{(df[df['transaction_type']=='credit']['amount'].sum() - df[df['transaction_type']=='debit']['amount'].sum()):,.2f}",
        }

        current_month_df = df[df["date"].between(pd.Timestamp(today.replace(day=1)), pd.Timestamp(today))]
        current_month_frame = prepare_export_frame(current_month_df)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button(
                label="CSV summary",
                data=export_to_csv(export_frame),
                file_name=f"expense_summary_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                width="stretch",
            )
        with col2:
            pdf_buf = generate_pdf_report("Expense Summary Report", kpis, export_frame)
            if pdf_buf:
                st.download_button(
                    label="PDF summary",
                    data=pdf_buf,
                    file_name=f"expense_summary_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    width="stretch",
                )
            else:
                st.button("PDF summary", disabled=True, width="stretch")
        with col3:
            month_kpis = {
                "Month": date.today().strftime("%B %Y"),
                "Transactions": len(current_month_df),
                "Income": f"₹{current_month_df[current_month_df['transaction_type']=='credit']['amount'].sum():,.2f}",
                "Expense": f"₹{current_month_df[current_month_df['transaction_type']=='debit']['amount'].sum():,.2f}",
            }
            month_pdf = generate_pdf_report(f"Monthly Snapshot - {date.today().strftime('%B %Y')}", month_kpis, current_month_frame)
            if month_pdf:
                st.download_button(
                    label="Monthly PDF",
                    data=month_pdf,
                    file_name=f"monthly_snapshot_{datetime.now().strftime('%Y%m')}.pdf",
                    mime="application/pdf",
                    width="stretch",
                )
            else:
                st.button("Monthly PDF", disabled=True, width="stretch")

offsets = {"Last 7 days": 6, "Last 30 days": 29, "Last 3 months": 89}
if preset == "All time":
    dff = df
else:
    start_d = today.replace(day=1) if preset == "This month" else today - timedelta(days=offsets[preset])
    dff = df[df["date"].between(pd.Timestamp(start_d), pd.Timestamp(today))]
expenses = dff[dff["transaction_type"] == "debit"]
category_totals = expenses.groupby("category")["amount"].sum()

total_in = dff.loc[dff["transaction_type"] == "credit", "amount"].sum()
total_out = expenses["amount"].sum()
net = total_in - total_out
txn_count = len(dff)
def money(value):
    return f"₹{abs(value):,.2f}"


if preset == "All time":
    period = "All time"
else:
    period = f"{start_d.strftime('%d %b %Y')} – {today.strftime('%d %b %Y')}"
if not txn_count:
    result_label = "No transactions in this period"
elif round(net, 2) == 0:
    result_label = "You received and spent the same amount"
elif net > 0:
    result_label = "Received more than you spent"
else:
    result_label = "Spent more than you received"

st.html(f"""
    <section class="dashboard-summary" aria-label="Selected period summary">
        <div class="dashboard-result">
            <div class="dashboard-period">{period}</div>
            <strong>{money(net)}</strong>
            <div>{result_label}</div>
            <div class="dashboard-breakdown">
                <dl><dt>Money received</dt><dd><strong>{money(total_in)}</strong></dd></dl>
                <dl><dt>Money spent</dt><dd><strong>{money(total_out)}</strong></dd></dl>
                <div class="dashboard-count">{txn_count:,} {"transaction" if txn_count == 1 else "transactions"}</div>
            </div>
        </div>
    </section>
""")


def amount_bar(label, value, largest, tone, detail=""):
    fill = max(0, value / largest * 100) if largest else 0
    return f"""
        <div class="amount-bar">
            <div class="amount-bar-label">
                <span>{escape(label)}</span>
                <strong>{money(value)}{f' <small>· {detail}</small>' if detail else ''}</strong>
            </div>
            <div class="amount-bar-track" aria-hidden="true"><span class="{tone}" style="width:{min(fill, 100):.2f}%"></span></div>
        </div>
    """


incoming, spending = st.columns([1, 1.35], gap="medium")
with incoming, st.container(border=True):
    st.html('<div class="dashboard-card-heading">Money in vs. money out</div>')
    total_movement = total_in + total_out
    if total_movement > 0:
        received_share = total_in / total_movement
        spent_share = total_out / total_movement
        segments = "".join(
            f'<span class="{kind}" style="flex:{share:.8f}"></span>'
            for kind, share in (("received", received_share), ("spent", spent_share))
            if share > 0
        )
        st.html(f"""
            <div class="dashboard-mix" aria-hidden="true">{segments}</div>
            <div class="dashboard-flow-detail">
                <span><i class="dashboard-swatch received" aria-hidden="true"></i>Received<strong>{money(total_in)}</strong></span>
                <span><i class="dashboard-swatch spent" aria-hidden="true"></i>Spent<strong>{money(total_out)}</strong></span>
            </div>
        """)
    else:
        st.caption("No money received or spent in this period.")

with spending, st.container(border=True):
    st.html('<div class="dashboard-card-heading">Where you spent the most</div>')
    largest_categories = category_totals[category_totals > 0].nlargest(5)
    if largest_categories.empty:
        st.caption("No expenses in this date range.")
    else:
        biggest_category, biggest_amount = next(iter(largest_categories.items()))
        st.caption(f"{biggest_category} accounted for {biggest_amount / total_out:.0%} of what you spent.")
        remaining = total_out - largest_categories.sum()
        scale = max(biggest_amount, remaining)
        bars = [
            amount_bar(category, amount, scale, "expense", f"{amount / total_out:.0%}")
            for category, amount in largest_categories.items()
        ]
        if remaining > 0.005:
            bars.append(amount_bar("Other categories combined", remaining, scale, "muted", f"{remaining / total_out:.0%}"))
        st.html("".join(bars))

st.html('<h2 class="section-div">When money moved</h2>')
with st.container(border=True):
    flow = dff.dropna(subset=["date"])
    if flow.empty:
        st.caption("No dated transactions in this range.")
    else:
        monthly = (flow["date"].max() - flow["date"].min()).days >= 60
        periods = flow["date"].dt.to_period("M") if monthly else flow["date"].dt.to_period("D")
        totals = flow.groupby([periods, "transaction_type"])["amount"].sum().unstack(fill_value=0)
        totals = totals.reindex(columns=["credit", "debit"], fill_value=0)
        dates = totals.index.to_timestamp()
        date_format = "%b %Y" if monthly else "%d %b"
        peak_kind = "credit" if chart_mode == "Income only" or not total_out else "debit"
        if chart_mode == "Expense only":
            peak_kind = "debit"
        peak = totals[peak_kind].idxmax()
        peak_amount = totals.loc[peak, peak_kind]
        if peak_amount > 0:
            verb = "received" if peak_kind == "credit" else "spent"
            unit = "month" if monthly else "day"
            preposition = "in" if monthly else "on"
            st.caption(f"You {verb} the most in one {unit} {preposition} {peak.strftime(date_format)} ({money(peak_amount)}).")

        fig = go.Figure()
        for kind, label, color in (("credit", "Received", RECEIVED_COLOR), ("debit", "Spent", SPENT_COLOR)):
            if (kind == "credit" and chart_mode == "Expense only") or (kind == "debit" and chart_mode == "Income only"):
                continue
            fig.add_trace(go.Bar(
                x=dates, y=totals[kind], name=label, marker_color=color,
                hovertemplate=f"%{{x|{date_format}}}<br>{label}: ₹%{{y:,.2f}}<extra></extra>",
            ))
        chart_style(fig, height=265)
        fig.update_layout(barmode="group")
        fig.update_xaxes(type="date", tickformat=date_format, showgrid=False)
        fig.update_yaxes(tickprefix="₹", rangemode="tozero")
        st.plotly_chart(fig, theme=None, config={"displayModeBar": False})

st.html('<h2 class="section-div">This month and last month</h2>')
comparison = calculate_period_comparison(df, today)
comparison_cards = []
for period, label in (("this_month", "This month"), ("last_month", "Last month")):
    for kind, title in (("income", "income"), ("expense", "spent")):
        amount = comparison[period][kind]
        change = ""
        if period == "this_month":
            previous = comparison["last_month"][kind]
            pct = comparison[f"{kind}_change_pct"]
            if not previous:
                change = "No activity last month"
            elif abs(pct) < 0.5:
                change = "About the same as last month"
            else:
                change = f"{abs(pct):.0f}% {'more' if pct > 0 else 'less'} than the full prior month"
        comparison_cards.append(f"""
            <section class="comparison-card">
                <div class="comparison-label">{label} {title}</div>
                <div class="comparison-value">₹{amount:,.2f}</div>
                {f'<div class="comparison-change">{change}</div>' if change else ''}
            </section>
        """)
st.html(f'<div class="comparison-grid">{"".join(comparison_cards)}</div>')

st.html('<h2 class="section-div">This month’s category budgets</h2>')
budget_form, budget_status = st.columns(2)
with budget_form:
    with st.container(border=True):
        categories = sorted(df.loc[df["transaction_type"] == "debit", "category"].unique())
        cat_for_budget = st.selectbox("Category", categories, key="cat_budget")
        budget_amount = st.number_input("Budget amount (₹)", min_value=1, step=100, key="budget_amt")
        if st.button("Set budget", key="set_budget_btn", disabled=not cat_for_budget):
            set_monthly_budget(budget_month, cat_for_budget, budget_amount)
            st.toast(f"Budget set for {cat_for_budget}.")
with budget_status:
    with st.container(border=True):
        st.html('<div class="chart-card-title">Budget status</div>')
        budgets = monthly_budgets(budget_month)
        month_expenses = df[(df["transaction_type"] == "debit") & df["date"].between(
            pd.Timestamp(today.replace(day=1)), pd.Timestamp(today))]
        monthly_totals = month_expenses.groupby("category")["amount"].sum()
        for category, budget in budgets.items():
            spent = monthly_totals.get(category, 0)
            progress = budget_progress(spent, budget)
            pct = progress["percent"]
            status = progress["status"].split(" ", 1)[1]
            st.html(f"""
                <div class="budget-row">
                    <div class="budget-label"><span>{escape(category)}</span><span>{status} · {pct:.0f}% used</span></div>
                    <progress aria-label="{escape(category)} budget used" value="{max(0, min(pct, 100))}" max="100"></progress>
                    <small>₹{spent:,.2f} / ₹{budget:,.2f}</small>
                </div>
            """)
        if not budgets:
            st.caption("No budgets set yet.")

# ── Transaction table (original logic unchanged) ──────────────────────────────
st.html('<h2 class="section-div">Transaction log</h2>')

sc1, sc2, sc3 = st.columns([2.2, 1, 1])
with sc1:
    st.session_state.setdefault("dash_search", "")
    search = st.text_input("Search transactions", placeholder="Search notes or categories", key="dash_search")
with sc2:
    st.session_state.setdefault("dash_type_filter", "all")
    type_filter = st.selectbox("Type", ["all", "debit", "credit"], format_func={"all": "All types", "debit": "Expenses", "credit": "Income"}.get, key="dash_type_filter")
with sc3:
    cats = ["all categories"] + sorted(set(ALL_CATEGORIES).union(df["category"]))
    st.session_state.setdefault("dash_cat_filter", "all categories")
    cat_filter = st.selectbox("Category", cats, format_func=lambda value: value.capitalize() if value == "all categories" else value, key="dash_cat_filter")

tdf = dff.copy()
if search:
    mask = tdf["note"].str.contains(search, case=False, na=False, regex=False) | tdf["category"].str.contains(search, case=False, na=False, regex=False)
    tdf = tdf[mask]
if type_filter != "all":
    tdf = tdf[tdf["transaction_type"] == type_filter]
if cat_filter != "all categories":
    tdf = tdf[tdf["category"] == cat_filter]

display = tdf[["id","transaction_type","date","amount","category","note"]].copy()
display = display.sort_values("date", ascending=False)
display["date"] = display["date"].dt.strftime("%d %b %Y").fillna(tdf["recorded_date"])
display["amount"] = display.apply(
    lambda r: f"+₹{r['amount']:,.2f}" if r["transaction_type"]=="credit" else f"-₹{r['amount']:,.2f}", axis=1
)
display["transaction_type"] = display["transaction_type"].replace({"credit": "Received", "debit": "Spent"})
display.columns = ["ID","Type","Date","Amount","Category","Note"]

st.dataframe(display.set_index("ID"), width="stretch", height=300)

with st.expander("Manage transactions"):
    id_col, delete_col = st.columns([2, 1], vertical_alignment="bottom")
    del_id = id_col.number_input("Transaction ID", min_value=0, step=1)
    if delete_col.button("Delete entry", key="del", disabled=not del_id):
        try:
            row = delete_expense(int(del_id))
        except ValueError as exc:
            st.warning(str(exc))
            st.stop()
        if row:
            set_dash_undo("delete", {"row": row}, f"Deleted #{int(del_id)}")
            st.rerun()
        st.warning(f"No transaction found with ID {int(del_id)}.")
    with st.form("move_expense_to_repayments"):
        st.markdown("**Was an unpaid amount saved as an expense?**")
        correction_id = st.number_input("Expense ID to correct", min_value=1, step=1, key="repayment_correction_id")
        row = get_expense_by_id(correction_id)
        if row:
            st.text(f"#{row['id']} · ₹{row['amount']:,.2f} · {row['note']}")
        direction = st.radio("What is still pending?", ["They owe me", "I owe them"], horizontal=True,
                             key="repayment_correction_direction")
        person = st.text_input("Person's name", key="repayment_correction_person")
        if st.form_submit_button("Move to Repayments"):
            try:
                payload = move_expense_to_repayments(correction_id, "collect" if direction == "They owe me" else "pay", person)
            except (ValueError, sqlite3.Error) as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else "Could not correct the entry. Try again.")
            else:
                set_dash_undo("move_to_repayments", payload, "Moved the unpaid amount to Repayments")
                st.rerun()
