# Flight Scanner — Design Document
Date: 2026-03-02

## Overview

A flight monitoring system that scrapes airline websites on a schedule, detects new available flights to configured destinations, and sends Telegram notifications with direct booking links. Supports multiple independent search jobs, each with its own configuration, managed entirely via Telegram bot commands.

## Goals

- Monitor multiple airlines for flights matching user-defined search criteria
- Send Telegram notifications with direct purchase links when matching flights are found
- Allow multiple independent search jobs (different origins, destinations, dates, airlines)
- Run reliably on a free cloud server (Railway) — always-on, no Mac needed
- Default passenger config: 2 adults, 10kg bags per person

## Architecture

```
┌─────────────────────────────────────────────┐
│          Cloud Server (Railway)              │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │        Telegram Bot (dual role)      │    │
│  │  Commands:  /newjob  /listjobs       │    │
│  │             /stopjob /pausejob       │    │
│  │  Notifications: flight alerts        │    │
│  └──────────┬──────────────────────────┘    │
│             │                                │
│  ┌──────────▼──────────────────────────┐    │
│  │         Job Manager                 │    │
│  │  (APScheduler — one entry per job)  │    │
│  └──────────┬──────────────────────────┘    │
│             │ runs each job on its interval  │
│  ┌──────────▼──────────────────────────┐    │
│  │      Scraper Engine (Playwright)    │    │
│  │  scrapers/ryanair.py                │    │
│  │  scrapers/easyjet.py                │    │
│  │  scrapers/wizzair.py                │    │
│  └──────────┬──────────────────────────┘    │
│             │                                │
│  ┌──────────▼──────────────────────────┐    │
│  │          SQLite DB                  │    │
│  │  jobs table: config per job         │    │
│  │  seen_flights table: dedup cache    │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

## Components

### 1. Telegram Bot (dual-role)
- **Notification channel:** sends flight alerts with booking links
- **Management interface:** handles slash commands to create/manage jobs
- Library: `python-telegram-bot` v21 (async)
- Runs as a webhook via FastAPI on Railway

### 2. Job Manager
- `APScheduler` (AsyncIOScheduler) runs each job on its configured interval
- Jobs persist in SQLite — survive server restarts
- New jobs from Telegram are immediately added to the scheduler

### 3. Scraper Engine
- `playwright` (Chromium, headless) for JS-rendered airline sites
- One module per airline: `scrapers/ryanair.py`, `scrapers/easyjet.py`, `scrapers/wizzair.py`
- Each scraper: search with job params → extract flight list → return structured results
- Resilience: try/except per airline, 3 retries with 5s delay, failures logged but non-fatal

### 4. SQLite Database (via SQLModel)
**`jobs` table:**
- id, name, status (active/paused/stopped)
- origin (IATA code), destinations (JSON list)
- airlines (JSON list), date_from, date_to
- passengers (default 2), bags_kg (default 10)
- check_interval_minutes, created_at, last_run_at

**`seen_flights` table:**
- job_id, flight_fingerprint (hash of airline+route+date+flight_number)
- first_seen_at, last_alerted_at
- Deduplication: same flight not re-alerted within 24 hours

## Telegram Bot Commands

| Command | Description |
|---|---|
| `/newjob` | Start guided wizard to create a new search job |
| `/listjobs` | Show all jobs with status and last run time |
| `/stopjob <id>` | Permanently stop a job |
| `/pausejob <id>` | Pause a job (keep config, stop checking) |
| `/resumejob <id>` | Resume a paused job |
| `/status` | Show system health and next scheduled runs |

### /newjob wizard flow:
```
You:  /newjob
Bot:  What's your origin airport? (e.g. TLV)
You:  TLV
Bot:  Destination(s)? Space-separated IATA codes (e.g. FCO BCN AMS)
You:  FCO BCN
Bot:  Airlines to check? Reply with numbers:
      1. Ryanair  2. EasyJet  3. Wizzair  4. All
You:  4
Bot:  Date range? (e.g. 2025-06-01 to 2025-08-31)
You:  2025-06-01 to 2025-08-31
Bot:  Check every how many minutes? (default: 30)
You:  60
Bot:  Job name? (optional, for your reference)
You:  Summer Europe
Bot:  ✅ Job #3 "Summer Europe" created!
      TLV → FCO, BCN | All airlines
      Dates: Jun 1 – Aug 31 | 2 adults, 10kg bags
      Checking every 60 minutes. First run in ~60 min.
```

## Notification Format

```
🚀 New flight found! [Summer Europe #3]
TLV → FCO | Ryanair FR1234
📅 Jun 14 → Jun 21 (7 nights)
💰 €89/person — 2 adults, 10kg bags
🔗 Book now → https://ryanair.com/...
```

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Bot framework | python-telegram-bot v21 |
| Scraping | Playwright (Chromium) |
| Scheduler | APScheduler (AsyncIOScheduler) |
| Database | SQLite via SQLModel |
| HTTP server | FastAPI (Railway webhook endpoint) |
| Deployment | Railway (free tier) |
| Config | Environment variables (.env) for secrets |

## Data Flow

1. User sends `/newjob` → bot wizard collects params → saved to `jobs` table
2. APScheduler adds cron entry for the job at its configured interval
3. On each tick: Playwright opens airline site, searches with job params
4. Extracted flights checked against `seen_flights` (keyed by `job_id + flight_fingerprint`)
5. New flights → format Telegram message → send with direct booking URL
6. Update `seen_flights` with timestamp for deduplication

## Project Structure

```
flights-scanner/
├── main.py                  # FastAPI app + bot initialization
├── scheduler.py             # APScheduler job management
├── database.py              # SQLite models (SQLModel)
├── notifier.py              # Telegram notification formatting & sending
├── bot/
│   ├── handlers.py          # Telegram command handlers
│   └── wizard.py            # Multi-step /newjob conversation
├── scrapers/
│   ├── base.py              # Abstract scraper interface
│   ├── ryanair.py           # Ryanair scraper
│   ├── easyjet.py           # EasyJet scraper
│   └── wizzair.py           # Wizzair scraper
├── models.py                # Pydantic models (Job, Flight)
├── requirements.txt
├── railway.toml             # Railway deployment config
└── .env.example             # Required env vars template
```

## Environment Variables

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...          # Your personal chat ID
DATABASE_URL=sqlite:///./flights.db
WEBHOOK_URL=https://your-app.railway.app
```

## Deployment (Railway)

- Railway provides always-on hosting on free tier
- Playwright requires buildpack: `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`
- `railway.toml` configures start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- SQLite file persists via Railway volume mount

## Error Handling

- Scraper failures: logged, Telegram admin alert if >3 consecutive failures for a job
- Bot webhook failures: FastAPI returns 200 to Telegram regardless to prevent retry storms
- DB errors: rollback transaction, log, continue
- Playwright crashes: restart browser context on next tick (stateless scraping)

## Future Extensions (out of scope now)

- Price threshold filter per job
- More airlines (Vueling, Transavia, Norwegian)
- Departure time preference (morning / evening)
- Round-trip vs one-way toggle
