"""
app.py — ExpenseBot Chat Interface
UI: Clean fintech aesthetic (CRED/Splitwise feel)
Logic: unchanged — multi-transaction, credit/debit, session state
"""

import streamlit as st
from datetime import datetime, timedelta, date
import html
import re
from textwrap import dedent
from db import (
    init_db,
    save_expense,
    get_recent_expenses,
    get_summary_stats,
    get_expense_by_id,
    delete_expenses_by_ids,
)
from ai_extractor import extract_expense

st.set_page_config(
    page_title="Enma · Expense Tracker",
    page_icon="閻魔",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 0 !important; max-width: 100% !important; }

/* ── Page background ── */
.stApp {
    background: #F2F0EB;
}

/* ═══════════════════════════════════════
   LEFT SIDEBAR
═══════════════════════════════════════ */
.sidebar {
    background: #16161A;
    min-height: 100vh;
    padding: 28px 24px 32px 24px;
    display: flex;
    flex-direction: column;
    gap: 0;
    position: relative;
    overflow: hidden;
}

/* subtle glow blobs */
.sidebar::before {
    content: '';
    position: absolute; top: -100px; right: -100px;
    width: 300px; height: 300px;
    background: radial-gradient(circle, rgba(139,92,246,0.12) 0%, transparent 65%);
    pointer-events: none;
}
.sidebar::after {
    content: '';
    position: absolute; bottom: 40px; left: -80px;
    width: 240px; height: 240px;
    background: radial-gradient(circle, rgba(16,185,129,0.08) 0%, transparent 65%);
    pointer-events: none;
}

/* brand */
.brand {
    display: flex; align-items: center; gap: 11px;
    margin-bottom: 28px;
}
.brand-icon {
    width: 38px; height: 38px;
    background: linear-gradient(135deg, #7c3aed, #6366f1);
    border-radius: 11px;
    display: flex; align-items: center; justify-content: center;
    font-size: 17px; flex-shrink: 0;
}
.brand-text-main {
    font-family: 'Outfit', sans-serif;
    font-size: 1.2rem; font-weight: 700;
    color: #f0eeff; letter-spacing: -0.02em;
}
.brand-text-sub {
    font-size: 0.62rem; color: #3a3a42;
    letter-spacing: 0.08em; text-transform: uppercase;
}

/* balance hero card */
.bal-card {
    background: linear-gradient(145deg, #1e1e26 0%, #191920 100%);
    border: 1px solid rgba(139,92,246,0.18);
    border-radius: 18px;
    padding: 20px 20px 18px 20px;
    margin-bottom: 12px;
    position: relative;
    overflow: hidden;
}
.bal-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(139,92,246,0.4), transparent);
}
.bal-card-label {
    font-size: 0.62rem; color: #3a3a48;
    text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;
}
.bal-card-amount {
    font-family: 'Outfit', sans-serif;
    font-size: 2rem; font-weight: 800;
    letter-spacing: -0.04em; line-height: 1; margin-bottom: 6px;
}
.bal-positive { color: #34d399; }
.bal-negative { color: #fb7185; }
.bal-card-sub { font-size: 0.68rem; color: #3a3a4a; line-height: 1.5; }

/* mini stat row */
.mini-row {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 8px; margin-bottom: 22px;
}
.mini-stat {
    border-radius: 13px; padding: 13px 14px;
}
.mini-income  { background: rgba(52,211,153,0.07); border: 1px solid rgba(52,211,153,0.14); }
.mini-expense { background: rgba(251,113,133,0.07); border: 1px solid rgba(251,113,133,0.14); }
.mini-label {
    font-size: 0.6rem; text-transform: uppercase;
    letter-spacing: 0.08em; margin-bottom: 5px;
    display: flex; align-items: center; gap: 5px;
}
.mini-dot { width: 5px; height: 5px; border-radius: 50%; display: inline-block; }
.dot-g { background: #34d399; } .dot-r { background: #fb7185; }
.mini-label-g { color: #2a6650; } .mini-label-r { color: #7a3040; }
.mini-amount {
    font-family: 'Outfit', sans-serif;
    font-size: 1rem; font-weight: 700; letter-spacing: -0.02em;
}
.mini-amt-g { color: #34d399; } .mini-amt-r { color: #fb7185; }

/* feed */
.feed-header {
    font-size: 0.62rem; color: #2e2e38;
    text-transform: uppercase; letter-spacing: 0.1em;
    margin-bottom: 10px; display: flex;
    align-items: center; justify-content: space-between;
}
.feed-list { display: flex; flex-direction: column; gap: 1px; }
.feed-row {
    display: flex; align-items: center; gap: 10px;
    padding: 9px 10px; border-radius: 10px;
    transition: background 0.12s;
}
.feed-row:hover { background: rgba(255,255,255,0.03); }
.feed-emoji {
    width: 30px; height: 30px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 13px; flex-shrink: 0;
}
.fe-debit  { background: rgba(251,113,133,0.1); }
.fe-credit { background: rgba(52,211,153,0.1); }
.feed-info { flex: 1; min-width: 0; }
.feed-cat  { font-size: 0.75rem; font-weight: 500; color: #c8c8d8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.feed-note { font-size: 0.63rem; color: #333340; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.feed-right { text-align: right; flex-shrink: 0; }
.fa-debit  { font-family: 'Outfit', sans-serif; font-size: 0.82rem; font-weight: 600; color: #fb7185; }
.fa-credit { font-family: 'Outfit', sans-serif; font-size: 0.82rem; font-weight: 600; color: #34d399; }
.feed-dt   { font-size: 0.6rem; color: #28282e; margin-top: 1px; }

/* ═══════════════════════════════════════
   RIGHT CHAT PANEL
═══════════════════════════════════════ */
.chat-panel {
    background: #F2F0EB;
    padding: 36px 40px 20px 40px;
}

.chat-panel-title {
    font-family: 'Outfit', sans-serif;
    font-size: 1.55rem; font-weight: 700;
    color: #141416; letter-spacing: -0.03em;
    line-height: 1.2; margin-bottom: 4px;
}
.chat-panel-sub { font-size: 0.8rem; color: #9a9490; margin-bottom: 20px; }

/* summary bar */
.summary-bar {
    display: flex; flex-wrap: wrap; gap: 0;
    background: #fff; border: 1px solid #e8e4dd;
    border-radius: 14px; padding: 14px 20px;
    margin-bottom: 18px; box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.summary-item {
    flex: 1; min-width: 80px;
    padding: 0 16px; border-right: 1px solid #f0ece5;
}
.summary-item:first-child { padding-left: 0; }
.summary-item:last-child  { padding-right: 0; border-right: none; }
.summary-label { font-size: 0.6rem; color: #b0a89e; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 3px; }
.summary-val   { font-family: 'Outfit', sans-serif; font-size: 0.95rem; font-weight: 700; letter-spacing: -0.02em; }
.summary-green  { color: #16a34a; }
.summary-red    { color: #dc2626; }
.summary-muted  { color: #1c1c1e; }

/* ── Chat messages ── */
.chat-wrap {
    max-height: 50vh; overflow-y: auto;
    display: flex; flex-direction: column; gap: 18px;
    padding: 4px 0 16px 0;
    scrollbar-width: thin; scrollbar-color: #ddd transparent;
}
.msg-row { display: flex; gap: 12px; align-items: flex-start; }
.msg-row.user { flex-direction: row-reverse; }

.avatar {
    width: 30px; height: 30px; border-radius: 9px;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.65rem; font-weight: 600; flex-shrink: 0;
    text-transform: uppercase; letter-spacing: 0.02em;
}
.avatar-bot  { background: #6366f1; color: #fff; }
.avatar-user { background: #1c1c1e; color: #fff; }

.bubble {
    border-radius: 6px 16px 16px 16px;
    padding: 13px 17px; max-width: 68%;
    min-width: 120px;
    font-size: 0.84rem; line-height: 1.65;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.bubble-bot {
    background: #fff; border: 1px solid #e8e4dd;
    color: #2c2a26; box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    border-radius: 4px 16px 16px 16px;
}
.bubble-user {
    background: #1c1c1e; color: #f0f0f0;
    border-radius: 16px 4px 16px 16px;
}
.bubble-error {
    background: #fff5f5; border: 1px solid #fecaca; color: #b91c1c;
    border-radius: 4px 16px 16px 16px;
}
.ts { font-size: 0.6rem; color: #c8c0b4; margin-top: 5px; padding: 0 2px; }
.ts-right { text-align: right; }

/* ── Transaction card inside bubble ── */
.txn-card {
    margin-top: 12px; border-radius: 12px;
    padding: 14px 16px; font-size: 0.78rem;
}
.txn-card.debit  { background: #fff5f6; border: 1px solid #fecdd3; }
.txn-card.credit { background: #f0fdf8; border: 1px solid #bbf7d0; }

.txn-stack { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }

.txn-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.txn-lbl {
    font-size: 0.6rem; color: #a09890;
    text-transform: uppercase; letter-spacing: 0.08em; min-width: 54px;
}
.txn-val { color: #2c2a26; font-weight: 500; }
.txn-amount-debit  { font-family: 'Outfit', sans-serif; font-size: 1.25rem; font-weight: 800; color: #e11d48; letter-spacing: -0.03em; }
.txn-amount-credit { font-family: 'Outfit', sans-serif; font-size: 1.25rem; font-weight: 800; color: #16a34a; letter-spacing: -0.03em; }

.badge {
    display: inline-block; padding: 2px 9px; border-radius: 20px;
    font-size: 0.6rem; font-weight: 700;
    letter-spacing: 0.06em; text-transform: uppercase;
}
.badge-debit  { background: #fecdd3; color: #9f1239; }
.badge-credit { background: #bbf7d0; color: #14532d; }

.confidence-pill {
    display: inline-block; padding: 2px 9px; border-radius: 20px;
    font-size: 0.58rem; font-weight: 700;
    letter-spacing: 0.05em; text-transform: uppercase;
}
.confidence-high   { background: #dcfce7; color: #166534; }
.confidence-medium { background: #fef3c7; color: #92400e; }
.confidence-low    { background: #fee2e2; color: #991b1b; }
.txn-uncertain { color: #b45309 !important; font-weight: 700; }

.undo-wrap {
    background: #fff; border: 1px solid #e8e4dd;
    border-radius: 12px; padding: 10px 12px;
    margin: 0 0 10px 0;
}
.undo-text { font-size: 0.74rem; color: #706860; }

.dup-wrap {
    background: #fff7ed; border: 1px solid #fed7aa;
    border-radius: 12px; padding: 10px 12px;
    margin: 0 0 10px 0;
}
.dup-text { font-size: 0.74rem; color: #9a3412; }

.review-wrap {
    background: #fff; border: 1px solid #e8e4dd;
    border-radius: 14px; padding: 14px 14px 10px 14px;
    margin: 0 0 12px 0;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.review-title {
    font-family: 'Outfit', sans-serif;
    font-size: 0.9rem; font-weight: 700; color: #1c1c1e;
    margin-bottom: 4px;
}
.review-sub { font-size: 0.72rem; color: #706860; margin-bottom: 10px; }
.review-item {
    border: 1px solid #ede9e2; border-radius: 12px;
    padding: 12px; margin-bottom: 10px; background: #faf8f4;
}
.review-item-head {
    display: flex; align-items: center; justify-content: space-between;
    gap: 10px; margin-bottom: 10px;
}
.review-item-title {
    font-size: 0.76rem; font-weight: 700; color: #1c1c1e;
    text-transform: uppercase; letter-spacing: 0.08em;
}
.review-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
}
.review-help { font-size: 0.65rem; color: #9a9490; margin-top: 4px; }

/* ── Hints ── */
.hints {
    display: flex; flex-wrap: wrap; gap: 7px;
    margin: 14px 0 10px 0;
}
.hint-pill {
    background: #fff; border: 1px solid #e8e4dd;
    border-radius: 20px; padding: 5px 13px;
    font-size: 0.71rem; color: #706860;
    white-space: nowrap;
}

/* ── Input area ── */
.input-hint {
    font-size: 0.7rem; color: #b0a89e;
    margin-bottom: 10px; line-height: 1.5;
}
.stTextInput > div > div > input {
    background: #fff !important;
    border: 1.5px solid #e0dbd2 !important;
    border-radius: 12px !important;
    color: #1c1c1e !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.9rem !important;
    padding: 13px 18px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
    transition: border-color 0.15s, box-shadow 0.15s;
}
.stTextInput > div > div > input:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.1) !important;
}
.stTextInput > div > div > input::placeholder { color: #c0b8ae !important; }
.stTextInput > div { border: none !important; box-shadow: none !important; }

.stTextArea > div > div > textarea {
    background: #fff !important;
    border: 1.5px solid #e0dbd2 !important;
    border-radius: 12px !important;
    color: #1c1c1e !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.9rem !important;
    padding: 13px 18px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
    transition: border-color 0.15s, box-shadow 0.15s;
    resize: vertical !important;
    min-height: 50px !important;
}
.stTextArea > div > div > textarea:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.1) !important;
}
.stTextArea > div > div > textarea::placeholder { color: #c0b8ae !important; }
.stTextArea > div { border: none !important; box-shadow: none !important; }

.stButton > button {
    background: #1c1c1e !important; color: #fff !important;
    border: none !important; border-radius: 12px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.84rem !important; font-weight: 600 !important;
    padding: 13px 22px !important; width: 100%;
    letter-spacing: 0.01em; transition: all 0.15s !important;
}
.stButton > button:hover {
    background: #6366f1 !important;
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(99,102,241,0.25) !important;
}

.st-key-dash button,
.st-key-reset_chat button,
.st-key-theme_toggle button,
.st-key-taskbar_toggle button {
    white-space: nowrap !important;
    word-break: keep-all !important;
}

.st-key-taskbar_toggle button {
    width: 42px !important;
    min-width: 42px !important;
    height: 42px !important;
    min-height: 42px !important;
    padding: 0 !important;
    border-radius: 10px !important;
    font-size: 1rem !important;
}

@media (max-width: 1000px) {
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 0.7rem !important; }
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }
    .chat-panel { padding: 18px 14px 14px 14px !important; }
    .sidebar { min-height: auto !important; }
    .summary-item { min-width: 48% !important; margin-bottom: 10px; }
    .bubble { max-width: 92% !important; }
    .block-container { padding: 0 !important; }
    .st-key-dash button,
    .st-key-reset_chat button,
    .st-key-theme_toggle button,
    .st-key-taskbar_toggle button {
        min-height: 42px !important;
        font-size: 0.78rem !important;
        padding: 10px 12px !important;
    }
}

@media (max-width: 560px) {
    .mini-row,
    .review-grid {
        grid-template-columns: 1fr !important;
    }
    .chat-panel-title {
        font-size: 1.2rem !important;
    }
}



</style>
""", unsafe_allow_html=True)

# ── Category emoji map ────────────────────────────────────────────────────────
CAT_ICONS = {
    "Food & Dining": "🍽️", "Groceries": "🛒", "Transport": "🚗",
    "Health & Medical": "💊", "Entertainment": "🎬", "Shopping": "🛍️",
    "Utilities & Bills": "⚡", "Education": "📚", "Travel": "✈️",
    "Personal Care": "🪥", "Home & Maintenance": "🏠", "Subscriptions": "📱",
    "Salary": "💼", "Freelance": "💻", "Gift": "🎁",
    "Reimbursement": "🔄", "Investment Returns": "📈",
    "Rental Income": "🏘️", "Other Income": "💰", "Other": "📦",
}

# ── Init (identical to original) ─────────────────────────────────────────────
init_db()


def sanitize_text(value, fallback=""):
    raw = "" if value is None else str(value)
    if re.search(r"</?[a-zA-Z][^>]*>", raw):
        raw = re.sub(r"</?[^>]+>", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        raw = fallback
    return html.escape(raw)


def sanitize_note_text(value, fallback=""):
    raw = "" if value is None else str(value)
    # Drop legacy malformed HTML-ish fragments that may have been stored earlier.
    if re.search(r"(?i)(<[^>]*>|\bclass\s*=|\bstyle\s*=|\bdiv\b|\bspan\b|feed-row|feed-emoji|feed-info|feed-cat|feed-note|feed-right|feed-dt|fa-credit|fa-debit)", raw):
        return fallback
    return sanitize_text(raw, fallback=fallback)

def _initial_messages():
    return [{
        "role": "bot",
        "text": "Hey! 👋 I'm Enma, your expense tracker.\n\nTell me about any transaction in plain English — I'll handle the rest.",
        "extract": None,
        "ts": None,
    }]

if "messages" not in st.session_state:
    st.session_state.messages = _initial_messages()
if "input_key" not in st.session_state:
    st.session_state.input_key = 0
if "undo_action" not in st.session_state:
    st.session_state.undo_action = None
if "theme" not in st.session_state:
    st.session_state.theme = "dark"
if "show_taskbar" not in st.session_state:
    st.session_state.show_taskbar = True


def toggle_theme():
    st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"


# ── Apply theme CSS ──────────────────────────────────────────────────────────
theme = st.session_state.theme
if theme == "dark":
    st.markdown("""
    <style>
    :root {
        --bg-primary: #10131d;
        --text-primary: #e9edf8;
        --text-secondary: #9ba7c0;
        --border-light: #2b3242;
        --card-bg: #1b2233;
        --sidebar-bg: #0d111b;
        --sidebar-text: #eef2ff;
        --input-bg: #141a29;
        --input-border: #2b3242;
        --btn-bg: #2c354a;
        --btn-hover: #3d4964;
    }
    .stApp { background: var(--bg-primary); color: var(--text-primary); }
    .sidebar { background: var(--sidebar-bg); color: var(--sidebar-text); }
    .chat-panel { background: var(--bg-primary); }
    .chat-panel-title, .summary-val, .txn-val, .review-title, .review-item-title { color: var(--text-primary) !important; }
    .chat-panel-sub, .summary-label, .input-hint, .hint-pill, .ts, .review-sub, .review-help { color: var(--text-secondary) !important; }
    .summary-bar, .undo-wrap, .dup-wrap, .review-wrap, .review-item, .bubble-bot, .hint-pill {
        background: var(--card-bg) !important;
        border-color: var(--border-light) !important;
    }
    .bubble-bot,
    .bubble-bot p,
    .bubble-bot span,
    .txn-lbl,
    .txn-val,
    .undo-text,
    .dup-text,
    .review-sub,
    .review-help {
        color: #e4e9f7 !important;
    }
    .txn-card.debit { background: rgba(225, 29, 72, 0.12) !important; border-color: rgba(244, 63, 94, 0.35) !important; }
    .txn-card.credit { background: rgba(22, 163, 74, 0.12) !important; border-color: rgba(34, 197, 94, 0.35) !important; }
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        background: var(--input-bg) !important;
        color: var(--text-primary) !important;
        border-color: var(--input-border) !important;
    }
    .stButton > button,
    .stFormSubmitButton > button,
    .stDownloadButton > button {
        background: var(--btn-bg) !important;
        color: #f5f7ff !important;
        border: 1px solid #4a5776 !important;
    }
    .stButton > button:hover,
    .stFormSubmitButton > button:hover,
    .stDownloadButton > button:hover {
        background: var(--btn-hover) !important;
        border-color: #64759a !important;
    }
    .stButton > button:disabled,
    .stFormSubmitButton > button:disabled,
    .stDownloadButton > button:disabled {
        background: #242a38 !important;
        color: #8e9ab7 !important;
        border: 1px solid #343e55 !important;
        opacity: 1 !important;
    }
    .st-key-dash button,
    .st-key-theme_toggle button,
    .stFormSubmitButton > button {
        background: linear-gradient(135deg, #7c3aed, #6366f1) !important;
        color: #f8faff !important;
        border: 1px solid #8b85ff !important;
    }
    .st-key-dash button:hover,
    .st-key-theme_toggle button:hover,
    .stFormSubmitButton > button:hover {
        background: linear-gradient(135deg, #8b5cf6, #4f46e5) !important;
        border-color: #aba7ff !important;
        box-shadow: 0 10px 22px rgba(99,102,241,0.38) !important;
    }
    .st-key-taskbar_toggle button {
        background: linear-gradient(135deg, rgba(124,58,237,0.28), rgba(99,102,241,0.3)) !important;
        color: #f4f7ff !important;
        border: 1px solid #7f84d8 !important;
    }
    .st-key-taskbar_toggle button:hover {
        background: linear-gradient(135deg, rgba(124,58,237,0.45), rgba(99,102,241,0.48)) !important;
        border-color: #a5abff !important;
        box-shadow: 0 8px 18px rgba(88,85,220,0.35) !important;
    }
    </style>
    """, unsafe_allow_html=True)
else:  # light theme
    st.markdown("""
    <style>
    :root {
        --bg-primary: #FFFFFF;
        --text-primary: #1a1a1a;
        --text-secondary: #4a4a4a;
        --border-light: #e0e0e0;
        --card-bg: #f5f5f5;
        --sidebar-bg: #f9f9f9;
        --sidebar-text: #1a1a1a;
    }
    .stApp { background: var(--bg-primary); color: var(--text-primary); }
    .sidebar { background: var(--sidebar-bg); color: var(--sidebar-text); border-right: 1px solid #e0e0e0; }
    .chat-panel { background: var(--bg-primary); }
    .summary-bar, .undo-wrap, .dup-wrap, .review-wrap, .review-item, .bubble-bot, .hint-pill {
        background: #ffffff !important;
        border-color: var(--border-light) !important;
    }
    </style>
    """, unsafe_allow_html=True)




def normalize_note_key(note):
    n = re.sub(r"\s+", " ", str(note or "").strip().lower())
    return n[:80]


def detect_duplicates(candidates):
    recent_rows = get_recent_expenses(300)
    duplicate_hits = []
    now = datetime.now()
    for txn in candidates:
        amount = round(float(txn.get("amount", 0)), 2)
        txn_date = str(txn.get("date", ""))
        txn_type = str(txn.get("transaction_type", "debit"))
        note_key = normalize_note_key(txn.get("note", ""))
        for row in recent_rows:
            created_at = row[6] if len(row) > 6 else None
            if not created_at:
                continue
            try:
                created_dt = datetime.strptime(str(created_at), "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue

            if abs((now - created_dt).total_seconds()) > 600:
                continue

            row_amount = round(float(row[1]), 2)
            row_date = str(row[4]) if len(row) > 4 else ""
            row_type = str(row[3]) if len(row) > 3 else "debit"
            row_note = normalize_note_key(row[5] if len(row) > 5 else "")

            if row_amount == amount and row_date == txn_date and row_type == txn_type and row_note == note_key:
                duplicate_hits.append({
                    "amount": amount,
                    "date": txn_date,
                    "note": txn.get("note", ""),
                    "transaction_type": txn_type,
                })
                break
    return duplicate_hits





def set_undo_action(action_type, payload, label):
    st.session_state.undo_action = {
        "type": action_type,
        "payload": payload,
        "label": label,
        "expires_at": datetime.now() + timedelta(seconds=8),
        "created_at": datetime.now(),
    }
    st.toast(f"{label}. Undo available for 8s.", icon="↩️")


def save_transactions_and_build_payload(transactions, single_result):
    saved_ids = []
    if transactions:
        saved = 0
        for txn in transactions:
            if isinstance(txn, dict):
                new_id = save_expense(txn)
                saved_ids.append(new_id)
                saved += 1
        message_text = f"Saved {saved} transactions" if saved != 1 else "Saved to history"
        extract_payload = {"transactions": transactions}
    else:
        new_id = save_expense(single_result)
        saved_ids.append(new_id)
        message_text = "Saved to history"
        extract_payload = single_result
    return saved_ids, message_text, extract_payload


# ── Stats ─────────────────────────────────────────────────────────────────────
stats        = get_summary_stats()
net          = stats.get("net_balance", 0.0)
total_credit = stats.get("total_credit", 0.0)
total_debit  = stats.get("total_debit", 0.0)
month_net    = stats.get("month_net", 0.0)
total_count  = stats.get("total_count", 0)
net_sign     = "+" if net >= 0 else ""
net_bal_cls  = "bal-positive" if net >= 0 else "bal-negative"

# ── Build left sidebar HTML ───────────────────────────────────────────────────
recent   = get_recent_expenses(14)
feed_html = ""
for row in recent:
    typ  = row[3] if len(row) > 3 else "debit"
    amt  = float(row[1])
    raw_cat = str(row[2])
    cat  = sanitize_text(raw_cat, fallback="Other")
    dt   = sanitize_text(row[4], fallback="") if len(row) > 4 else ""
    note = sanitize_note_text(row[5], fallback="") if len(row) > 5 else ""
    icon = CAT_ICONS.get(raw_cat, "💳")
    sign = "+" if typ == "credit" else "−"
    feed_html += f"""
    <div class="feed-row">
        <div class="feed-emoji fe-{typ}">{icon}</div>
        <div class="feed-info">
            <div class="feed-cat">{cat}</div>
            {f'<div class="feed-note">{(note or "")[:28]}</div>' if note else ""}
        </div>
        <div class="feed-right">
            <div class="fa-{typ}">{sign}₹{amt:,.0f}</div>
            <div class="feed-dt">{dt}</div>
        </div>
    </div>"""
feed_html = re.sub(r'(?m)^[ \t]+', '', feed_html)

sidebar_html = f"""
<div class="sidebar">
  <div class="brand">
    <div class="brand-icon">閻魔</div>
    <div>
      <div class="brand-text-main">Enma</div>
      <div class="brand-text-sub">Money Tracker</div>
    </div>
  </div>

  <div class="bal-card">
    <div class="bal-card-label">Net Balance</div>
    <div class="bal-card-amount {net_bal_cls}">{net_sign}₹{abs(net):,.0f}</div>
    <div class="bal-card-sub">{total_count} transactions · this month {month_net:+,.0f}</div>
  </div>

  <div class="mini-row">
    <div class="mini-stat mini-income">
      <div class="mini-label mini-label-g"><span class="mini-dot dot-g"></span>Income</div>
      <div class="mini-amount mini-amt-g">₹{total_credit:,.0f}</div>
    </div>
    <div class="mini-stat mini-expense">
      <div class="mini-label mini-label-r"><span class="mini-dot dot-r"></span>Spent</div>
      <div class="mini-amount mini-amt-r">₹{total_debit:,.0f}</div>
    </div>
  </div>

  <div class="feed-header">
    <span>Recent</span>
    <span style="color:#222228">{len(recent)} entries</span>
  </div>
  <div class="feed-list">
    {feed_html if feed_html else '<div style="color:#2a2a32;font-size:0.73rem;padding:10px 4px">No transactions yet</div>'}
  </div>
</div>
"""
sidebar_html = re.sub(r'(?m)^[ \t]+', '', dedent(sidebar_html)).strip()

# ── Build chat messages HTML (same logic as original) ─────────────────────────
msgs_html = '<div class="chat-wrap" id="chatbox">'
for msg in st.session_state.messages:
    ts = msg["ts"].strftime("%H:%M") if msg.get("ts") else ""
    if msg["role"] == "user":
        user_text = html.escape(msg["text"]).replace("\n", "<br>")
        msgs_html += f"""
        <div class="msg-row user">
            <div class="avatar avatar-user">you</div>
            <div>
                <div class="bubble bubble-user">{user_text}</div>
                <div class="ts ts-right">{ts}</div>
            </div>
        </div>"""
    else:
        text  = html.escape(msg["text"]).replace("\n", "<br>")
        extra = " bubble-error" if msg.get("error") else ""
        card_html = ""
        if msg.get("extract"):
            extract = msg["extract"]
            # ── Multi-transaction support (original logic preserved) ──
            transactions = extract.get("transactions") if isinstance(extract, dict) else None
            if transactions:
                card_html = '<div class="txn-stack">'
                for txn in transactions:
                    typ       = txn.get("transaction_type", "debit")
                    sign      = "+" if typ == "credit" else "−"
                    amt_class = f"txn-amount-{typ}"
                    badge_html = f'<span class="badge badge-{typ}">{typ}</span>'
                    txn_cat = sanitize_text(txn.get("category", "—"), fallback="—")
                    txn_date = sanitize_text(txn.get("date", "—"), fallback="—")
                    txn_note = sanitize_note_text(txn.get("note", "—"), fallback="—")
                    icon = CAT_ICONS.get(txn.get("category",""), "💳")
                    card_html += f"""
                    <div class="txn-card {typ}">
                        <div class="txn-row" style="align-items:center;gap:10px;margin-bottom:8px">
                            <span class="{amt_class}">{sign}₹{float(txn.get('amount',0)):,.0f}</span>
                            {badge_html}
                        </div>
                        <div class="txn-row">
                            <span class="txn-lbl">Category</span>
                            <span class="txn-val">{icon} {txn_cat}</span>
                        </div>
                        <div class="txn-row">
                            <span class="txn-lbl">Date</span>
                            <span class="txn-val">{txn_date}</span>
                        </div>
                        <div class="txn-row">
                            <span class="txn-lbl">Note</span>
                            <span class="txn-val">{txn_note}</span>
                        </div>
                    </div>"""
                card_html += '</div>'
            else:
                # Single transaction (original logic preserved)
                e         = extract
                typ       = e.get("transaction_type", "debit")
                sign      = "+" if typ == "credit" else "−"
                amt_class = f"txn-amount-{typ}"
                badge_html = f'<span class="badge badge-{typ}">{typ}</span>'
                e_cat = sanitize_text(e.get("category", "—"), fallback="—")
                e_date = sanitize_text(e.get("date", "—"), fallback="—")
                e_note = sanitize_note_text(e.get("note", "—"), fallback="—")
                icon = CAT_ICONS.get(e.get("category",""), "💳")
                card_html = f"""
                <div class="txn-card {typ}">
                    <div class="txn-row" style="align-items:center;gap:10px;margin-bottom:8px">
                        <span class="{amt_class}">{sign}₹{float(e.get('amount',0)):,.0f}</span>
                        {badge_html}
                    </div>
                    <div class="txn-row">
                        <span class="txn-lbl">Category</span>
                        <span class="txn-val">{icon} {e_cat}</span>
                    </div>
                    <div class="txn-row">
                        <span class="txn-lbl">Date</span>
                        <span class="txn-val">{e_date}</span>
                    </div>
                    <div class="txn-row">
                        <span class="txn-lbl">Note</span>
                        <span class="txn-val">{e_note}</span>
                    </div>
                </div>"""

        msgs_html += f"""
        <div class="msg-row">
            <div class="avatar avatar-bot">E</div>
            <div style="flex:1">
                <div class="bubble bubble-bot{extra}">{text}</div>
                {card_html}
                <div class="ts">{ts}</div>
            </div>
        </div>"""
msgs_html += "</div>"
msgs_html = re.sub(r'(?m)^[ \t]+', '', msgs_html)

# ── Render two-column layout ──────────────────────────────────────────────────
if st.session_state.show_taskbar:
    left_col, right_col = st.columns([340, 860], gap="small")
    with left_col:
        if st.button("✕", key="taskbar_toggle", help="Hide recent panel"):
            st.session_state.show_taskbar = False
            st.rerun()
        st.markdown(sidebar_html, unsafe_allow_html=True)
else:
    right_col = st.container()

with right_col:
    st.markdown('<div class="chat-panel">', unsafe_allow_html=True)
    if st.session_state.show_taskbar:
        head_l, head_r, head_m = st.columns([5, 1.2, 1])
    else:
        head_t, head_l, head_r, head_m = st.columns([0.8, 4.2, 1.2, 1])
        with head_t:
            if st.button("☰", key="taskbar_toggle", help="Show recent panel"):
                st.session_state.show_taskbar = True
                st.rerun()
    with head_l:
        st.markdown('<div class="chat-panel-title">What\'s on your mind?</div>', unsafe_allow_html=True)
    with head_r:
        if st.button("📈 Dash", key="dash", help="Open dashboard"):
            st.switch_page("pages/1_📊_Dashboard.py")
    with head_m:
        theme_icon = "🌙" if st.session_state.theme == "dark" else "☀️"
        if st.button(theme_icon, key="theme_toggle", help="Toggle light/dark mode"):
            toggle_theme()
            st.rerun()
    st.markdown('<div class="chat-panel-sub">Type any transaction — I\'ll extract the details automatically.</div>', unsafe_allow_html=True)

    # Summary bar (same data as original)
    st.markdown(f"""
    <div class="summary-bar">
        <div class="summary-item">
            <div class="summary-label">Net</div>
            <div class="summary-val {'summary-green' if net >= 0 else 'summary-red'}">{net_sign}₹{abs(net):,.0f}</div>
        </div>
        <div class="summary-item">
            <div class="summary-label">Income</div>
            <div class="summary-val summary-muted">₹{total_credit:,.0f}</div>
        </div>
        <div class="summary-item">
            <div class="summary-label">Spent</div>
            <div class="summary-val summary-muted">₹{total_debit:,.0f}</div>
        </div>
        <div class="summary-item">
            <div class="summary-label">This Month</div>
            <div class="summary-val summary-muted">₹{month_net:+,.0f}</div>
        </div>
        <div class="summary-item">
            <div class="summary-label">Transactions</div>
            <div class="summary-val summary-muted">{total_count}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Chat messages
    st.markdown(msgs_html, unsafe_allow_html=True)
    st.markdown("""
    <script>const c=document.getElementById('chatbox');if(c)c.scrollTop=c.scrollHeight;</script>
    """, unsafe_allow_html=True)

    # Hints row
    st.markdown("""
    <div class="hints">
      <span class="hint-pill">paid ₹800 dentist</span>
      <span class="hint-pill">received 20k salary</span>
      <span class="hint-pill">uber 240 today</span>
      <span class="hint-pill">groceries 1500</span>
      <span class="hint-pill">received 200 from papa and paid 120 food</span>
    </div>
    """, unsafe_allow_html=True)

    # Hint text
    st.markdown('<p class="input-hint">debit: "paid 500 groceries" · credit: "received 20000 salary" · mixed: "received 200 from papa and paid 120 food"</p>', unsafe_allow_html=True)


    # Undo window
    undo_state = st.session_state.get("undo_action")
    if undo_state:
        if datetime.now() < undo_state["expires_at"]:
            st.markdown(f'<div class="undo-wrap"><div class="undo-text">{undo_state["label"]} · Undo available for a few seconds.</div></div>', unsafe_allow_html=True)
            uc1, uc2, _ = st.columns([1, 1, 6])
            with uc1:
                if st.button("Undo", key="undo_last_action"):
                    if undo_state["type"] == "save":
                        ids = list(undo_state["payload"].get("ids", []) or [])
                        if not ids:
                            ids = [row.get("id") for row in undo_state["payload"].get("rows", []) if row.get("id")]
                        if ids:
                            delete_expenses_by_ids(ids)
                        st.session_state.messages.append({
                            "role": "bot",
                            "text": "Undid the last save.",
                            "extract": None,
                            "ts": datetime.now(),
                        })
                    st.session_state.undo_action = None
                    st.rerun()
            with uc2:
                if st.button("Dismiss", key="dismiss_undo"):
                    st.session_state.undo_action = None
                    st.rerun()
        else:
            st.session_state.undo_action = None

    # Input row + Reset button (original logic)
    with st.form("chat_form", clear_on_submit=True):
        input_col, send_col = st.columns([5, 1])
        with input_col:
            user_input = st.text_input(
                "User Input", placeholder="Type a transaction…",
                key="chat_input",
                label_visibility="collapsed",
            ).strip()
        with send_col:
            send = st.form_submit_button("Send")
    reset_col, _ = st.columns([2, 5])
    with reset_col:
        if st.button("Reset chat", key="reset_chat"):
            st.session_state.messages = _initial_messages()
            st.session_state.input_key = 0
            st.rerun()

    # ── Handle submission ──
    if send and user_input:
        text = user_input
        st.session_state.messages.append({
            "role": "user", "text": text, "extract": None, "ts": datetime.now()
        })

        with st.spinner("Extracting transaction..."):
            result = extract_expense(text)

        if result.get("error"):
            st.session_state.messages.append({
                "role": "bot",
                "text": f"Error: {result['error']}",
                "extract": None, "error": True, "ts": datetime.now(),
            })
        else:
            transactions = []
            if isinstance(result, dict):
                if "transactions" in result and isinstance(result["transactions"], list):
                    transactions = result["transactions"]
                else:
                    transactions = [result]
            
            saved_ids = []
            if transactions:
                saved = 0
                for txn in transactions:
                    if isinstance(txn, dict):
                        new_id = save_expense(txn)
                        saved_ids.append(new_id)
                        saved += 1
                message_text = f"Saved {saved} transactions" if saved != 1 else "Saved to history"
                extract_payload = {"transactions": transactions} if len(transactions) > 1 else transactions[0]
            else:
                new_id = save_expense(result)
                saved_ids.append(new_id)
                message_text = "Saved to history"
                extract_payload = result
            
            st.session_state.messages.append({
                "role": "bot",
                "text": message_text,
                "extract": extract_payload,
                "ts": datetime.now(),
            })
            set_undo_action("save", {"ids": saved_ids}, "Saved transaction(s)")

        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)