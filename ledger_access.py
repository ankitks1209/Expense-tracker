"""Optional passcode for the shared personal ledger."""

from hashlib import sha256
from hmac import compare_digest
import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


def require_ledger_access():
    passcode = os.environ.get("ENMA_LEDGER_PASSCODE")
    if not passcode:
        try:
            passcode = st.secrets.get("ENMA_LEDGER_PASSCODE")
        except StreamlitSecretNotFoundError:
            return
    if not passcode:
        return

    expected = sha256(str(passcode).encode()).digest()
    if compare_digest(st.session_state.get("enma_ledger_access", b""), expected):
        return

    st.title("Unlock Enma")
    with st.form("ledger_access", clear_on_submit=True):
        entered = st.text_input("Ledger passcode", type="password")
        if st.form_submit_button("Unlock"):
            if compare_digest(sha256(entered.encode()).digest(), expected):
                st.session_state.enma_ledger_access = expected
                st.rerun()
            st.error("Incorrect passcode.")
    st.stop()
