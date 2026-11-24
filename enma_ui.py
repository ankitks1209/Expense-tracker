"""Shared appearance for Enma's Streamlit pages."""

from pathlib import Path

import streamlit as st
from ledger_reset import render_reset_confirmation


THEMES = {
    "light": {
        "page": "#f2f5fa", "surface": "#ffffff", "soft": "#e8edf6", "border": "#d6dfed",
        "ink": "#142442", "secondary": "#364967", "muted": "#526481",
        "accent": "#264eca", "accent-soft": "#e8eeff", "accent-text": "#ffffff",
        "income": "#14633e", "expense": "#ac2836", "expense-soft": "#ffebee",
        "expense-bar": "#c6434e", "feature": "#14264d", "feature-ink": "#f5f8ff",
        "feature-muted": "#c4d1ed", "feature-rule": "#52658d",
    },
    "dark": {
        "page": "#111828", "surface": "#192338", "soft": "#25334d", "border": "#3a4a67",
        "ink": "#f0f4ff", "secondary": "#c4d0e8", "muted": "#a7b8d5",
        "accent": "#a9beff", "accent-soft": "#283e70", "accent-text": "#131f3e",
        "income": "#80e0ad", "expense": "#ffa5aa", "expense-soft": "#48272d",
        "expense-bar": "#ff8892", "feature": "#223c72", "feature-ink": "#f5f8ff",
        "feature-muted": "#d3dfff", "feature-rule": "#6682ba",
    },
}
STYLESHEET = Path(__file__).with_suffix(".css")
WORDMARK = '<span class="enma-wordmark">Enma</span>'


def apply_theme():
    st.session_state.setdefault("theme", "light")
    palette = THEMES[st.session_state.theme]
    variables = "".join(f"--enma-{name}:{value};" for name, value in palette.items())
    st.html(f"<style>:root {{{variables}}}\n{STYLESHEET.read_text(encoding='utf-8')}</style>")
    return palette


def page_header(*, page="chat"):
    with st.container(key="enma_header"):
        if page == "home":
            brand, theme = st.columns([4, 1], vertical_alignment="center")
        else:
            brand, nav, theme, reset = st.columns([4, 2, 2, 2], vertical_alignment="center")
        with brand:
            if page == "home":
                st.html(f"""<div class="landing-brand">{WORDMARK}
                    <span class="landing-full-name">Expense Navigation and Management Assistant</span>
                </div>""")
            else:
                st.html(f'<a class="enma-brand" href="./" aria-label="Enma home">{WORDMARK}</a>')
        if page != "home":
            with nav:
                if page == "dashboard":
                    if st.button("Chat", key="back", icon=":material/chat_bubble:", width="stretch"):
                        st.switch_page("chat.py")
                elif page == "chat":
                    if st.button("Dashboard", key="dash", icon=":material/monitoring:", width="stretch"):
                        st.switch_page("dashboard.py")
        with theme:
            dark = st.session_state.theme == "dark"
            if st.button(
                "Light mode" if dark else "Dark mode",
                key="dash_theme_toggle" if page == "dashboard" else "theme_toggle",
                icon=":material/light_mode:" if dark else ":material/dark_mode:",
                width="stretch",
            ):
                st.session_state.theme = "light" if dark else "dark"
                st.rerun()
        if page != "home":
            if reset.button("Reset all", key="reset_all_transactions", icon=":material/restart_alt:", width="stretch"):
                st.session_state.confirm_reset_all = True
    if page != "home":
        render_reset_confirmation()
