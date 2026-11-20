"""Enma's landing page with an example voice entry."""

from pathlib import Path

import streamlit as st

from enma_ui import apply_theme, page_header


apply_theme()
stylesheet = Path(__file__).with_suffix(".css").read_text(encoding="utf-8")
st.html(f"<style>{stylesheet}</style>")
page_header(page="home")

with st.container(key="landing_hero"):
    intro, example = st.columns([1, 1], gap="large", vertical_alignment="center")
    with intro:
        st.html("""
            <div class="landing-intro">
                <h1>Log an expense<br>with your voice</h1>
                <p>Speak or type in Hindi, English, or Hinglish. Enma shows the amount, category, and date so you can check them before you save.</p>
            </div>
        """)
        with st.container(key="landing_actions", horizontal=True, gap="small"):
            if st.button("Open chat", key="landing_chat", type="primary", icon=":material/arrow_forward:"):
                st.switch_page("chat.py")
            if st.button("View dashboard", key="landing_dashboard"):
                st.switch_page("dashboard.py")

    with example:
        st.html("""
            <figure class="landing-demo">
                <figcaption class="landing-demo-label">Example voice entry</figcaption>
                <blockquote lang="hi-Latn">“Kal rent ke liye <s>₹5,000</s> diye. Nahi, <strong>₹4,000.</strong>”</blockquote>
                <div class="landing-preview">
                    <div class="landing-preview-row">
                        <span>Ready to review</span><span>Money spent</span>
                    </div>
                    <strong class="landing-preview-amount">₹4,000</strong>
                    <div class="landing-preview-row">
                        <span>Rent · Home &amp; Maintenance</span><span>Yesterday</span>
                    </div>
                </div>
            </figure>
        """)

st.html("""
    <section class="landing-steps" aria-labelledby="landing-steps-title">
        <h2 id="landing-steps-title">From voice note to ledger</h2>
        <ol>
            <li>
                <h3>Tell Enma what happened</h3>
                <p>Log one payment or describe several transactions in a single message.</p>
            </li>
            <li>
                <h3>Check the details</h3>
                <p>Correct yourself as you speak. If Enma asks which amount you meant, you can answer with the mic.</p>
            </li>
            <li>
                <h3>See where your money went</h3>
                <p>Save the entry, then open the dashboard to compare money received, money spent, and your biggest expenses.</p>
            </li>
        </ol>
    </section>
""")
