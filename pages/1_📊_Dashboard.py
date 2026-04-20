"""
pages/1_📊_Dashboard.py — Analytics Dashboard
UI: Clean fintech aesthetic
Logic: unchanged — chart modes, session state filters, reset all, delete
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta, datetime
import sys, os
from io import BytesIO, StringIO
import csv
import json

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import (
    init_db,
    get_all_expenses,
    get_all_expenses_rows,
    get_category_totals,
    get_daily_totals,
    get_monthly_totals,
    get_summary_stats,
    delete_expense,
    delete_all_expenses,
    get_expense_by_id,
    insert_expense_row,
    insert_expense_rows,
)

st.set_page_config(page_title="Dashboard · Enma", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 0 2rem 2.5rem 2rem !important; max-width: 1320px; }
.stApp { background: #F2F0EB; }

/* ── Top nav ── */
.topnav {
    display: flex; align-items: center; justify-content: space-between;
    padding: 26px 0 20px 0;
    border-bottom: 1px solid #e4e0d8;
    margin-bottom: 24px;
}
.nav-brand { display: flex; align-items: center; gap: 10px; }
.nav-icon {
    width: 34px; height: 34px;
    background: linear-gradient(135deg, #7c3aed, #6366f1);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center; font-size: 15px;
}
.nav-name {
    font-family: 'Outfit', sans-serif;
    font-size: 1.05rem; font-weight: 700; color: #141416; letter-spacing: -0.02em;
}
.nav-page { font-size: 0.7rem; color: #a09890; }

/* ── Section dividers ── */
.section-div {
    font-size: 0.65rem; color: #b0a89e;
    text-transform: uppercase; letter-spacing: 0.1em;
    margin: 26px 0 14px 0;
    display: flex; align-items: center; gap: 10px;
}
.section-div::after { content:''; flex:1; height:1px; background:#e4e0d8; }

/* ── KPI cards ── */
.kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 6px; }
.kpi {
    background: #fff; border: 1px solid #ede9e2;
    border-radius: 16px; padding: 20px 22px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    transition: box-shadow 0.2s, transform 0.2s;
}
.kpi:hover { box-shadow: 0 6px 20px rgba(0,0,0,0.07); transform: translateY(-1px); }
.kpi-lbl {
    font-size: 0.62rem; color: #b0a89e;
    text-transform: uppercase; letter-spacing: 0.09em; margin-bottom: 10px;
}
.kpi-val {
    font-family: 'Outfit', sans-serif;
    font-size: 1.65rem; font-weight: 800;
    letter-spacing: -0.04em; line-height: 1;
}
.kpi-sub { font-size: 0.67rem; color: #c8c0b4; margin-top: 6px; }
.green  { color: #16a34a; }
.red    { color: #dc2626; }
.yellow { color: #d97706; }
.blue   { color: #4f46e5; }
.white  { color: #1c1c1e; }

/* ── Chart card wrapper ── */
.chart-card {
    background: #fff; border: 1px solid #ede9e2;
    border-radius: 16px; padding: 20px 22px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.chart-card-title {
    font-family: 'Outfit', sans-serif;
    font-size: 0.9rem; font-weight: 600; color: #1c1c1e;
    letter-spacing: -0.01em; margin-bottom: 2px;
}
.chart-card-sub { font-size: 0.7rem; color: #c0b8ae; margin-bottom: 14px; }

/* ── Filter bar ── */
.filter-bar {
    display: flex; align-items: center; gap: 10px;
    background: #fff; border: 1px solid #ede9e2;
    border-radius: 14px; padding: 10px 16px;
    margin-bottom: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}
.filter-label { font-size: 0.68rem; color: #b0a89e; white-space: nowrap; }

/* ── Table ── */
[data-testid="stDataFrame"] {
    border: 1px solid #ede9e2 !important;
    border-radius: 14px !important;
    overflow: hidden !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;
}
[data-testid="stDataFrame"] * { font-family: 'DM Sans', sans-serif !important; font-size: 0.8rem !important; }
[data-testid="stDataFrame"] [role="columnheader"] { background: #f8f5f0 !important; color: #706860 !important; font-weight: 600 !important; }
[data-testid="stDataFrame"] [role="row"]:nth-child(even) { background: #faf8f4 !important; }

/* ── Inputs ── */
.stTextInput > div > div > input {
    background: #fff !important; border: 1.5px solid #e4e0d8 !important;
    border-radius: 11px !important; color: #1c1c1e !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.86rem !important; padding: 10px 14px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03) !important;
}
.stTextInput > div > div > input:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.09) !important;
}
.stSelectbox > div > div {
    background: #fff !important; border: 1.5px solid #e4e0d8 !important;
    border-radius: 11px !important; color: #1c1c1e !important;
    font-family: 'DM Sans', sans-serif !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03) !important;
}
.stButton > button {
    background: #1c1c1e !important; color: #fff !important;
    border: none !important; border-radius: 11px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.82rem !important; font-weight: 600 !important;
    padding: 10px 20px !important; transition: all 0.15s !important;
}
.stButton > button:hover {
    background: #6366f1 !important;
    box-shadow: 0 6px 16px rgba(99,102,241,0.22) !important;
    transform: translateY(-1px);
}
.st-key-reset_all_transactions button,
.st-key-dash_reset_filters button,
.st-key-export_toggle button,
.st-key-back button,
.st-key-dash_theme_toggle button {
    white-space: nowrap !important;
    word-break: keep-all !important;
}
.stNumberInput > div > div > input {
    background: #fff !important; border: 1.5px solid #e4e0d8 !important;
    border-radius: 11px !important; color: #1c1c1e !important;
    font-family: 'DM Sans', sans-serif !important; font-size: 0.86rem !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03) !important;
}

/* empty state */
.empty-state {
    text-align: center; padding: 80px 20px;
}
.empty-state-icon { font-size: 2.5rem; margin-bottom: 14px; }
.empty-state-title {
    font-family: 'Outfit', sans-serif;
    font-size: 1.2rem; font-weight: 700; color: #1c1c1e; margin-bottom: 6px;
}
.empty-state-sub { font-size: 0.82rem; color: #b0a89e; }
</style>
""", unsafe_allow_html=True)

init_db()

# ── Theme setup ──────────────────────────────────────────────────────────────
if "theme" not in st.session_state:
    st.session_state.theme = "dark"

def toggle_theme():
    st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"

# Apply theme CSS
theme = st.session_state.theme
if theme == "dark":
    st.markdown("""
    <style>
    :root {
        --bg-primary: #12131a;
        --bg-card: #1a1d27;
        --text-primary: #eceff8;
        --text-secondary: #a7b0c4;
        --border-light: #2b3242;
        --grid-color: #2b3242;
        --axis-color: #9aa4bb;
        --button-bg: #2b3242;
        --button-hover: #3b4660;
    }
    .stApp { background: var(--bg-primary); color: var(--text-primary); }
    .block-container,
    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] span,
    [data-testid="stMarkdownContainer"] li,
    .stCaption,
    label,
    .stSelectbox label,
    .stTextInput label,
    .stNumberInput label {
        color: var(--text-primary) !important;
    }
    .stCaption,
    .nav-page,
    .section-div,
    .kpi-lbl,
    .kpi-sub,
    .chart-card-sub,
    .empty-state-sub {
        color: var(--text-secondary) !important;
    }
    div[data-baseweb="select"] > div {
        background: #161a25 !important;
        color: #e6ebf7 !important;
        border-color: var(--border-light) !important;
    }
    div[data-baseweb="select"] input {
        color: #e6ebf7 !important;
    }
    .streamlit-expanderHeader {
        color: var(--text-primary) !important;
    }
    .topnav { border-bottom-color: var(--border-light); }
    .nav-name, .chart-card-title, .empty-state-title, .kpi-val { color: var(--text-primary) !important; }
    .section-div::after { background: var(--border-light) !important; }
    .kpi, .chart-card, [data-testid="stDataFrame"] { background: var(--bg-card) !important; border-color: var(--border-light) !important; }
    [data-testid="stDataFrame"] [role="columnheader"] { background: #222838 !important; color: #ced5e6 !important; }
    [data-testid="stDataFrame"] [role="row"] { background: #1a1d27 !important; }
    [data-testid="stDataFrame"] [role="row"] * { color: #e6ebf7 !important; }
    [data-testid="stDataFrame"] [role="row"]:nth-child(even) { background: #202536 !important; }
    .stTextInput > div > div > input,
    .stSelectbox > div > div,
    .stNumberInput > div > div > input {
        background: #161a25 !important;
        color: #e6ebf7 !important;
        border-color: var(--border-light) !important;
    }
    .stButton > button,
    .stDownloadButton > button {
        background: var(--button-bg) !important;
        color: #f4f7ff !important;
        border: 1px solid #4a5776 !important;
    }
    .stButton > button:hover,
    .stDownloadButton > button:hover {
        background: var(--button-hover) !important;
        border-color: #64759a !important;
        box-shadow: 0 6px 16px rgba(0,0,0,0.35) !important;
    }
    .st-key-reset_all_transactions button,
    .st-key-dash_reset_filters button,
    .st-key-export_toggle button,
    .st-key-back button,
    .st-key-dash_theme_toggle button {
        background: var(--button-bg) !important;
        color: #f4f7ff !important;
        border: 1px solid #4a5776 !important;
    }
    .st-key-reset_all_transactions button:hover,
    .st-key-dash_reset_filters button:hover,
    .st-key-export_toggle button:hover,
    .st-key-back button:hover,
    .st-key-dash_theme_toggle button:hover {
        background: var(--button-hover) !important;
        border-color: #64759a !important;
    }
    .st-key-dash_theme_toggle button {
        background: linear-gradient(135deg, #7c3aed, #6366f1) !important;
        color: #f8faff !important;
        border: 1px solid #8b85ff !important;
    }
    .st-key-dash_theme_toggle button:hover {
        background: linear-gradient(135deg, #8b5cf6, #4f46e5) !important;
        border-color: #aba7ff !important;
        box-shadow: 0 10px 22px rgba(99,102,241,0.38) !important;
    }
    .stButton > button:disabled,
    .stDownloadButton > button:disabled {
        background: #242a38 !important;
        color: #8e9ab7 !important;
        border: 1px solid #343e55 !important;
        opacity: 1 !important;
    }
    @media (max-width: 900px) {
        .block-container { padding: 0 0.8rem 1.4rem 0.8rem !important; }
        .kpi-grid { grid-template-columns: repeat(2, 1fr) !important; }
        .chart-card { padding: 14px 14px !important; }
        .stButton > button {
            min-height: 42px !important;
            padding: 10px 12px !important;
            font-size: 0.76rem !important;
        }
        [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 0.6rem !important; }
        [data-testid="stHorizontalBlock"] > [data-testid="column"] {
            min-width: 100% !important;
            flex: 1 1 100% !important;
        }
    }
    @media (max-width: 560px) {
        .kpi-grid { grid-template-columns: 1fr !important; }
    }
    </style>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <style>
    :root {
        --bg-primary: #FFFFFF;
        --bg-card: #ffffff;
        --text-primary: #1a1a1a;
        --text-secondary: #5d6578;
        --border-light: #e0e0e0;
        --grid-color: #edf1f8;
        --axis-color: #7a8498;
        --button-bg: #1c1c1e;
        --button-hover: #3d4456;
    }
    .stApp { background: var(--bg-primary); color: var(--text-primary); }
    .kpi, .chart-card, [data-testid="stDataFrame"] { background: var(--bg-card) !important; border-color: var(--border-light) !important; }
    .nav-page, .section-div, .kpi-lbl, .kpi-sub, .chart-card-sub, .empty-state-sub { color: var(--text-secondary) !important; }
    @media (max-width: 900px) {
        .block-container { padding: 0 0.8rem 1.4rem 0.8rem !important; }
        .kpi-grid { grid-template-columns: repeat(2, 1fr) !important; }
        .chart-card { padding: 14px 14px !important; }
        [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 0.6rem !important; }
        [data-testid="stHorizontalBlock"] > [data-testid="column"] {
            min-width: 100% !important;
            flex: 1 1 100% !important;
        }
    }
    @media (max-width: 560px) {
        .kpi-grid { grid-template-columns: 1fr !important; }
    }
    </style>
    """, unsafe_allow_html=True)

# ── Chart colours (warm palette to match bg) ──────────────────────────────────
GREEN   = "#16a34a"
RED     = "#dc2626"
INDIGO  = "#6366f1"
AMBER   = "#d97706"
PALETTE = ["#6366f1","#16a34a","#d97706","#dc2626","#8b5cf6",
           "#0891b2","#65a30d","#db2777","#0d9488","#ea580c",
           "#7c3aed","#15803d","#b45309"]
if theme == "dark":
    BG_CHART = "rgba(0,0,0,0)"
    GRID_C   = "#2b3242"
    TEXT_C   = "#9aa4bb"
    CHART_EDGE = "#1a1d27"
    LEGEND_BG = "rgba(26,29,39,0.92)"
    LEGEND_TEXT = "#d4dbec"
    LEGEND_BORDER = "#2b3242"
else:
    BG_CHART = "rgba(0,0,0,0)"
    GRID_C   = "#f0ece5"
    TEXT_C   = "#b0a89e"
    CHART_EDGE = "#F2F0EB"
    LEGEND_BG = "rgba(255,255,255,0.7)"
    LEGEND_TEXT = "#706860"
    LEGEND_BORDER = "#ede9e2"


def chart_style(fig, height=260):
    fig.update_layout(
        paper_bgcolor=BG_CHART, plot_bgcolor=BG_CHART,
        font=dict(family="DM Sans, sans-serif", color=TEXT_C, size=11),
        title=dict(text=""),
        margin=dict(l=18, r=42, t=12, b=42),
        height=height,
        hovermode="x unified",
        legend=dict(
            bgcolor=LEGEND_BG,
            font=dict(color=LEGEND_TEXT, size=10),
            bordercolor=LEGEND_BORDER, borderwidth=1,
            orientation="h", y=-0.2,
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

def prompt_reset_all_transactions():
    st.session_state.confirm_reset_all = True


def toggle_export_panel():
    st.session_state.export_panel = not st.session_state.get("export_panel", False)


def set_dash_undo(action_type, payload, label):
    st.session_state.dash_undo_action = {
        "type": action_type,
        "payload": payload,
        "label": label,
        "expires_at": datetime.now() + timedelta(seconds=8),
    }
    st.toast(f"{label}. Undo available for 8s.", icon="↩️")

def confirm_reset_all_transactions():
    snapshot = get_all_expenses_rows()
    delete_all_expenses()
    if snapshot:
        set_dash_undo("reset", {"rows": snapshot}, "Reset all transactions")
    reset_dashboard_filters()
    st.session_state.confirm_reset_all = False

def cancel_reset_all_transactions():
    st.session_state.confirm_reset_all = False


# ── Budget & Export helpers ────────────────────────────────────────────────────
def get_category_budgets():
    """Load budgets from session or initialize empty dict"""
    if "budgets" not in st.session_state:
        st.session_state.budgets = {}
    return st.session_state.budgets


def set_category_budget(category, amount):
    """Save a budget for a category"""
    if "budgets" not in st.session_state:
        st.session_state.budgets = {}
    st.session_state.budgets[category] = amount


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


# ── Top nav ───────────────────────────────────────────────────────────────────
nc1, nc2 = st.columns([5, 1])
with nc1:
    st.markdown("""
    <div class="topnav">
      <div class="nav-brand">
        <div class="nav-icon">📈</div>
        <div>
          <div class="nav-name">Enma</div>
          <div class="nav-page">Analytics Dashboard</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
with nc2:
    col_t, col_b = st.columns(2)
    with col_t:
        if st.button("← Back", key="back"):
            st.switch_page("app.py")
    with col_b:
        theme_icon = "🌙" if st.session_state.theme == "dark" else "☀️"
        if st.button(theme_icon, key="dash_theme_toggle", help="Toggle light/dark mode"):
            toggle_theme()
            st.rerun()

# ── Actions row (reset all — original logic unchanged) ────────────────────────
st.session_state.setdefault("confirm_reset_all", False)
st.session_state.setdefault("dash_undo_action", None)
st.session_state.setdefault("selected_category", None)
st.session_state.setdefault("budgets", {})
st.session_state.setdefault("export_panel", False)
actions_left, actions_right = st.columns([6, 2])

with actions_left:
    undo_state = st.session_state.get("dash_undo_action")
    if undo_state:
        if datetime.now() < undo_state["expires_at"]:
            st.markdown(f'<div style="color:#706860;font-size:0.74rem;background:#fff;border:1px solid #ede9e2;padding:8px 12px;border-radius:10px;display:inline-block">{undo_state["label"]} · Undo available</div>', unsafe_allow_html=True)
            u1, u2, _ = st.columns([1, 1, 6])
            with u1:
                if st.button("Undo", key="dash_undo"):
                    if undo_state["type"] == "delete":
                        row = undo_state["payload"].get("row")
                        if row:
                            insert_expense_row(row)
                    elif undo_state["type"] == "reset":
                        rows = undo_state["payload"].get("rows", [])
                        if rows:
                            insert_expense_rows(rows)
                    st.session_state.dash_undo_action = None
                    st.rerun()
            with u2:
                if st.button("Dismiss", key="dash_undo_dismiss"):
                    st.session_state.dash_undo_action = None
                    st.rerun()
        else:
            st.session_state.dash_undo_action = None

with actions_right:
    if not st.session_state.confirm_reset_all:
        exp_col, reset_col = st.columns(2)
        with exp_col:
            st.button("📥 Export", key="export_toggle", on_click=toggle_export_panel)
        with reset_col:
            st.button("Reset all", key="reset_all_transactions", on_click=prompt_reset_all_transactions, help="Delete all transactions")
    else:
        st.markdown('<div style="color:#b91c1c;font-size:0.74rem;margin-bottom:6px;background:#fff5f5;padding:8px 12px;border-radius:10px;border:1px solid #fecaca">Delete every transaction permanently?</div>', unsafe_allow_html=True)
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            st.button("Yes, delete all", key="confirm_reset_all_transactions", on_click=confirm_reset_all_transactions)
        with cancel_col:
            st.button("Cancel", key="cancel_reset_all_transactions", on_click=cancel_reset_all_transactions)

# ── Load data ─────────────────────────────────────────────────────────────────
all_rows = get_all_expenses()
if not all_rows:
    st.markdown("""
    <div class="empty-state">
      <div class="empty-state-icon">📭</div>
      <div class="empty-state-title">No transactions yet</div>
      <div class="empty-state-sub">Add a few entries in chat to unlock the dashboard.</div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── Export dialog ─────────────────────────────────────────────────────────────
if st.session_state.get("export_panel"):
    with st.expander("📥 Export Report", expanded=True):
        df_export = pd.DataFrame(all_rows, columns=["id","amount","category","transaction_type","date","note","raw_input","created_at"])
        export_frame = df_export[["date","transaction_type","category","amount","note"]].copy()
        export_frame["date"] = pd.to_datetime(export_frame["date"]).dt.strftime("%d %b %Y")

        kpis = {
            "Total Transactions": len(df_export),
            "Total Income": f"₹{df_export[df_export['transaction_type']=='credit']['amount'].sum():,.0f}",
            "Total Expenses": f"₹{df_export[df_export['transaction_type']=='debit']['amount'].sum():,.0f}",
            "Net": f"₹{(df_export[df_export['transaction_type']=='credit']['amount'].sum() - df_export[df_export['transaction_type']=='debit']['amount'].sum()):,.0f}",
        }

        current_month = date.today().replace(day=1)
        current_month_df = df_export[pd.to_datetime(df_export["date"]).dt.date >= current_month]
        current_month_frame = current_month_df[["date","transaction_type","category","amount","note"]].copy()
        current_month_frame["date"] = pd.to_datetime(current_month_frame["date"]).dt.strftime("%d %b %Y")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button(
                label="📄 CSV Summary",
                data=export_to_csv(export_frame),
                file_name=f"expense_summary_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with col2:
            pdf_buf = generate_pdf_report("Expense Summary Report", kpis, export_frame)
            if pdf_buf:
                st.download_button(
                    label="📕 PDF Summary",
                    data=pdf_buf,
                    file_name=f"expense_summary_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            else:
                st.button("📕 PDF Summary", disabled=True, use_container_width=True)
        with col3:
            month_kpis = {
                "Month": date.today().strftime("%B %Y"),
                "Transactions": len(current_month_df),
                "Income": f"₹{current_month_df[current_month_df['transaction_type']=='credit']['amount'].sum():,.0f}",
                "Expense": f"₹{current_month_df[current_month_df['transaction_type']=='debit']['amount'].sum():,.0f}",
            }
            month_pdf = generate_pdf_report(f"Monthly Snapshot - {date.today().strftime('%B %Y')}", month_kpis, current_month_frame)
            if month_pdf:
                st.download_button(
                    label="🗓️ Monthly Snapshot PDF",
                    data=month_pdf,
                    file_name=f"monthly_snapshot_{datetime.now().strftime('%Y%m')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            else:
                st.button("🗓️ Monthly Snapshot PDF", disabled=True, use_container_width=True)

df = pd.DataFrame(all_rows, columns=["id","amount","category","transaction_type","date","note","raw_input","created_at"])
df["date"]   = pd.to_datetime(df["date"])
df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)

# ── Filters (original session-state logic unchanged) ─────────────────────────
fc1, fc2, fc3 = st.columns([1.6, 1.6, 1])
with fc1:
    st.session_state.setdefault("dash_preset", "Last 30 days")
    preset = st.selectbox("Time preset", ["Last 30 days","Last 7 days","This month","Last 3 months","All time"],
                          key="dash_preset", label_visibility="collapsed")
with fc2:
    st.session_state.setdefault("dash_chart_mode", "Overview")
    chart_mode = st.selectbox("Chart Mode", ["Overview","Credit vs Debit","Income only","Expense only"],
                              key="dash_chart_mode", label_visibility="collapsed")
with fc3:
    st.button("Reset filters", key="dash_reset_filters", on_click=reset_dashboard_filters)

today = date.today()
offsets = {"Last 7 days":7,"Last 30 days":30,"Last 3 months":90}
if preset in offsets:
    start_d = today - timedelta(days=offsets[preset])
elif preset == "This month":
    start_d = today.replace(day=1)
else:
    start_d = date(2020,1,1)

dff = df[(df["date"] >= pd.Timestamp(start_d)) & (df["date"] <= pd.Timestamp(today))]

# ── KPI cards (original data, new style) ──────────────────────────────────────
total_in  = dff[dff["transaction_type"]=="credit"]["amount"].sum()
total_out = dff[dff["transaction_type"]=="debit"]["amount"].sum()
net       = total_in - total_out
txn_count = len(dff)
net_color = "green" if net >= 0 else "red"
sign      = "+" if net >= 0 else ""
top_cat   = dff[dff["transaction_type"]=="debit"].groupby("category")["amount"].sum().idxmax() \
            if not dff[dff["transaction_type"]=="debit"].empty else "—"

st.markdown('<div class="section-div">Overview</div>', unsafe_allow_html=True)
st.markdown(f"""
<div class="kpi-grid">
    <div class="kpi">
        <div class="kpi-lbl">Net Balance</div>
        <div class="kpi-val {net_color}">{sign}₹{abs(net):,.0f}</div>
        <div class="kpi-sub">income − expenses</div>
    </div>
    <div class="kpi">
        <div class="kpi-lbl">Total Income</div>
        <div class="kpi-val green">₹{total_in:,.0f}</div>
        <div class="kpi-sub">credits in period</div>
    </div>
    <div class="kpi">
        <div class="kpi-lbl">Total Spent</div>
        <div class="kpi-val red">₹{total_out:,.0f}</div>
        <div class="kpi-sub">debits in period</div>
    </div>
    <div class="kpi">
        <div class="kpi-lbl">Transactions</div>
        <div class="kpi-val blue">{txn_count}</div>
        <div class="kpi-sub">in selected period</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Period comparison (This month vs last month) ───────────────────────────────
st.markdown('<div class="section-div">Period Comparison</div>', unsafe_allow_html=True)
today = date.today()
this_month_start = today.replace(day=1)
last_month_end = this_month_start - timedelta(days=1)
last_month_start = last_month_end.replace(day=1)

df_this_month = df[(df["date"] >= pd.Timestamp(this_month_start)) & (df["date"] <= pd.Timestamp(today))]
df_last_month = df[(df["date"] >= pd.Timestamp(last_month_start)) & (df["date"] <= pd.Timestamp(last_month_end))]

this_in = df_this_month[df_this_month["transaction_type"]=="credit"]["amount"].sum()
this_out = df_this_month[df_this_month["transaction_type"]=="debit"]["amount"].sum()
last_in = df_last_month[df_last_month["transaction_type"]=="credit"]["amount"].sum()
last_out = df_last_month[df_last_month["transaction_type"]=="debit"]["amount"].sum()

pct_in_change = ((this_in - last_in) / max(last_in, 1)) * 100
pct_out_change = ((this_out - last_out) / max(last_out, 1)) * 100
in_arrow = "📈" if pct_in_change >= 0 else "📉"
out_arrow = "📈" if pct_out_change >= 0 else "📉"

comp_col1, comp_col2, comp_col3, comp_col4 = st.columns(4)
with comp_col1:
    st.markdown(f"""
    <div style="background:#fff;border:1px solid #ede9e2;border-radius:12px;padding:16px;text-align:center">
        <div style="font-size:0.7rem;color:#b0a89e;margin-bottom:6px">THIS MONTH INCOME</div>
        <div style="font-size:1.4rem;font-weight:700;color:#16a34a">₹{this_in:,.0f}</div>
        <div style="font-size:0.68rem;color:#706860;margin-top:4px">{in_arrow} {abs(pct_in_change):.0f}% vs last month</div>
    </div>
    """, unsafe_allow_html=True)
with comp_col2:
    st.markdown(f"""
    <div style="background:#fff;border:1px solid #ede9e2;border-radius:12px;padding:16px;text-align:center">
        <div style="font-size:0.7rem;color:#b0a89e;margin-bottom:6px">THIS MONTH EXPENSES</div>
        <div style="font-size:1.4rem;font-weight:700;color:#dc2626">₹{this_out:,.0f}</div>
        <div style="font-size:0.68rem;color:#706860;margin-top:4px">{out_arrow} {abs(pct_out_change):.0f}% vs last month</div>
    </div>
    """, unsafe_allow_html=True)
with comp_col3:
    st.markdown(f"""
    <div style="background:#fff;border:1px solid #ede9e2;border-radius:12px;padding:16px;text-align:center">
        <div style="font-size:0.7rem;color:#b0a89e;margin-bottom:6px">LAST MONTH INCOME</div>
        <div style="font-size:1.4rem;font-weight:700;color:#16a34a">₹{last_in:,.0f}</div>
    </div>
    """, unsafe_allow_html=True)
with comp_col4:
    st.markdown(f"""
    <div style="background:#fff;border:1px solid #ede9e2;border-radius:12px;padding:16px;text-align:center">
        <div style="font-size:0.7rem;color:#b0a89e;margin-bottom:6px">LAST MONTH EXPENSES</div>
        <div style="font-size:1.4rem;font-weight:700;color:#dc2626">₹{last_out:,.0f}</div>
    </div>
    """, unsafe_allow_html=True)

# ── Charts row 1 (original chart_mode logic unchanged) ───────────────────────

# ── Budget tracking ────────────────────────────────────────────────────────────
st.markdown('<div class="section-div">Budget Tracking</div>', unsafe_allow_html=True)
st.markdown("💡 Set budgets for categories to track spending. Alerts show when nearing limit.", unsafe_allow_html=True)

budget_cols = st.columns(2)
with budget_cols[0]:
    st.markdown("**Set Category Budget**")
    cat_for_budget = st.selectbox("Category", sorted(dff["category"].unique().tolist()), key="cat_budget", label_visibility="collapsed")
    budget_amount = st.number_input("Budget amount (₹)", min_value=0, step=100, key="budget_amt", label_visibility="collapsed")
    if st.button("Set Budget", key="set_budget_btn"):
        set_category_budget(cat_for_budget, budget_amount)
        st.success(f"✓ Budget set for {cat_for_budget}: ₹{budget_amount:,.0f}")

with budget_cols[1]:
    st.markdown("**Budget Status**")
    budgets = get_category_budgets()
    if budgets:
        cat_exp = dff[dff["transaction_type"]=="debit"].groupby("category")["amount"].sum()
        for cat, budget in budgets.items():
            spent = cat_exp.get(cat, 0)
            pct = (spent / max(budget, 1)) * 100
            
            # Color based on usage
            if pct >= 100:
                bar_color = "#dc2626"  # red
                status = "❌ Over budget"
            elif pct >= 80:
                bar_color = "#d97706"  # orange
                status = "⚠️ Near limit"
            else:
                bar_color = "#16a34a"  # green
                status = "✓ On track"
            
            st.markdown(f"""
            <div style="margin-bottom:12px">
                <div style="font-size:0.75rem;color:#706860;margin-bottom:4px;display:flex;justify-content:space-between">
                    <span>{cat}</span>
                    <span>{status}</span>
                </div>
                <div style="width:100%;height:8px;background:#e4e0d8;border-radius:4px;overflow:hidden">
                    <div style="width:{min(pct, 100)}%;height:100%;background:{bar_color};transition:width 0.3s"></div>
                </div>
                <div style="font-size:0.65rem;color:#b0a89e;margin-top:2px">₹{spent:,.0f} / ₹{budget:,.0f} ({pct:.0f}%)</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.caption("No budgets set yet. Set one above!")
st.markdown('<div class="section-div">Cashflow over time</div>', unsafe_allow_html=True)
c1, c2 = st.columns([3, 1], gap="medium")

with c1:
    st.markdown('<div class="chart-card">', unsafe_allow_html=True)
    st.markdown('<div class="chart-card-title">Daily Cashflow</div><div class="chart-card-sub">Income and expenses day by day</div>', unsafe_allow_html=True)
    daily_rows = get_daily_totals()
    if daily_rows:
        dd = pd.DataFrame(daily_rows, columns=["date","debit","credit"])
        dd["date"] = pd.to_datetime(dd["date"])
        dd = dd[(dd["date"] >= pd.Timestamp(start_d)) & (dd["date"] <= pd.Timestamp(today))]
        if not dd.empty:
            dd = dd.sort_values("date")
            dd["date_label"] = dd["date"].dt.strftime("%d %b")
            fig = go.Figure()
            if chart_mode in ("Overview", "Credit vs Debit", "Income only"):
                fig.add_trace(go.Scatter(
                    x=dd["date_label"], y=dd["credit"], name="Income",
                    line=dict(color=GREEN, width=3, shape="spline"),
                    marker=dict(size=6, color=GREEN),
                    fill="tozeroy", fillcolor="rgba(22,163,74,0.07)",
                    hovertemplate="<b>%{x}</b><br>+₹%{y:,.0f}<extra></extra>",
                    mode="lines+markers",
                ))
            if chart_mode in ("Overview", "Credit vs Debit", "Expense only"):
                fig.add_trace(go.Scatter(
                    x=dd["date_label"], y=dd["debit"], name="Expense",
                    line=dict(color=RED, width=3, shape="spline"),
                    marker=dict(size=6, color=RED),
                    fill="tozeroy", fillcolor="rgba(220,38,38,0.07)",
                    hovertemplate="<b>%{x}</b><br>-₹%{y:,.0f}<extra></extra>",
                    mode="lines+markers",
                ))
            chart_style(fig, height=300)
            fig.update_layout(
                xaxis_title=None,
                yaxis_title=None,
                hovermode="x unified",
            )
            fig.update_xaxes(type="category")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown('<div style="color:#b0a89e;font-size:0.78rem;padding:24px 0;text-align:center">No daily transactions in the selected range.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="color:#b0a89e;font-size:0.78rem;padding:24px 0;text-align:center">No daily transactions yet.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with c2:
    st.markdown('<div class="chart-card">', unsafe_allow_html=True)
    st.markdown('<div class="chart-card-title">Split</div><div class="chart-card-sub">Income vs Expense ratio</div>', unsafe_allow_html=True)
    if txn_count > 0 and chart_mode in ("Overview", "Credit vs Debit"):
        fig2 = go.Figure(go.Pie(
            labels=["Income","Expense"],
            values=[max(total_in, 0.01), max(total_out, 0.01)],
            hole=0.65,
            marker=dict(colors=[GREEN, RED], line=dict(color=CHART_EDGE, width=3)),
            textinfo="percent",
            textfont=dict(size=10, color=TEXT_C),
            hovertemplate="<b>%{label}</b><br>₹%{value:,.0f}<extra></extra>",
        ))
        chart_style(fig2, height=240)
        fig2.update_layout(
            showlegend=True,
            legend=dict(orientation="h", y=-0.08, x=0.5, xanchor="center"),
            annotations=[dict(
                text=f"{'↑' if net>=0 else '↓'}₹{abs(net):,.0f}",
                x=0.5, y=0.5,
                font=dict(size=12, color=GREEN if net>=0 else RED, family="Outfit"),
                showarrow=False,
            )],
        )
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
    elif txn_count > 0:
        st.markdown('<div style="color:#b0a89e;font-size:0.78rem;padding:20px 0;text-align:center">Select "Credit vs Debit" to see the breakdown.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ── Charts row 2 (original chart_mode logic unchanged) ───────────────────────
st.markdown('<div class="section-div">Monthly breakdown</div>', unsafe_allow_html=True)
m1, m2 = st.columns(2, gap="medium")

with m1:
    st.markdown('<div class="chart-card">', unsafe_allow_html=True)
    st.markdown('<div class="chart-card-title">Monthly Overview</div><div class="chart-card-sub">Income vs expenses by month</div>', unsafe_allow_html=True)
    monthly = get_monthly_totals()
    if monthly:
        md = pd.DataFrame(monthly, columns=["month","debit","credit"])
        md["month"] = pd.to_datetime(md["month"] + "-01", errors="coerce")
        md = md.sort_values("month")
        md["month_label"] = md["month"].dt.strftime("%b %Y")
        fig3 = go.Figure()
        if chart_mode in ("Overview", "Credit vs Debit", "Income only"):
            fig3.add_trace(go.Bar(x=md["month_label"], y=md["credit"], name="Income",
                                  marker_color=GREEN, marker_line_width=0, opacity=0.9,
                                  hovertemplate="<b>%{x}</b><br>+₹%{y:,.0f}<extra></extra>"))
        if chart_mode in ("Overview", "Credit vs Debit", "Expense only"):
            fig3.add_trace(go.Bar(x=md["month_label"], y=md["debit"], name="Expense",
                                  marker_color=RED, marker_line_width=0, opacity=0.9,
                                  hovertemplate="<b>%{x}</b><br>-₹%{y:,.0f}<extra></extra>"))
        fig3.update_layout(barmode="group", bargap=0.28, bargroupgap=0.06)
        chart_style(fig3, height=260)
        fig3.update_xaxes(type="category")
        st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)

with m2:
    st.markdown('<div class="chart-card">', unsafe_allow_html=True)
    st.markdown('<div class="chart-card-title">Where Your Money Goes</div><div class="chart-card-sub">Top expense categories</div>', unsafe_allow_html=True)
    cat_rows = get_category_totals("debit")
    if cat_rows:
        cd = pd.DataFrame(cat_rows, columns=["category","total"]).head(8)
        colors = [PALETTE[i % len(PALETTE)] for i in range(len(cd))]
        fig4 = go.Figure(go.Bar(
            x=cd["total"], y=cd["category"], orientation="h",
            marker_color=colors, marker_line_width=0,
            text=[f"₹{v:,.0f}" for v in cd["total"]],
            textposition="outside", textfont=dict(size=10, color=TEXT_C),
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>₹%{x:,.0f}<extra></extra>",
        ))
        chart_style(fig4, height=260)
        fig4.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig4, use_container_width=True, config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)

# ── Transaction table (original logic unchanged) ──────────────────────────────
st.markdown('<div class="section-div">Transaction log</div>', unsafe_allow_html=True)

sc1, sc2, sc3 = st.columns([2.2, 1, 1])
with sc1:
    st.session_state.setdefault("dash_search", "")
    search = st.text_input("Search Transactions", placeholder="Search transactions…", key="dash_search", label_visibility="collapsed")
with sc2:
    st.session_state.setdefault("dash_type_filter", "all")
    type_filter = st.selectbox("Type Filter", ["all","debit","credit"], key="dash_type_filter", label_visibility="collapsed")
with sc3:
    cats = ["all categories"] + sorted(dff["category"].unique().tolist())
    st.session_state.setdefault("dash_cat_filter", "all categories")
    cat_filter = st.selectbox("Category Filter", cats, key="dash_cat_filter", label_visibility="collapsed")

tdf = dff.copy()
if search:
    mask = tdf["note"].str.contains(search, case=False, na=False) | tdf["category"].str.contains(search, case=False, na=False)
    tdf = tdf[mask]
if type_filter != "all":
    tdf = tdf[tdf["transaction_type"] == type_filter]
if cat_filter != "all categories":
    tdf = tdf[tdf["category"] == cat_filter]

display = tdf[["id","transaction_type","date","amount","category","note"]].copy()
display = display.sort_values("date", ascending=False)
display["date"]   = display["date"].dt.strftime("%d %b %Y")
display["amount"] = display.apply(
    lambda r: f"+₹{r['amount']:,.0f}" if r["transaction_type"]=="credit" else f"-₹{r['amount']:,.0f}", axis=1
)
display["transaction_type"] = display["transaction_type"].str.upper()
display.columns = ["ID","Type","Date","Amount","Category","Note"]

st.dataframe(display.set_index("ID"), width="stretch", height=300)

# ── Delete (original logic unchanged) ─────────────────────────────────────────
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
dc1, dc2, dc3 = st.columns([1,1,3])
with dc1:
    del_id = st.number_input("Delete ID", min_value=0, step=1, placeholder="ID to delete", label_visibility="collapsed")
with dc2:
    if st.button("Delete entry", key="del"):
        if del_id and del_id > 0:
            row = get_expense_by_id(int(del_id))
            delete_expense(int(del_id))
            st.success(f"Deleted #{int(del_id)}")
            if row:
                set_dash_undo("delete", {"row": row}, f"Deleted #{int(del_id)}")
            st.rerun()
st.markdown('<span style="color:#c0b8ae;font-size:0.68rem">Enter an ID from the table above to delete a record.</span>', unsafe_allow_html=True)