"""Telegram conversation wizard for /daytrip — Extreme Day Trips search."""

from telegram.ext import ConversationHandler

from bot.wizard import parse_airlines, parse_date_range
from daytrips import format_day_trip_telegram, search_day_trips

# Conversation states
DT_ASK_ORIGIN, DT_ASK_DATE_RANGE, DT_ASK_AIRLINES = range(3)

MAX_RESULTS = 20
MAX_MESSAGE_LEN = 4000  # leave headroom below Telegram's 4096 limit


async def daytrip_start(update, context):
    """Entry point for /daytrip — ask for home airport."""
    await update.message.reply_text(
        "✈️ *Extreme Day Trips*\n\n"
        "What's your *home airport*? (IATA code, e.g. BRS)",
        parse_mode="Markdown",
    )
    return DT_ASK_ORIGIN


async def dt_ask_date_range(update, context):
    """Store origin, ask for date range."""
    context.user_data["dt_origin"] = update.message.text.strip().upper()
    await update.message.reply_text(
        "Date range?\n"
        "(e.g. `2026-06-01 to 2026-06-30`, `June to August 2026`, or `March 2026`)",
        parse_mode="Markdown",
    )
    return DT_ASK_DATE_RANGE


async def dt_ask_airlines(update, context):
    """Store dates, ask for airlines."""
    try:
        start, end = parse_date_range(update.message.text)
    except ValueError as e:
        await update.message.reply_text(
            f"Couldn't parse that date range. {e}\nTry again:"
        )
        return DT_ASK_DATE_RANGE

    context.user_data["dt_date_from"] = start
    context.user_data["dt_date_to"] = end
    await update.message.reply_text(
        "Which airlines to search?\n"
        "1. Ryanair\n2. EasyJet\n3. Wizzair\n4. Google Flights\n5. All\n\n"
        "Reply with number(s), e.g. `1 3` or `5` for all",
        parse_mode="Markdown",
    )
    return DT_ASK_AIRLINES


async def dt_run_search(update, context):
    """Parse airlines, run search, send results."""
    airlines = parse_airlines(update.message.text)
    origin = context.user_data["dt_origin"]
    date_from = context.user_data["dt_date_from"]
    date_to = context.user_data["dt_date_to"]

    await update.message.reply_text(
        f"🔍 Searching day trips from *{origin}*\n"
        f"📅 {date_from} to {date_to}\n"
        f"Airlines: {', '.join(a.title() for a in airlines)}\n\n"
        "This may take a minute…",
        parse_mode="Markdown",
    )

    results = await search_day_trips(
        origin=origin,
        date_from=date_from,
        date_to=date_to,
        airlines=airlines,
    )

    context.user_data.clear()

    if not results:
        await update.message.reply_text(
            "😔 No day trips found for those dates and airports.\n"
            "Try a wider date range or different origin.",
        )
        return ConversationHandler.END

    # Limit to top N results
    results = results[:MAX_RESULTS]
    header = f"🏆 *Top {len(results)} Day Trips from {origin}*\n\n"

    # Build messages, batching to stay under Telegram's 4096 char limit
    messages = []
    current = header
    for i, trip in enumerate(results, start=1):
        entry = format_day_trip_telegram(trip, i) + "\n\n"
        if len(current) + len(entry) > MAX_MESSAGE_LEN:
            messages.append(current)
            current = ""
        current += entry

    if current.strip():
        messages.append(current)

    for msg in messages:
        await update.message.reply_text(
            msg.strip(),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

    return ConversationHandler.END


async def dt_cancel(update, context):
    """Cancel the day trip wizard."""
    context.user_data.clear()
    await update.message.reply_text("Day trip search cancelled.")
    return ConversationHandler.END
