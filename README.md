# Enma · Multilingual expense tracker

Record income, expenses and repayments in English, Hindi or Hinglish. Enma asks for details when an amount or repayment is unclear.

[Project evaluation and architecture](submission/REPORT.md) · [Mobile demonstration](submission/mobile-demo.gif)

## Features

- **Natural language input** — "paid ₹800 for the dentist yesterday"
- **Transaction extraction** — local parsing supports amounts such as ₹1,250.50 and 20k, separate dates for each transaction, and common Hinglish phrases
- **Follow-up questions** — clarify a split bill, refund, missing amount, or date in chat before saving
- **Voice messages** — dictate an expense or reply in Hindi, English, or Hinglish using Gnani Prisma
- **Repayment reminders** — track what others owe you and what you owe them, with optional due dates
- **13 smart categories** — Food, Transport, Health, Shopping, and more
- **Analytics dashboard** — daily trends, monthly bars, category donut, full table
- **Light and dark modes** — shared across chat and dashboard
- **Zero-infrastructure** — single SQLite file, no cloud database needed

---

## 🚀 Quick Setup (5 minutes)

### Step 1 — Clone / download the project

```bash
# If you have git:
git clone https://github.com/KakarotGolu/Expense-tracker.git
cd Expense-tracker

# Or just unzip the folder and cd into it
```

### Step 2 — Create a virtual environment

```bash
# Mac / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Optional Groq setup

1. Go to **https://console.groq.com**
2. Sign up (free, no credit card)
3. Click **API Keys** → **Create API Key**
4. Copy the key (starts with `gsk_...`)

Add the key to `.streamlit/secrets.toml` to use the optional model-assisted mode in Chat. The local mode uses numeric amounts.

```toml
GROQ_API_KEY = "gsk_your_actual_key_here"
```

> ⚠️ This file is in `.gitignore` — it will never be committed to git.

### Step 5 — Run the app

```bash
streamlit run app.py
```

Open your browser at **http://localhost:8501**

### Optional microphone setup

Create a [Gnani API key](https://app.gnani.ai/) and add it to `.streamlit/secrets.toml` or set it in the server environment.

```toml
GNANI_API_KEY = "your_gnani_key"
```

In chat, select **Use mic**, allow microphone access, and record up to 30 seconds. Click **Transcribe**, then **Check transactions**. You can answer follow-up questions with the mic. Review the amounts and whether money came in or went out, then select **Save to ledger**. Use **Record again** if something sounds wrong.

You can correct yourself within a recording. For example, “Rent was five thousand. No, four thousand” records ₹4,000 as an expense after you confirm it. If the transcript has both amounts without a clear correction, Enma asks which to use. **Undo last save** removes the last saved entry or batch. **Dismiss** keeps the save and hides those controls.

### Track repayments

Try “I paid ₹3,000 for dinner and split it in half with Rahul” or “I owe Aditya ₹500 tomorrow.” Review the draft and save it. On **Dashboard → Repayments**, you can also add a reminder manually, change its due date, and see which payments are due or overdue. **Mark received** or **Mark paid** records the money movement in the ledger. Due dates are shown in the app.

### Measure transcript understanding

Run the offline pilot from the project directory:

```bash
python -m benchmarks.enma_understanding --split dev --verbose
python -m benchmarks.enma_understanding --split holdout --verbose
```

The 50 cases start from text, including examples of transcription errors. They score amount, direction, category, date, counterparty, repayment link and follow-up type. The default run is offline and never writes to the ledger. Add `--model` to send only the fictional examples to Groq and compare the model before and after validation on shared responses. Use `--retry-rate-limits --request-interval 8` for a paced comparison. The current holdout has been inspected, so reserve new unseen examples for a final comparison.

For an audio comparison, record the fictional cases as WAV files named `01.wav`, `02.wav`, and so on in case order. Pass `--audio-dir PATH --verbose` to send the clips to Gnani, print the intended and transcribed words, and score both versions. Add `--model` to include Groq in that comparison.

### Model-assisted parsing and draft corrections

Set `GROQ_API_KEY` and enable **Use model-assisted parsing** under **Understanding and preferences** in Chat. Groq receives the active message and its follow-up exchange. Enma checks each quote against its surrounding statement and later corrections, checks direction and dates, and shows a draft before anything is saved. Overlapping quotes from one statement cannot create duplicate expenses. If Groq is unavailable on the first turn, Enma tries the local parser. If Groq sends a draft that fails validation, Enma asks for the details again.

In a draft, open **Correct an amount**, select the entry or repayment, and type or speak a correction such as “Change it to 2800.” The other amounts stay as they were. Entries show an exact source quote from the model, or the phrase the local parser used.

New model-generated split repayments reference their expense. The sum of linked repayments cannot exceed that expense, and the database checks this again when saving. Removing or undoing the expense also removes its linked reminders. Previously saved standalone reminders retain their existing records and are not automatically matched to old expenses.

To teach a category, type or say “When I say ‘flat ka rent’, put it under Home,” then confirm the preference. You can also enter or remove preferences under **Understanding and preferences**. Preferences are saved for this ledger and apply only to categories.

---

## 📁 Project Structure

```
expense_tracker/
│
├── app.py                    ← Streamlit entry point and navigation
├── landing.py                ← Landing page
├── chat.py                   ← Text and voice entry
├── db.py                     ← All SQLite database operations
├── ai_extractor.py           ← Transaction parsing and follow-ups
├── requirements.txt          ← Python dependencies
├── expenses.db               ← SQLite database (auto-created)
│
├── dashboard.py              ← Analytics dashboard with charts
│
└── .streamlit/
    ├── config.toml           ← Dark theme settings
    └── secrets.toml          ← Your API keys (⚠️ never commit)
```


## 💬 How to Use

### Chat

Select **Open chat** from the home page.

Describe a completed expense or income in chat.

| You type | Enma records |
|---|---|
| `paid 800 for the dentist yesterday` | ₹800 · Health & Medical · yesterday · dentist |
| `uber 240 this morning` | ₹240 · Transport · today · uber |
| `groceries 2100 last saturday` | ₹2100 · Groceries · last saturday · groceries |
| `netflix subscription 499` | ₹499 · Subscriptions · today · Netflix subscription |
| `coffee 120 rs` | ₹120 · Food & Dining · today · coffee |
| `received 20k salary` | ₹20,000 credit · Salary · today |

If you enter `paid 500 for dinner, split with Rahul`, Enma asks what you personally paid. Reply with your amount, such as `250`. If an entry matches one saved in the last ten minutes, choose whether to save it again.

### Dashboard

Click **📊 Open Dashboard →** to see:
- **KPI cards** — total spent, transaction count, average, top category
- **Daily trend line** — spending pattern over time
- **Category donut** — where your money goes
- **Monthly bars** — month-by-month comparison
- **Full table** — search, filter, and delete entries

## Streamlit Cloud deployment

1. Push your project to a **GitHub repo** (make sure `secrets.toml` is in `.gitignore`)
2. Go to **https://share.streamlit.io**
3. Connect your GitHub repo
4. Set **Main file path** to `app.py`
5. Go to **Settings → Secrets** and add:
   ```
   GROQ_API_KEY = "gsk_your_key_here"
   ```
6. Click **Deploy** ✓

For a public demonstration, start with `ENMA_DEMO_MODE=1 streamlit run app.py`. Each browser session gets a temporary ledger; reloading can start a fresh one. The personal database is never opened in demo mode. Monthly budgets persist alongside the transactions in the selected ledger. Reset recovery lasts only for the current session.

In personal mode the app uses one ledger per deployment. For a private personal ledger, set `ENMA_LEDGER_PASSCODE` to a strong passcode in deployment secrets or the server environment. Both pages prompt for it before showing or changing ledger data. Without a passcode, anyone who can reach the app can use the shared ledger.

> Note: Streamlit Cloud uses ephemeral storage — `expenses.db` resets on redeploy.  
> For persistent cloud storage, swap SQLite for **Supabase** (free tier) — ask ExpenseBot to help you migrate!

## Render deployment

1. Create a **Render** account at render.com
2. New → **Web Service** → connect your repo
3. Set:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app.py --server.port $PORT --server.headless true`
4. Add environment variable: `GROQ_API_KEY = gsk_...`
5. The `expenses.db` file persists on Render's disk (add a persistent disk in settings)

---

## Model used in the evaluation

The optional chat model is configured in `understanding.py`. The benchmark accepts `--model MODEL_ID` for models supporting its structured response schema.

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `streamlit` | Web UI for both chat and dashboard |
| `groq` | Optional model-assisted transaction understanding |
| `plotly` | Interactive charts on dashboard |
| `pandas` | Data manipulation for analytics |
| `reportlab` | Dashboard PDF exports |
| `requests` | Gnani speech-to-text requests |

---
## Troubleshooting

**"GROQ_API_KEY not set"**  
→ Make sure `.streamlit/secrets.toml` exists with your key, or set env var: `export GROQ_API_KEY=gsk_...`

**"groq package not installed"**  
→ Run: `pip install groq`

**"AI returned unexpected format"**  
→ Try again — occasionally the model hiccups. If it persists, check `ai_extractor.py` and verify your API key is valid.

**Charts are empty**  
→ Add a transaction in chat and choose a date range that includes it.

**App won't start**  
→ Make sure you activated your virtual environment: `source venv/bin/activate`
