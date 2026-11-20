"""Shared reset confirmation and undo for Chat and Dashboard."""

from copy import deepcopy
import sqlite3

import streamlit as st

from db import reset_ledger, restore_ledger


CHAT_STATE = {
    "messages": [], "pending_clarification": None, "pending_duplicate": None, "voice_draft": None,
    "voice_transcript": None, "voice_open": False, "draft_edit": None, "undo_action": None,
    "dash_undo_action": None, "budgets": {}, "duplicate_reminder": None,
}


def render_reset_confirmation():
    st.session_state.setdefault("confirm_reset_all", False)
    undo = st.session_state.get("ledger_reset_undo")
    if undo:
        with st.container(border=True):
            st.write("Ledger reset. Your saved transactions and repayment reminders were cleared.")
            restore, dismiss = st.columns(2)
            if restore.button("Undo reset", key="undo_ledger_reset"):
                try:
                    restore_ledger(undo["ledger"])
                except sqlite3.Error:
                    st.error("Could not restore the ledger. Try again.")
                else:
                    st.session_state.update(undo["session"])
                    st.session_state.ledger_reset_undo = None
                    st.rerun()
            if dismiss.button("Dismiss", key="dismiss_ledger_reset"):
                st.session_state.ledger_reset_undo = None
                st.rerun()
    if not st.session_state.confirm_reset_all:
        return
    with st.container(border=True):
        st.warning("Clear all saved income, expenses, repayment reminders, budgets, and this chat? Undo is available only in this browser session. Reloading or restarting the app can end recovery.")
        clear, cancel = st.columns(2)
        if clear.button("Reset now", key="confirm_reset_all_transactions", type="primary"):
            session = deepcopy({key: st.session_state.get(key, default) for key, default in CHAT_STATE.items()})
            try:
                snapshot = reset_ledger()
            except sqlite3.Error:
                st.error("Could not reset the ledger. Try again.")
            else:
                st.session_state.ledger_reset_undo = {"ledger": snapshot, "session": session}
                st.session_state.update(deepcopy(CHAT_STATE))
                st.session_state.voice_recording_id = st.session_state.get("voice_recording_id", 0) + 1
                st.session_state.confirm_reset_all = False
                st.rerun()
        if cancel.button("Cancel", key="cancel_reset_all_transactions"):
            st.session_state.confirm_reset_all = False
            st.rerun()
