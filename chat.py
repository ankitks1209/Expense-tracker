"""Chat and voice entry for Enma."""

import streamlit as st
from datetime import datetime
import html
import re
import sqlite3
from db import (
    init_db,
    DuplicateExpense,
    save_chat_entries,
    get_recent_expenses,
    get_summary_stats,
    undo_chat_entries,
    category_preferences,
    set_category_preference,
    remove_category_preference,
)
from ai_extractor import ALL_CATEGORIES, extract_expense, resolve_clarification
from draft_edits import attach_source_quotes, apply_preferences, draft_entries, edit_amount, preference_phrase, teach_command
from enma_ui import apply_theme, page_header
from ledger_access import require_ledger_access
from understanding import ModelUnavailable, UnderstandingError, ask_model, groq_key
from voice_input import TranscriptionError, gnani_api_key, normalize_voice_transcript, transcribe_recording

st.set_page_config(
    page_title="Enma · Expense Tracker",
    page_icon=":material/receipt_long:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

apply_theme()
require_ledger_access()
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

st.session_state.setdefault("messages", [])
st.session_state.setdefault("pending_clarification", None)
st.session_state.setdefault("pending_duplicate", None)
st.session_state.setdefault("voice_transcript", None)
st.session_state.setdefault("voice_recording_id", 0)
st.session_state.setdefault("undo_action", None)
st.session_state.setdefault("voice_open", False)
st.session_state.setdefault("voice_draft", None)
st.session_state.setdefault("draft_edit", None)
st.session_state.setdefault("teach_preference", None)
st.session_state.setdefault("parser_model_assisted", False)


def append_bot_message(message, *, error=False, extract=None, follow_up=False):
    st.session_state.messages.append({
        "role": "bot", "text": message, "error": error, "extract": extract, "ts": datetime.now(),
        "follow_up": follow_up,
    })


def save_chat_result(result, *, allow_duplicate=False):
    transactions, reminders = draft_entries(result)
    try:
        saved_ids, reminder_ids = save_chat_entries(transactions, reminders, check_duplicates=not allow_duplicate)
    except DuplicateExpense:
        st.session_state.pending_duplicate = result
        return True
    except (sqlite3.Error, ValueError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "Could not save the entries. Please try again."
        append_bot_message(message, error=True)
        return False
    reminder_count = len(reminder_ids) + sum(bool(row.get("repayment")) for row in transactions)
    counts = []
    if saved_ids:
        counts.append(f"{len(saved_ids)} {'transaction' if len(saved_ids) == 1 else 'transactions'}")
    if reminder_count:
        counts.append(f"{reminder_count} {'repayment reminder' if reminder_count == 1 else 'repayment reminders'}")
    message = f"Saved {' and '.join(counts)}"
    append_bot_message(message, extract=result)
    st.session_state.undo_action = {"ids": saved_ids, "reminder_ids": reminder_ids, "message": st.session_state.messages[-1]}
    return True


def submit_chat_message(message, pending, *, from_voice=False):
    st.session_state.messages.append({
        "role": "user", "text": message, "extract": None, "ts": datetime.now(),
    })
    if not pending:
        try:
            teaching = teach_command(message)
        except ValueError as exc:
            append_bot_message(str(exc), error=True)
            return
        if teaching:
            st.session_state.teach_preference = teaching
            append_bot_message("Review the category preference under Understanding and preferences.")
            return
    with st.spinner("Reading your message…"):
        model_turns = pending.get("model_turns") if pending else None
        if model_turns or (not pending and st.session_state.parser_model_assisted):
            turns = list(model_turns or [])
            if pending:
                turns.append({"role": "assistant", "content": pending["question"]})
            turns.append({"role": "user", "content": message})
            try:
                result = ask_model(turns, groq_key())
            except ModelUnavailable:
                if pending:
                    result = {"clarification": {**pending, "reply_hint": "Couldn’t check that reply. Try again or discard this draft."}}
                else:
                    append_bot_message("Model-assisted parsing was unavailable. Review the result from the local parser.")
                    result = extract_expense(normalize_voice_transcript(message), allow_remote_amount=False)
            except UnderstandingError:
                result = {"clarification": {
                    "kind": "repeat",
                    "question": "I couldn’t verify the draft against what you said. Can you repeat the payment or repayment details?",
                    "model_turns": turns,
                    "ready": pending.get("ready", []) if pending else [],
                    "ready_reminders": pending.get("ready_reminders", []) if pending else [],
                }}
            force_review = True
        else:
            parsed_text = normalize_voice_transcript(message)
            result = resolve_clarification(pending, parsed_text) if pending else extract_expense(parsed_text, allow_remote_amount=False)
            force_review = False
    if pending and pending.get("original_message"):
        attach_source_quotes(result, pending["original_message"])
    attach_source_quotes(result, message)
    apply_preferences(result, category_preferences())

    st.session_state.pending_clarification = result.get("clarification")
    if question := st.session_state.pending_clarification:
        question["original_message"] = pending.get("original_message", message) if pending else message
        if not question.get("reply_hint"):
            append_bot_message(question["question"], follow_up=True)
    elif result.get("error"):
        append_bot_message(result["error"], error=True)
    elif force_review or from_voice or pending or "transactions" in result or "repayment" in result or "reminder" in result:
        st.session_state.voice_draft = result
    else:
        save_chat_result(result)


def format_money(amount, *, signed=False):
    sign = "−" if amount < 0 else ("+" if signed else "")
    return f"{sign}₹{abs(amount):,.2f}"


def repayment_text(reminder):
    collect = reminder.get("direction", "collect") == "collect"
    person = sanitize_text(reminder.get("person"))
    amount = format_money(reminder["amount"]).removesuffix(".00")
    if not person:
        return f"{amount} to collect" if collect else f"{amount} to pay"
    return f"{person} owes you {amount}" if collect else f"You owe {person} {amount}"


def source_details(entry):
    lines = []
    for field, label in (("source", "From your message"), ("parsed_phrase", "Phrase Enma used"), ("correction", "Your correction")):
        if entry.get(field) and (field != "parsed_phrase" or not entry.get("source")):
            lines.append(f'<span class="receipt-note">{label} · {sanitize_text(entry[field])}</span>')
    return "".join(lines)


def entry_cards(transactions, reminders):
    cards = [receipt(row) for row in transactions]
    for reminder in reminders:
        due = sanitize_text(reminder.get("due_date"))
        note = sanitize_note_text(reminder.get("note"))
        details = "To collect" if reminder["direction"] == "collect" else "To pay"
        if due:
            details += f" · Due {due}"
        cards.append(f"""
            <article class="enma-receipt">
                <strong>{repayment_text(reminder)}</strong>
                <span class="receipt-note">{details}</span>
                {f'<span class="receipt-note">{note}</span>' if note else ''}
                {source_details(reminder)}
            </article>
        """)
    return f'<div class="receipt-stack">{"".join(cards)}</div>'


def receipt(transaction):
    credit = transaction.get("transaction_type") == "credit"
    direction = "Money in" if credit else "Money out"
    tone = "income" if credit else "expense"
    amount = float(transaction["amount"]) * (1 if credit else -1)
    category = sanitize_text(transaction.get("category"), "Other")
    try:
        txn_date = datetime.fromisoformat(transaction["date"]).strftime("%d %b %Y").lstrip("0")
    except (KeyError, ValueError, TypeError):
        txn_date = sanitize_text(transaction.get("date"), "—")
    note = sanitize_note_text(transaction.get("note"))
    repayment = transaction.get("repayment")
    reminder = f'<span class="receipt-note">{repayment_text(repayment)}</span>' if repayment else ""
    return f"""
        <article class="enma-receipt">
            <div class="receipt-head">
                <strong class="receipt-amount enma-{tone}">{format_money(amount, signed=True)}</strong>
                <span class="receipt-kind">{direction}</span>
            </div>
            <div class="receipt-details"><span>{category}</span><time>{txn_date}</time></div>
            {f'<span class="receipt-note">{note}</span>' if note else ''}
            {reminder}
            {source_details(transaction)}
            {source_details(repayment) if repayment else ""}
        </article>
    """


def render_message(message):
    user = message["role"] == "user"
    text = html.escape(message["text"]).replace("\n", "<br>")
    timestamp = message["ts"].strftime("%H:%M")
    author = "You" if user else "Enma"
    extract = message.get("extract")
    cards = entry_cards(*draft_entries(extract)) if extract else ""
    style = " error" if message.get("error") else ""
    st.html(f"""
        <article class="chat-message {'user' if user else 'assistant'}">
            <div class="chat-meta"><strong>{author}</strong><time>{timestamp}</time></div>
            <div class="chat-bubble{style}">{text}</div>
            {cards}
        </article>
    """)


def render_conversation():
    messages = st.session_state.messages
    # Skip the initial greeting saved by the previous chat layout.
    messages = [message for message in messages if message.get("ts")]
    pending = st.session_state.pending_clarification
    if pending:
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if message.get("follow_up") and message["text"] == pending["question"]:
                messages.pop(index)  # The current question is already shown above the reply controls.
                break
    with st.container(key="enma_conversation", border=True):
        if not messages:
            st.html("""
                <div class="chat-empty">
                    <div>
                        <div class="enma-card-title">Start with a transaction</div>
                        <p>Include the amount and what it was for. Add the date if it wasn’t today.</p>
                    </div>
                    <div class="enma-receipt empty-example">
                        <q>Paid ₹250 for lunch yesterday</q>
                        <div class="receipt-details"><span>Food &amp; Dining</span><span>Yesterday</span></div>
                    </div>
                </div>
            """)
            return
        if len(messages) > 2:
            with st.expander("Earlier messages"):
                for message in messages[:-2]:
                    render_message(message)
        for message in messages[-2:]:
            render_message(message)


def render_recent():
    stats = get_summary_stats()
    net = stats["net_balance"]
    st.html(f"""
        <section class="ledger-summary" aria-label="Ledger summary">
            <div>
                <div class="ledger-summary-label">Net balance</div>
                <div class="enma-amount">{format_money(net, signed=True)}</div>
            </div>
            <dl>
                <div><dt>Income</dt><dd>{format_money(stats['total_credit'])}</dd></div>
                <div><dt>Spent</dt><dd>{format_money(stats['total_debit'])}</dd></div>
                <div><dt>This month</dt><dd>{format_money(stats['month_net'], signed=True)}</dd></div>
            </dl>
        </section>
    """)
    recent = get_recent_expenses(14)
    rows = []
    for _, amount, category, direction, txn_date, note, _ in recent:
        credit = direction == "credit"
        category = sanitize_text(category, "Other")
        txn_date = sanitize_text(txn_date)
        note = sanitize_note_text(note)
        rows.append(f"""
            <div class="feed-row">
                <div class="feed-main">
                    <div class="feed-name">{category}</div>
                    {f'<div class="feed-note">{note}</div>' if note else ''}
                </div>
                <div class="feed-money">
                    <div class="feed-value enma-{'income' if credit else 'expense'}">
                        {format_money(amount if credit else -amount, signed=True)}
                    </div>
                    <div class="feed-date">{txn_date}</div>
                </div>
            </div>
        """)
    st.html(f"""
        <section class="ledger-recent">
            <header><div class="enma-card-title">Recent activity</div><span>{len(recent)} shown</span></header>
            {''.join(rows) if rows else '<div class="enma-muted">No transactions yet</div>'}
        </section>
    """)


def render_undo():
    action = st.session_state.undo_action
    if not action:
        return
    st.caption("Undo removes the last save. Dismiss keeps it and hides these controls.")
    undo, dismiss = st.columns(2)
    if undo.button("Undo last save", key="undo_last_action", icon=":material/undo:", width="stretch"):
        ids = action.get("ids") or action.get("payload", {}).get("ids", [])
        try:
            undo_chat_entries(ids, action.get("reminder_ids", []))
        except (sqlite3.Error, ValueError) as exc:
            st.error(str(exc) if isinstance(exc, ValueError) else "Could not undo the save. Try again.")
            return
        saved_message = action.get("message")
        if saved_message is not None:
            saved_message.update(text="Save undone", extract=None)
        append_bot_message("Undid the last save.")
        st.session_state.undo_action = None
        st.rerun()
    if dismiss.button("Dismiss", key="dismiss_undo", width="stretch"):
        st.session_state.undo_action = None
        st.rerun()


def clear_voice():
    st.session_state.voice_open = False
    st.session_state.voice_transcript = None
    st.session_state.voice_recording_id += 1


def render_voice_review(pending, transcript, *, editing=False):
    with st.form("voice_review"):
        reviewed = st.text_area("Review what Enma heard", value=transcript)
        send_col, discard_col = st.columns(2)
        send_voice = send_col.form_submit_button(
            "Apply correction" if editing else "Send reply" if pending else "Check transactions", type="primary", width="stretch"
        )
        discard_voice = discard_col.form_submit_button("Record again", width="stretch")
    if send_voice and not reviewed.strip():
        st.warning("Enter a transcript or discard this recording.")
    elif send_voice or discard_voice:
        clear_voice()
        if send_voice:
            if editing:
                apply_draft_edit(reviewed.strip())
            else:
                submit_chat_message(reviewed.strip(), pending, from_voice=True)
        else:
            st.session_state.voice_open = True
        st.rerun()
    if st.button("Discard recording", key="discard_voice_transcript"):
        clear_voice()
        st.rerun()


def render_recorder(voice_key):
    if not voice_key:
        st.caption("Set GNANI_API_KEY on the server to enable the microphone.")
        return
    st.caption("Record up to 30 seconds in English, Hindi, or Hinglish. Gnani transcribes the clip.")
    with st.form("voice_recording"):
        recording = st.audio_input(
            "Microphone", sample_rate=16000,
            key=f"voice_recording_{st.session_state.voice_recording_id}",
        )
        transcribe = st.form_submit_button("Transcribe", type="primary")
    if not transcribe:
        return
    if recording is None:
        st.warning("Record a voice message first.")
        return
    try:
        with st.spinner("Transcribing…"):
            transcript = transcribe_recording(recording.getvalue(), voice_key)
    except TranscriptionError as exc:
        st.error(str(exc))
        return
    st.session_state.voice_transcript = transcript
    st.session_state.voice_recording_id += 1
    st.rerun()


def render_follow_up(pending):
    st.markdown("**One detail to confirm**")
    st.write(pending["question"])
    if pending.get("reply_hint"):
        st.warning(pending["reply_hint"])
    ready = pending.get("ready", [])
    reminders = pending.get("ready_reminders", [])
    if ready or reminders:
        with st.expander(f"{len(ready) + len(reminders)} understood · unsaved", expanded=True):
            st.html(entry_cards(ready, reminders))
    if suggestion := pending.get("suggestion"):
        label = format_money(suggestion).removesuffix(".00")
        is_repayment = pending["kind"] == "due"
        action = f"Track {label}" if is_repayment else f"I paid {label}"
        key = "suggest_repayment" if is_repayment else "suggest_payment"
        if st.button(action, key=key, type="primary"):
            submit_chat_message(str(suggestion), pending)
            st.rerun()
    if pending["kind"] == "due":
        if st.button("Skip repayment", key="skip_repayment"):
            submit_chat_message("skip repayment", pending)
            st.rerun()
    if st.button("Discard draft", key="cancel_clarification"):
        st.session_state.pending_clarification = None
        clear_voice()
        append_bot_message("Draft discarded.")
        st.rerun()


def render_draft(draft):
    rows, reminders = draft_entries(draft)
    count = len(rows) + len(reminders)
    st.markdown(f"**Review {count} {'entry' if count == 1 else 'entries'} before saving**")
    st.html(entry_cards(rows, reminders))
    if reminders or any(row.get("repayment") for row in rows):
        st.caption("Pending repayments appear on the Dashboard and count when marked received or paid.")
    save, retry, cancel = st.columns(3)
    label = "Save to ledger" if rows else "Save reminder" if count == 1 else "Save reminders"
    if save.button(label, key="save_voice_draft", type="primary", width="stretch"):
        if save_chat_result(draft):
            st.session_state.voice_draft = None
            st.session_state.draft_edit = None
            clear_voice()
        st.rerun()
    if retry.button("Record again", key="retry_voice_draft", width="stretch"):
        st.session_state.voice_draft = None
        st.session_state.draft_edit = None
        clear_voice()
        st.session_state.voice_open = True
        st.rerun()
    if cancel.button("Discard draft", key="cancel_voice_draft", width="stretch"):
        st.session_state.voice_draft = None
        st.session_state.draft_edit = None
        clear_voice()
        append_bot_message("Draft discarded.")
        st.rerun()
    render_draft_editor(rows, reminders)


def apply_draft_edit(message):
    group, index = st.session_state.edit_target
    try:
        st.session_state.voice_draft = edit_amount(st.session_state.voice_draft, group, index, message)
    except ValueError as exc:
        st.session_state.draft_edit = str(exc)
    else:
        st.session_state.draft_edit = "Draft updated."


def render_draft_editor(rows, reminders):
    with st.expander("Correct an amount", expanded=bool(st.session_state.voice_open or st.session_state.draft_edit)):
        options = {}
        for index, row in enumerate(rows):
            options[("transaction", index)] = f"{index + 1}. {row['note']} · {format_money(row['amount'])}"
            if row.get("repayment"):
                due = row["repayment"]
                options[("repayment", index)] = f"{index + 1}. To collect from {due['person'] or 'someone'} · {format_money(due['amount'])}"
        for index, row in enumerate(reminders):
            action = "To collect from" if row["direction"] == "collect" else "To pay"
            options[("reminder", index)] = f"{len(rows) + index + 1}. {action} {row['person'] or 'someone'} · {format_money(row['amount'])}"
        st.selectbox("Entry to correct", list(options), format_func=options.get, key="edit_target",
                     disabled=st.session_state.voice_transcript is not None or st.session_state.voice_open)
        if st.session_state.draft_edit:
            st.info(st.session_state.draft_edit)
        with st.form("draft_amount_edit", clear_on_submit=True):
            correction = st.text_input("New amount or correction", placeholder="Change it to ₹2,800")
            if st.form_submit_button("Apply correction", disabled=st.session_state.voice_open) and correction.strip():
                apply_draft_edit(correction.strip())
                st.rerun()
        if st.session_state.voice_transcript is not None:
            render_voice_review(None, st.session_state.voice_transcript, editing=True)
        elif st.session_state.voice_open:
            if st.button("Close mic", key="close_draft_mic"):
                clear_voice()
                st.rerun()
            render_recorder(gnani_api_key())
        elif st.button("Speak correction", key="speak_correction", icon=":material/mic:"):
            st.session_state.voice_open = True
            st.rerun()


def remember_parser_choice():
    st.session_state.parser_model_assisted = st.session_state.model_assisted


def render_parser_settings():
    with st.expander("Understanding and preferences", expanded=bool(st.session_state.teach_preference)):
        st.session_state.model_assisted = st.session_state.parser_model_assisted
        st.checkbox("Use model-assisted parsing", key="model_assisted", on_change=remember_parser_choice)
        st.caption("When enabled, Groq receives the current message and its follow-up replies to draft entries. Gnani still transcribes audio.")
        if teaching := st.session_state.teach_preference:
            phrase, category = teaching
            st.write(f"Remember “{phrase}” as {category}?")
            save, cancel = st.columns(2)
            if save.button("Remember preference"):
                set_category_preference(phrase, category)
                st.session_state.teach_preference = None
                append_bot_message(f"I’ll categorize “{phrase}” as {category}.")
                st.rerun()
            if cancel.button("Cancel preference"):
                st.session_state.teach_preference = None
                st.rerun()
        with st.form("category_preference", clear_on_submit=True):
            phrase = st.text_input("Phrase to remember", placeholder="flat ka rent", max_chars=100)
            category = st.selectbox("Category", ALL_CATEGORIES)
            if st.form_submit_button("Save preference"):
                if normalized := preference_phrase(phrase):
                    set_category_preference(normalized, category)
                    st.rerun()
                st.warning("Enter a phrase to remember.")
        preferences = category_preferences()
        if preferences:
            phrase = st.selectbox("Saved preferences", list(preferences),
                                  format_func=lambda key: f"{key} → {preferences[key]}")
            if st.button("Forget preference"):
                remove_category_preference(phrase)
                st.rerun()


def submit_typed_message():
    message = st.session_state.chat_input
    if message and message.strip():
        clear_voice()
        submit_chat_message(message.strip(), st.session_state.pending_clarification)


def render_composer():
    pending_duplicate = st.session_state.pending_duplicate
    if pending_duplicate:
        st.warning("A matching entry already exists. Save again only if this is a separate payment or debt.")
        keep, cancel = st.columns(2)
        if keep.button("Save anyway", key="save_duplicate", type="primary", width="stretch"):
            st.session_state.pending_duplicate = None
            save_chat_result(pending_duplicate, allow_duplicate=True)
            st.rerun()
        if cancel.button("Cancel save", key="cancel_duplicate", width="stretch"):
            st.session_state.pending_duplicate = None
            append_bot_message("Canceled the save.")
            st.rerun()

    pending = st.session_state.pending_clarification
    transcript = st.session_state.voice_transcript
    draft = st.session_state.voice_draft
    with st.container(key="enma_composer"):
        if pending:
            render_follow_up(pending)
        if draft:
            render_draft(draft)
        elif transcript is not None:
            render_voice_review(pending, transcript)
        else:
            with st.container(key="enma_entry"):
                entry, mic = st.columns([5, 1.65], vertical_alignment="center")
                with entry:
                    st.chat_input(
                        "Type a message…",
                        key="chat_input", disabled=bool(pending_duplicate),
                        on_submit=submit_typed_message,
                    )
                with mic:
                    voice_open = st.session_state.voice_open
                    if st.button(
                        "Close mic" if voice_open else ("Voice reply" if pending else "Use mic"),
                        key="toggle_voice", icon=":material/mic_off:" if voice_open else ":material/mic:",
                        type="secondary" if voice_open else "primary", width="stretch",
                        disabled=bool(pending_duplicate),
                    ):
                        st.session_state.voice_open = not voice_open
                        st.session_state.voice_recording_id += 1
                        st.rerun()
            if st.session_state.voice_open and not pending_duplicate:
                render_recorder(gnani_api_key())


page_header()
main, recent = st.columns([2.55, 1], gap="large")
with main:
    st.html("""
        <div class="enma-heading">
            <h1>Log a transaction</h1>
            <p>Say it in English, Hindi, or Hinglish. You can type it too.</p>
        </div>
    """)
    render_conversation()
    render_undo()
    render_composer()
    render_parser_settings()
    if st.session_state.messages and st.button("Reset chat", key="reset_chat", type="tertiary"):
        st.session_state.messages = []
        st.session_state.pending_clarification = None
        st.session_state.pending_duplicate = None
        st.session_state.voice_draft = None
        st.session_state.draft_edit = None
        st.session_state.teach_preference = None
        clear_voice()
        st.rerun()
with recent:
    render_recent()
