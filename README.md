ExpenseBot — AI-powered Expense Tracker
Type expenses in plain English. AI extracts the details. Dashboard shows you the trends.

1) Features

Natural language input** — "paid ₹800 for the dentist yesterday"
AI extraction** — Groq (free) parses amount, category, date, and note automatically
13 smart categories** — Food, Transport, Health, Shopping, and more
Analytics dashboard** — daily trends, monthly bars, category donut, full table
Dark mode** — clean monospace aesthetic, mobile-friendly
Zero-infrastructure** — single SQLite file, no cloud database needed

 Quick Setup (5 minutes)

Step 1 — Clone / download the project

```bash
# If you have git:
git clone <your-repo-url>
cd expense_tracker

# Or just unzip the folder and cd into it
```

 Step 2 — Create a virtual environment

```bash
# Mac / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

 Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

Step 4 — Get a FREE Groq API key

1. Go to **https://console.groq.com**
2. Sign up (free, no credit card)
3. Click **API Keys** → **Create API Key**
4. Copy the key (starts with `gsk_...`)

Step 5 — Add your API key

Edit `.streamlit/secrets.toml`:

```toml
GROQ_API_KEY = "gsk_your_actual_key_here"
```

> ⚠️ This file is in `.gitignore` — it will never be committed to git.
 Step 6 — (Optional) Add demo data

```bash
python seed_data.py
```

This adds ~40 sample expenses so you can immediately see the dashboard charts.

### Step 7 — Run the app!

```bash
streamlit run app.py
```

Open your browser at **http://localhost:8501** 🎉

*📁 Project Structure

```
expense_tracker/
│
├── app.py                    ← Main chat interface (home page)
├── db.py                     ← All SQLite database operations
├── ai_extractor.py           ← Groq AI expense parsing
├── seed_data.py              ← (Optional) Add demo data
├── requirements.txt          ← Python dependencies
├── expenses.db               ← SQLite database (auto-created)
│
├── pages/
│   └── 1_📊_Dashboard.py    ← Analytics dashboard with charts
│
└── .streamlit/
    ├── config.toml           ← Dark theme settings
    └── secrets.toml          ← Your API keys (⚠️ never commit)
```

💬 How to Use

Chat Interface (app.py)

Type anything describing an expense:

| You type | AI extracts |
|---|---|
| `paid 800 for the dentist yesterday` | ₹800 · Health & Medical · yesterday · dentist |
| `uber 240 this morning` | ₹240 · Transport · today · uber |
| `groceries 2100 last saturday` | ₹2100 · Groceries · last saturday · groceries |
| `netflix subscription 499` | ₹499 · Subscriptions · today · Netflix subscription |
| `coffee 120 rs` | ₹120 · Food & Dining · today · coffee |

*Dashboard

Click **📊 Open Dashboard →** to see:
- **KPI cards** — total spent, transaction count, average, top category
- **Daily trend line** — spending pattern over time
- **Category donut** — where your money goes
- **Monthly bars** — month-by-month comparison
- **Full table** — search, filter, and delete entries

🌐 Deploying for Free (Streamlit Cloud)

1. Push your project to a **GitHub repo** (make sure `secrets.toml` is in `.gitignore`)
2. Go to **https://share.streamlit.io**
3. Connect your GitHub repo
4. Set **Main file path** to `app.py`
5. Go to **Settings → Secrets** and add:
   ```
   GROQ_API_KEY = "gsk_your_key_here"
   ```
6. Click **Deploy** ✓

> Note: Streamlit Cloud uses ephemeral storage — `expenses.db` resets on redeploy.  
> For persistent cloud storage, swap SQLite for **Supabase** (free tier) — ask ExpenseBot to help you migrate!

 🔧 Deploying on Render (Persistent DB)

1. Create a **Render** account at render.com
2. New → **Web Service** → connect your repo
3. Set:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app.py --server.port $PORT --server.headless true`
4. Add environment variable: `GROQ_API_KEY = gsk_...`
5. The `expenses.db` file persists on Render's disk (add a persistent disk in settings)

🤖 Changing the AI Model

In `ai_extractor.py`, change the model name:

```python
model="llama-3.3-70b-versatile",   # Default — best accuracy
# model="llama-3.1-8b-instant",    # Faster, slightly less accurate
# model="gemma2-9b-it",            # Google's Gemma — also free on Groq
# model="mixtral-8x7b-32768",      # Mixtral — good for long context
```

All models are **free** on Groq's free tier.

 📦 Dependencies

| Package | Purpose |
|---|---|
| `streamlit` | Web UI for both chat and dashboard |
| `groq` | Free AI API client for expense extraction |
| `plotly` | Interactive charts on dashboard |
| `pandas` | Data manipulation for analytics |

---
❓ Troubleshooting

**"GROQ_API_KEY not set"**  
→ Make sure `.streamlit/secrets.toml` exists with your key, or set env var: `export GROQ_API_KEY=gsk_...`

**"groq package not installed"**  
→ Run: `pip install groq`

**"AI returned unexpected format"**  
→ Try again — occasionally the model hiccups. If it persists, check `ai_extractor.py` and verify your API key is valid.

**Charts are empty**  
→ Run `python seed_data.py` to add demo data, or add expenses via the chat first.

**App won't start**  
→ Make sure you activated your virtual environment: `source venv/bin/activate`
