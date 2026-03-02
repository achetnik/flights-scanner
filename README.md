# ✈️ Flights Scanner

A Telegram-managed flight monitoring system that scrapes **Ryanair**, **EasyJet**, and **Wizzair** on a configurable schedule, detects available flights to your chosen destinations, and sends instant Telegram alerts with direct booking links.

Designed for **2 adults with 10 kg bags**. Runs 24/7 on Railway (free tier) — no Mac needed.

---

## Features

- **Multi-job support** — run multiple independent search jobs simultaneously, each with its own origin, destinations, airlines, dates, and check interval
- **Telegram-native UX** — create, pause, stop, and monitor jobs entirely from your phone
- **Smart deduplication** — same flight won't alert again within 24 hours
- **Direct booking links** — every alert includes a pre-filled link to the airline's booking page
- **Resilient scraping** — one airline failing doesn't affect the others
- **Always-on** — deployed to Railway cloud, runs continuously

---

## System Architecture

```mermaid
flowchart LR
    subgraph Railway["Railway Cloud"]
        BOT["Telegram Bot\n/newjob /listjobs\n/stop /pause /resume"]
        SCH["APScheduler\nper-job interval"]
        RUN["Job Runner\nscrape + dedup + alert"]
        DB[("SQLite\nJobs + SeenFlights")]
    end

    subgraph Airlines["Airline APIs"]
        RY["Ryanair\nAvailability API"]
        EJ["EasyJet\nRoute Pricing API"]
        WZ["Wizzair\nTimetable API\nPlaywright cookie"]
    end

    YOU["You on Telegram"] <-->|commands + alerts| BOT
    BOT --> DB
    BOT --> SCH
    SCH -->|every N min| RUN
    RUN --> DB
    RUN --> RY
    RUN --> EJ
    RUN --> WZ
```

---

## Data Flow

```mermaid
flowchart TD
    U([👤 You on Telegram]) -->|/newjob| B[Telegram Bot]
    B -->|wizard Q&A| B
    B -->|save config| DB[(SQLite\nJobs DB)]
    B -->|register| S[APScheduler]

    S -->|every N minutes| R[Job Runner]
    R -->|per airline| SC{Scrapers}
    SC -->|httpx GET| RY[Ryanair API]
    SC -->|httpx GET| EJ[EasyJet API]
    SC -->|Playwright cookie\n+ httpx POST| WZ[Wizzair API]

    RY -->|flights| R
    EJ -->|flights| R
    WZ -->|flights| R

    R -->|fingerprint check| DB
    DB -->|seen under 24h ago| SKIP[Skip]
    DB -->|new or expired| ALERT[Send Alert]
    ALERT -->|mark seen| DB
    ALERT -->|Telegram message| U
```

---

## Job Lifecycle

```mermaid
stateDiagram-v2
    [*] --> ACTIVE : /newjob complete

    ACTIVE --> PAUSED : /pausejob
    PAUSED --> ACTIVE : /resumejob

    ACTIVE --> STOPPED : /stopjob
    PAUSED --> STOPPED : /stopjob

    ACTIVE --> ACTIVE : scrape and alert on each tick

    STOPPED --> [*]
```

---

## Deduplication Logic

```mermaid
flowchart LR
    F[FlightResult] -->|SHA-256 of\nairline+flight_no\n+date+route| FP[fingerprint]
    FP --> Q{In seen_flights with\nlast_alerted_at >= now - 24h?}
    Q -->|Yes| SKIP[Skip — already alerted]
    Q -->|No| SEND[Send Telegram alert]
    SEND --> UPSERT[Upsert seen_flights\nrow with now]
```

---

## Telegram Commands

| Command | Description |
|---|---|
| `/newjob` | Start a guided wizard to create a new search job |
| `/listjobs` | Show all jobs with status and last run time |
| `/pausejob <id>` | Pause a job (keeps config, stops checking) |
| `/resumejob <id>` | Resume a paused job |
| `/stopjob <id>` | Permanently stop a job |
| `/status` | Show system health — active/paused job counts, UTC time |
| `/cancel` | Cancel an in-progress /newjob wizard |

### /newjob wizard

```mermaid
sequenceDiagram
    participant U as You
    participant B as Bot

    U->>B: /newjob
    B->>U: What's your origin airport? (e.g. TLV)
    U->>B: TLV
    B->>U: Destination(s)? (e.g. FCO BCN AMS)
    U->>B: FCO BCN
    B->>U: Airlines? 1.Ryanair 2.EasyJet 3.Wizzair 4.All
    U->>B: 4
    B->>U: Date range? (e.g. 2025-06-01 to 2025-08-31)
    U->>B: June to August 2025
    B->>U: Check every how many minutes? (default: 30)
    U->>B: 60
    B->>U: Job name? (or /skip)
    U->>B: Summer Europe
    B->>U: ✅ Job #3 created — TLV→FCO,BCN · All airlines · checking every 60 min
```

---

## Notification Format

When a new flight is found, you receive:

```
🚀 New flight found! [Summer Europe #3]
TLV → FCO | Ryanair FR1234
📅 Jun 14, 2025
💰 €89.99/person — 2 adults, 10kg bags
[Book now →](https://www.ryanair.com/...)
```

---

## Project Structure

```
flights-scanner/
├── main.py              # FastAPI app — webhook, lifespan, handler registration
├── models.py            # Pydantic models: JobConfig, FlightResult
├── database.py          # SQLModel tables: Job, SeenFlight, JobStatus
├── notifier.py          # Telegram message formatting and sending
├── job_runner.py        # Core loop: scrape → dedup → alert
├── scheduler.py         # APScheduler: per-job interval scheduling
├── scrapers/
│   ├── base.py          # Abstract BaseScraper interface
│   ├── ryanair.py       # Ryanair internal availability API (httpx)
│   ├── easyjet.py       # EasyJet route pricing API (httpx)
│   ├── wizzair.py       # Wizzair timetable API (Playwright cookie + httpx)
│   └── registry.py      # get_scraper("ryanair") → RyanairScraper()
├── bot/
│   ├── wizard.py        # /newjob ConversationHandler + parsing helpers
│   └── handlers.py      # /listjobs /stopjob /pausejob /resumejob /status
├── tests/               # 33 tests (pytest + pytest-asyncio)
├── requirements.txt
├── railway.toml         # Railway deployment config
└── .env.example         # Environment variable template
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web framework | FastAPI + uvicorn |
| Telegram bot | python-telegram-bot v21 (async, webhook mode) |
| Scraping | Playwright (Chromium) + httpx |
| Scheduler | APScheduler (AsyncIOScheduler) |
| Database | SQLite via SQLModel |
| Deployment | Railway (free tier, always-on) |
| Testing | pytest + pytest-asyncio (33 tests) |

---

## Setup & Deployment

### 1. Get Telegram credentials

1. Message **@BotFather** on Telegram → `/newbot` → copy the token
2. Message **@userinfobot** → copy your chat ID

### 2. Deploy to Railway

```bash
brew install railway
railway login
railway init
railway variables set TELEGRAM_BOT_TOKEN=your_token_here
railway variables set TELEGRAM_CHAT_ID=your_chat_id_here
railway variables set DATABASE_URL=sqlite:///./flights.db
railway up
```

After deploy, Railway gives you a public URL (e.g. `https://flights-scanner-production.up.railway.app`):

```bash
railway variables set WEBHOOK_URL=https://flights-scanner-production.up.railway.app
railway up
```

### 3. Add persistent storage (Railway dashboard)

Service → **+ Add Volume** → mount at `/app`

This ensures `flights.db` survives redeploys.

### 4. Verify

```bash
curl https://your-app.railway.app/health
# → {"status":"ok"}
```

Then open Telegram and send `/status` to your bot.

---

## Local Development

```bash
git clone https://github.com/fabiomantel/flights-scanner
cd flights-scanner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

uvicorn main:app --reload --port 8000
```

Run tests:

```bash
pytest tests/ -v
```

---

## Adding a New Airline

1. Create `scrapers/myairline.py` extending `BaseScraper` with `airline_name = "myairline"` and implement `search()`
2. Register it in `scrapers/registry.py`
3. Add tests in `tests/test_myairline_scraper.py`

That's it — the wizard, job runner, and scheduler pick it up automatically.

---

## License

MIT
