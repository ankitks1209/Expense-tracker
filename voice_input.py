"""Send a short microphone recording to Gnani Prisma for transcription."""

import io
import os
import re
import wave

import requests
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


GNANI_TRANSCRIPTION_URL = "https://api.vachana.ai/stt/v3"
MAX_RECORDING_SECONDS = 30

HINDI_TERMS = {
    "पैसे वापस मिले": "got money back", "वापस मिले": "got back", "वापस दिया": "wapas diya",
    "खर्च किए": "spent", "खर्च किया": "spent", "पे किए": "paid", "पे किया": "paid",
    "खर्च नहीं किया": "did not pay", "नहीं दिए": "did not pay", "नहीं दिया": "did not pay",
    "भुगतान किया": "paid", "भुगतान नहीं किया": "did not pay", "पे नहीं किया": "did not pay",
    "पैसे नहीं मिले": "not received", "रिफंड नहीं आया": "refund pending",
    "रिफंड आया": "refund arrived", "रिफंड मिला": "refund received",
    "रिफंड किया": "refund kiya", "स्प्लिट किया": "split", "बाँटा": "split", "बांटा": "split",
    "मेरा हिस्सा": "my share", "मेरे हिस्से": "my share", "कुल": "total",
    "उसमें से": "from that", "उसमे से": "from that",
    "जिसमें से": "from that", "जिसमे से": "from that",
    "आधे आधे": "split in half", "आधा आधा": "split in half",
    "से लेने हैं": "owes me", "से लेने है": "owes me",
    "मैंने": "maine", "हमने": "humne", "दिया": "diya", "दिए": "diye", "दिये": "diye",
    "भरा": "bhara", "चुकाया": "chukaya", "लाया": "laya", "लाए": "laya", "खरीदा": "kharida",
    "मिला": "mila", "मिली": "mili", "मिले": "mile", "वापस": "wapas",
    "फिर": "then", "आज": "aaj", "कल": "kal", "दिन पहले": "days ago", "और": "aur", "या": "or",
    "मेरा मतलब": "mera matlab", "सॉरी": "sorry", "असल में": "actually",
    "किराया": "rent", "किराये": "rent", "किराए": "rent", "बाकी": "baaki",
    "अलग रखे": "set aside", "बचा लिए": "set aside", "बचाए": "set aside",
    "save कर ली": "set aside", "save कर लिया": "set aside",
    "save करा": "set aside", "save किया": "set aside", "सेव किया": "set aside", "सेव करा": "set aside",
    "सेव कर ली": "set aside", "सेव कर लिया": "set aside",
    "पॉकेट मनी": "pocket money", "ग्रोसरी": "groceries", "राशन": "groceries",
    "रुपये": "rupees", "रुपए": "rupees", "रुपया": "rupee",
    "हाँ": "haan", "हां": "haan", "नहीं": "nahi", "जी": "ji",
    "सैलरी": "salary", "वेतन": "salary", "रिफंड": "refund",
    "मूवी": "movie", "डिनर": "dinner", "लंच": "lunch", "चाय": "chai", "कॉफी": "coffee",
    "खाना खाया": "ate food", "खाना खाए": "ate food", "खाने पर": "on food", "खाने के लिए": "for food",
    "दोस्त को": "to a friend",
    "किराना": "groceries", "पेट्रोल": "petrol", "मेट्रो": "metro", "टैक्सी": "taxi",
    "आने का भाड़ा": "fare", "भाड़ा": "fare", "भाड़ा": "fare",
    "के लगे": "cost", "लगा": "cost", "लगे": "cost",
    "उबर": "Uber", "ओला": "Ola", "ज़ोमैटो": "Zomato", "स्विगी": "Swiggy",
    "जनवरी": "January", "फ़रवरी": "February", "फरवरी": "February",
    "मार्च": "March", "अप्रैल": "April", "मई": "May", "जून": "June",
    "जुलाई": "July", "अगस्त": "August", "सितंबर": "September",
    "अक्टूबर": "October", "नवंबर": "November", "दिसंबर": "December",
}
HINDI_PATTERN = re.compile(
    r"(?<![\w\u0900-\u097f])(?:"
    + "|".join(map(re.escape, sorted(HINDI_TERMS, key=len, reverse=True)))
    + r")(?![\w\u0900-\u097f])"
)
HINDI_DIGITS = str.maketrans("०१२३४५६७८९।", "0123456789.")


def normalize_voice_transcript(transcript: str) -> str:
    """Map common Hindi transaction phrases to the existing chat vocabulary."""
    normalized = transcript.translate(HINDI_DIGITS)
    amount = r"((?:₹\s*)?\d+(?:,\d+)*(?:\.\d+)?)(?:\s+(?:रुपये|रुपए))?"
    normalized = re.sub(
        amount + r"\s+(?:मुझे|मेरे को)\s+देने\s+हैं?\s+([^,.;!?]+?)\s+को(?=$|[\s,.;!?])",
        r"I owe \2 \1", normalized,
    )
    normalized = re.sub(
        amount + r"\s+लेने\s+हैं?\s+(?:मेरे को|मुझे)(?=$|[\s,.;!?])",
        r"I have to get \1 back", normalized,
    )
    normalized = re.sub(
        r"^मुझे\s+(.+?)\s+को\s+(₹?\s*[\d,.]+)(?:\s+(?:रुपये|रुपए))?\s+देने\s+हैं?",
        r"I owe \1 \2", normalized,
    )
    normalized = re.sub(
        r"^(?:मुझे\s+)?(.+?)\s+से\s+(₹?\s*[\d,.]+)(?:\s+(?:रुपये|रुपए))?\s+लेने\s+हैं?",
        r"\1 owes me \2", normalized,
    )
    normalized = HINDI_PATTERN.sub(lambda match: HINDI_TERMS[match[0]], normalized)
    # A recognizer can hear "nahi" as "नई". Only repair it between amounts.
    normalized = re.sub(
        r"(?<=\d)(?P<gap>(?:\s+(?:rupees?|rs\.?))?[,.;]?\s+)नई(?=\s*[,.;]?\s*₹?\s*\d)",
        r"\g<gap>nahi", normalized,
    )
    return re.sub(r"\btrnasport\b", "transport", normalized, flags=re.IGNORECASE)


class TranscriptionError(ValueError):
    pass


def gnani_api_key():
    key = os.environ.get("GNANI_API_KEY", "").strip()
    if key:
        return key
    try:
        return str(st.secrets.get("GNANI_API_KEY", "")).strip()
    except StreamlitSecretNotFoundError:
        return ""


def transcribe_recording(recording: bytes, api_key: str) -> str:
    if not api_key:
        raise TranscriptionError("Configure GNANI_API_KEY to use voice input.")
    try:
        with wave.open(io.BytesIO(recording), "rb") as wav:
            frame_count = wav.getnframes()
            if not frame_count or not wav.readframes(1):
                raise TranscriptionError("The recording is empty. Try again.")
            if frame_count > MAX_RECORDING_SECONDS * wav.getframerate():
                raise TranscriptionError("Record a clip of 30 seconds or less.")
    except (EOFError, wave.Error):
        raise TranscriptionError("The microphone recording could not be read. Try again.") from None

    try:
        response = requests.post(
            GNANI_TRANSCRIPTION_URL,
            headers={"X-API-Key-ID": api_key},
            files={"audio_file": ("recording.wav", recording, "audio/wav")},
            data={"model": "prisma-v3.0", "language_code": "hi-IN,en-IN", "format": "transcribe"},
            timeout=(5, 25),
            allow_redirects=False,
        )
        if response.status_code in (401, 403):
            raise TranscriptionError("Gnani rejected the API key. Check the server configuration.")
        if response.status_code == 429:
            raise TranscriptionError("Gnani is rate-limiting requests. Wait a moment and try again.")
        if response.status_code != 200:
            raise TranscriptionError("Gnani could not transcribe this recording. Try again.")
        payload = response.json()
    except requests.Timeout:
        raise TranscriptionError("Transcription timed out. Try a shorter recording.") from None
    except requests.RequestException:
        raise TranscriptionError("Could not get a transcription from Gnani. Try again.") from None

    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise TranscriptionError("Gnani could not transcribe this recording. Try again.")
    if payload.get("truncated"):
        raise TranscriptionError("The transcript was incomplete. Try a shorter recording.")
    transcript = payload.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        raise TranscriptionError("No speech was detected. Try again closer to the microphone.")
    return transcript.strip()
