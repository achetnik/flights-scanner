import calendar
import re
from datetime import date
from typing import List, Tuple

AIRLINE_OPTIONS = {
    "1": "ryanair",
    "2": "easyjet",
    "3": "wizzair",
}

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    # Abbreviations
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Conversation states
(
    ASK_ORIGIN,
    ASK_DESTINATIONS,
    ASK_AIRLINES,
    ASK_DATE_RANGE,
    ASK_INTERVAL,
    ASK_NAME,
    CONFIRM,
) = range(7)


def parse_iata_list(text: str) -> List[str]:
    codes = re.split(r"[\s,]+", text.strip())
    return [c.upper() for c in codes if c]


def parse_airlines(text: str) -> List[str]:
    text = text.strip().lower()
    if text in ("4", "all"):
        return list(AIRLINE_OPTIONS.values())
    codes = re.split(r"[\s,]+", text)
    result = []
    for c in codes:
        if c in AIRLINE_OPTIONS:
            result.append(AIRLINE_OPTIONS[c])
        elif c in AIRLINE_OPTIONS.values():
            result.append(c)
    return list(set(result)) if result else list(AIRLINE_OPTIONS.values())


def _lookup_month(name: str) -> int:
    """Resolve a month name or abbreviation to a month number (1-12)."""
    m = MONTH_MAP.get(name.lower())
    if m is None:
        raise ValueError(f"Unknown month: {name!r}")
    return m


def parse_date_range(text: str) -> Tuple[date, date]:
    """Parse a date-range string into (start, end) dates.

    Supported formats:
      • 2025-06-01 to 2025-08-31    (ISO)
      • 01/06/2025 to 31/08/2025     (DD/MM/YYYY)
      • June to August 2025          (natural, full months)
      • Jun to Aug 2025              (abbreviated months)
      • March 2026                   (single month)
      • Mar 2026                     (single month, abbreviated)
    """
    text = text.strip()

    # --- ISO: "2025-06-01 to 2025-08-31" ---
    iso_match = re.search(
        r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE
    )
    if iso_match:
        start = date.fromisoformat(iso_match.group(1))
        end = date.fromisoformat(iso_match.group(2))
        return start, end

    # --- DD/MM/YYYY: "08/03/2026 to 29/03/2026" or "08-03-2026 to 29-03-2026" ---
    dmy_match = re.search(
        r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\s+to\s+(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})",
        text, re.IGNORECASE,
    )
    if dmy_match:
        d1, m1, y1 = int(dmy_match.group(1)), int(dmy_match.group(2)), int(dmy_match.group(3))
        d2, m2, y2 = int(dmy_match.group(4)), int(dmy_match.group(5)), int(dmy_match.group(6))
        start = date(y1, m1, d1)
        end = date(y2, m2, d2)
        return start, end

    # --- Natural range: "June to August 2025" / "Jun to Aug 2025" ---
    natural_match = re.search(
        r"([a-z]+)\s+to\s+([a-z]+)\s+(\d{4})", text, re.IGNORECASE
    )
    if natural_match:
        m1 = MONTH_MAP.get(natural_match.group(1).lower())
        m2 = MONTH_MAP.get(natural_match.group(2).lower())
        year = int(natural_match.group(3))
        if m1 and m2:
            start = date(year, m1, 1)
            last_day = calendar.monthrange(year, m2)[1]
            end = date(year, m2, last_day)
            return start, end

    # --- Single month: "March 2026" / "Mar 2026" ---
    single_match = re.search(r"([a-z]+)\s+(\d{4})", text, re.IGNORECASE)
    if single_match:
        m = MONTH_MAP.get(single_match.group(1).lower())
        year = int(single_match.group(2))
        if m:
            start = date(year, m, 1)
            last_day = calendar.monthrange(year, m)[1]
            end = date(year, m, last_day)
            return start, end

    raise ValueError(
        f"Cannot parse date range: {text!r}. "
        "Use 'YYYY-MM-DD to YYYY-MM-DD', 'Month to Month YYYY', or 'Month YYYY'"
    )


async def newjob_start(update, context):
    await update.message.reply_text(
        "Let's create a new flight search job!\n\n"
        "What's your *origin airport*? (IATA code, e.g. TLV)",
        parse_mode="Markdown",
    )
    return ASK_ORIGIN


async def ask_destinations(update, context):
    context.user_data["origin"] = update.message.text.strip().upper()
    await update.message.reply_text(
        "Destination(s)? Space or comma-separated IATA codes (e.g. `FCO BCN AMS`)",
        parse_mode="Markdown",
    )
    return ASK_DESTINATIONS


async def ask_airlines(update, context):
    context.user_data["destinations"] = parse_iata_list(update.message.text)
    await update.message.reply_text(
        "Which airlines to check?\n"
        "1. Ryanair\n2. EasyJet\n3. Wizzair\n4. All\n\n"
        "Reply with number(s), e.g. `1 2` or `4` for all",
        parse_mode="Markdown",
    )
    return ASK_AIRLINES


async def ask_date_range(update, context):
    context.user_data["airlines"] = parse_airlines(update.message.text)
    await update.message.reply_text(
        "Date range? (e.g. `2025-06-01 to 2025-08-31`, `June to August 2025`, or `June 2025`)",
        parse_mode="Markdown",
    )
    return ASK_DATE_RANGE


async def ask_interval(update, context):
    try:
        start, end = parse_date_range(update.message.text)
    except ValueError as e:
        await update.message.reply_text(f"Couldn't parse that date. {e}\nTry again:")
        return ASK_DATE_RANGE
    context.user_data["date_from"] = start
    context.user_data["date_to"] = end
    await update.message.reply_text(
        "Check every how many minutes? (default: 30, min: 15)",
        parse_mode="Markdown",
    )
    return ASK_INTERVAL


async def ask_name(update, context):
    text = update.message.text.strip()
    try:
        interval = max(15, int(text))
    except ValueError:
        interval = 30
    context.user_data["check_interval_minutes"] = interval
    await update.message.reply_text(
        "Job name? (optional — for your reference, e.g. 'Summer Rome')\n"
        "Or send /skip to use a default name.",
        parse_mode="Markdown",
    )
    return ASK_NAME


async def confirm_job(update, context):
    text = update.message.text.strip()
    if text.lower() != "/skip":
        context.user_data["name"] = text

    data = context.user_data
    name = data.get("name", f"{data['origin']}→{','.join(data['destinations'])}")
    msg = (
        f"Creating job: *{name}*\n"
        f"Route: {data['origin']} → {', '.join(data['destinations'])}\n"
        f"Airlines: {', '.join(data['airlines'])}\n"
        f"Dates: {data['date_from']} to {data['date_to']}\n"
        f"Interval: every {data['check_interval_minutes']} min\n"
        f"Passengers: 2 adults, 10kg bags"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return await _save_job(update, context)


async def _save_job(update, context):
    import json
    from sqlmodel import Session
    from database import Job, get_engine

    data = context.user_data
    name = data.get("name")
    engine = get_engine()
    with Session(engine) as session:
        job = Job(
            name=name,
            origin=data["origin"],
            destinations=json.dumps(data["destinations"]),
            airlines=json.dumps(data["airlines"]),
            date_from=data["date_from"],
            date_to=data["date_to"],
            check_interval_minutes=data["check_interval_minutes"],
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    from scheduler import add_job_to_scheduler
    add_job_to_scheduler(job_id, data["check_interval_minutes"])

    await update.message.reply_text(
        f"Job #{job_id} created and running!",
        parse_mode="Markdown",
    )
    context.user_data.clear()
    from telegram.ext import ConversationHandler
    return ConversationHandler.END


async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("Job creation cancelled.")
    from telegram.ext import ConversationHandler
    return ConversationHandler.END
