"""Streamlit entry point for Enma."""

import streamlit as st


st.set_page_config(
    page_title="Enma · Expense Tracker",
    page_icon=":material/receipt_long:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.navigation(
    [
        st.Page("landing.py", title="Home", default=True),
        st.Page("chat.py", title="Chat", url_path="Chat"),
        st.Page("dashboard.py", title="Dashboard", url_path="Dashboard"),
    ],
    position="hidden",
).run()
