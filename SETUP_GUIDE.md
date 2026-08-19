# 🏀🏈⚾🏒 Sports Betting Bot — Setup Guide

> Complete setup from zero. No coding experience needed. Follow every step in order.

\---

## What You're Installing

|Tool|What it does|
|-|-|
|Python|Runs the bot|
|PostgreSQL|Database that stores all the data|
|Redis|Fast cache for live data|
|The bot itself|All the code in this folder|

\---

## STEP 1: Install Python

1. Go to **https://www.python.org/downloads/**
2. Click the big yellow "Download Python 3.11.x" button
3. Run the installer
4. ⚠️ **IMPORTANT**: Check the box that says **"Add Python to PATH"** before clicking Install
5. Open a Terminal (Mac) or Command Prompt (Windows) and type:

```
   python --version
   ```

   You should see `Python 3.11.x`. If you do, Python is installed ✅

\---

## STEP 2: Install PostgreSQL (the database)

**Mac:**

1. Go to **https://postgresapp.com/**
2. Download and install Postgres.app
3. Open the app and click "Initialize"
4. Click "Start" to start the database

**Windows:**

1. Go to **https://www.postgresql.org/download/windows/**
2. Download the installer and run it
3. During install: set a password (write it down — you'll need it)
4. Leave port as 5432 (default)
5. Finish the install

**Create your database:**
Open Terminal/Command Prompt and type:

```bash
# Mac:
/Applications/Postgres.app/Contents/Versions/latest/bin/psql -c "CREATE DATABASE sportsbetting;"

# Windows (in the psql command line, password you set above):
psql -U postgres
CREATE DATABASE sportsbetting;
\\q
```

\---

## STEP 3: Install Redis (fast cache)

**Mac:**

```bash
brew install redis
brew services start redis
```

(Install Homebrew first if needed: https://brew.sh)

**Windows:**

1. Go to **https://github.com/microsoftarchive/redis/releases**
2. Download `Redis-x64-xxx.msi` and install
3. Redis will start automatically as a Windows service

\---

## STEP 4: Set Up the Bot

Open Terminal/Command Prompt and navigate to this folder:

```bash
cd path/to/sports-betting-bot
# Example Mac: cd /Users/yourname/Downloads/sports-betting-bot
# Example Windows: cd C:\\Users\\yourname\\Downloads\\sports-betting-bot
```

Install all required packages:

```bash
pip install -r requirements.txt
```

This will take 2-3 minutes. That's normal.

\---

## STEP 5: Get Your API Keys

### OddsAPI ($50/mo — required for live odds)

1. Go to **https://the-odds-api.com**
2. Click "Start Free Trial" → Sign up
3. Go to your dashboard → copy your API key

### Reddit API (Free — required for Reddit monitoring)

1. Go to **https://www.reddit.com/prefs/apps** (log in to Reddit first)
2. Scroll to the bottom → click "Create app"
3. Fill in:

   * Name: `SportsBettingBot`
   * Select: **script**
   * Redirect URI: `http://localhost`
4. Click "Create app"
5. You'll see a box with a short string under the app name — that's your **Client ID**
6. The "secret" field is your **Client Secret**

### Anthropic API (for AI analysis — Phase 4)

1. Go to **https://console.anthropic.com**
2. Sign up → go to API Keys → create a key

\---

## STEP 6: Configure Your Keys

1. Find the file called `.env.example` in this folder
2. Make a copy of it and rename the copy to `.env`
3. Open `.env` with any text editor (Notepad on Windows, TextEdit on Mac)
4. Fill in your values:

```
DATABASE\_URL=postgresql://postgres:YOUR\_PASSWORD@localhost:5432/sportsbetting
ODDS\_API\_KEY=paste\_your\_odds\_api\_key\_here
REDDIT\_CLIENT\_ID=paste\_your\_reddit\_client\_id\_here
REDDIT\_CLIENT\_SECRET=paste\_your\_reddit\_client\_secret\_here
ANTHROPIC\_API\_KEY=paste\_your\_anthropic\_key\_here
```

Replace `YOUR\_PASSWORD` with the PostgreSQL password you set in Step 2.

\---

## STEP 7: Initialize the Database

This creates all the tables in your database (run only once):

```bash
python database/init\_db.py
```

You should see:

```
✅ Database connection successful.
✅ All database tables created successfully.
✅ Database initialized. Ready to collect data.
```

\---

## STEP 8: Run the Bot

Start the full data collection bot:

```bash
python scheduler/scheduler.py
```

On first run, it will:

1. Load all teams and player rosters (ESPN) — \~2 min
2. Load current odds (OddsAPI) — \~30 seconds
3. Load news from all RSS feeds — \~1 min
4. Load Reddit posts — \~2 min
5. Load contract data — \~3 min

Then it runs continuously, updating every few minutes automatically.

\---

## STEP 9: Test It's Working

Open a new Terminal window and run:

```bash
python tests/test\_data.py
```

This will show you how many records are in each table.

\---

## What's Next

|Phase|What it adds|
|-|-|
|✅ Phase 1 (complete)|Data pipeline — all 4 sports, all sources|
|🔜 Phase 2|Twitter/X integration for real-time beat reporter alerts|
|🔜 Phase 3|Head-to-head stats, referee data, weather for outdoor sports|
|🔜 Phase 4|AI analysis — Claude analyzes every game and outputs bet signals|
|🔜 Phase 5|Dashboard — visual interface to review picks|

\---

## Common Issues

**"command not found: python"** → Try `python3` instead of `python`

**"Connection refused" (database error)** → PostgreSQL isn't running. Start it (Step 2)

**"No module named X"** → Run `pip install -r requirements.txt` again

**Odds API returns empty** → Check your key in `.env` is correct and not expired

\---

## File Structure (what each file does)

```
sports-betting-bot/
├── config/
│   └── settings.py          ← All config and API keys loader
├── database/
│   ├── models.py            ← All database table definitions
│   └── init\_db.py           ← Run once to create tables
├── data\_ingestion/
│   ├── official/
│   │   ├── espn\_client.py   ← Teams, players, scores, injuries (free)
│   │   └── odds\_client.py   ← Live odds and line movement ($50/mo)
│   ├── soft/
│   │   ├── reddit\_client.py ← Reddit rumors and news (free)
│   │   └── news\_client.py   ← RSS news feeds (free)
│   └── contracts/
│       └── contract\_client.py ← Salary and incentive data (free scrape)
├── scheduler/
│   └── scheduler.py         ← Runs everything automatically
├── requirements.txt         ← All Python packages needed
├── .env.example             ← Template for your API keys
└── SETUP\_GUIDE.md           ← This file
```

