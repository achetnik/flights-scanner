"""Tests for the /daytrip Telegram conversation wizard."""

import pytest
from datetime import date, time
from unittest.mock import AsyncMock, MagicMock, patch

from models import FlightResult
from daytrips import DayTripResult, format_day_trip_telegram
from bot.daytrip_wizard import (
    DT_ASK_ORIGIN,
    DT_ASK_DATE_RANGE,
    DT_ASK_AIRLINES,
    daytrip_start,
    dt_ask_date_range,
    dt_ask_airlines,
    dt_run_search,
    dt_cancel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_update(text: str):
    """Create a minimal mocked Telegram Update with message text."""
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context():
    """Create a minimal mocked CallbackContext with user_data dict."""
    ctx = MagicMock()
    ctx.user_data = {}
    return ctx


def _flight(
    airline="ryanair",
    origin="BRS",
    destination="BCN",
    dep_date=date(2026, 6, 14),
    dep_time=None,
    arr_time=None,
    price=50.0,
    flight_number="FR1234",
):
    return FlightResult(
        airline=airline,
        origin=origin,
        destination=destination,
        departure_date=dep_date,
        departure_time=dep_time,
        arrival_time=arr_time,
        price_gbp=price,
        booking_url="https://example.com",
        flight_number=flight_number,
    )


# ---------------------------------------------------------------------------
# format_day_trip_telegram
# ---------------------------------------------------------------------------

class TestFormatDayTripTelegram:
    def test_basic_formatting(self):
        out = _flight(
            origin="BRS", destination="BCN",
            dep_date=date(2026, 6, 14),
            dep_time=time(7, 0), arr_time=time(10, 0),
            price=40.0,
        )
        ret = _flight(
            airline="wizzair",
            origin="BCN", destination="BRS",
            dep_date=date(2026, 6, 14),
            dep_time=time(18, 0), arr_time=time(21, 0),
            price=35.0,
        )
        trip = DayTripResult(outbound=out, return_flight=ret)
        text = format_day_trip_telegram(trip, 1)

        assert "Bristol (BRS) → Barcelona (BCN)" in text
        assert "#1" in text
        assert "07:00" in text
        assert "18:00" in text
        assert "75.00" in text
        assert "£" in text
        assert "Ryanair" in text
        assert "Wizzair" in text
        assert "✈️" in text
        assert "💰" in text
        assert "Book outbound" in text
        assert "Book return" in text
        assert "https://example.com" in text

    def test_missing_times_show_question_mark(self):
        out = _flight(dep_time=None, arr_time=None, price=10.0)
        ret = _flight(dep_time=None, arr_time=None, price=20.0)
        trip = DayTripResult(outbound=out, return_flight=ret)
        text = format_day_trip_telegram(trip, 5)

        assert "?" in text
        assert "#5" in text
        assert "30.00" in text


# ---------------------------------------------------------------------------
# Conversation handlers
# ---------------------------------------------------------------------------

class TestDaytripStart:
    @pytest.mark.asyncio
    async def test_prompts_for_airport(self):
        update = _make_update("/daytrip")
        context = _make_context()
        state = await daytrip_start(update, context)

        assert state == DT_ASK_ORIGIN
        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "home airport" in msg.lower() or "IATA" in msg


class TestDtAskDateRange:
    @pytest.mark.asyncio
    async def test_stores_origin_and_asks_dates(self):
        update = _make_update("BRS")
        context = _make_context()
        state = await dt_ask_date_range(update, context)

        assert state == DT_ASK_DATE_RANGE
        assert context.user_data["dt_origin"] == "BRS"
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_uppercases_origin(self):
        update = _make_update("  brs  ")
        context = _make_context()
        await dt_ask_date_range(update, context)
        assert context.user_data["dt_origin"] == "BRS"


class TestDtAskAirlines:
    @pytest.mark.asyncio
    async def test_stores_dates_and_asks_airlines(self):
        update = _make_update("2026-06-01 to 2026-06-30")
        context = _make_context()
        state = await dt_ask_airlines(update, context)

        assert state == DT_ASK_AIRLINES
        assert context.user_data["dt_date_from"] == date(2026, 6, 1)
        assert context.user_data["dt_date_to"] == date(2026, 6, 30)

    @pytest.mark.asyncio
    async def test_invalid_date_retries(self):
        update = _make_update("not a date")
        context = _make_context()
        state = await dt_ask_airlines(update, context)

        # Should stay in the same state and ask again
        assert state == DT_ASK_DATE_RANGE
        msg = update.message.reply_text.call_args[0][0]
        assert "parse" in msg.lower() or "try again" in msg.lower()

    @pytest.mark.asyncio
    async def test_natural_date_format(self):
        update = _make_update("June to August 2026")
        context = _make_context()
        state = await dt_ask_airlines(update, context)

        assert state == DT_ASK_AIRLINES
        assert context.user_data["dt_date_from"] == date(2026, 6, 1)
        assert context.user_data["dt_date_to"] == date(2026, 8, 31)

    @pytest.mark.asyncio
    async def test_single_month_format(self):
        update = _make_update("March 2026")
        context = _make_context()
        state = await dt_ask_airlines(update, context)

        assert state == DT_ASK_AIRLINES
        assert context.user_data["dt_date_from"] == date(2026, 3, 1)
        assert context.user_data["dt_date_to"] == date(2026, 3, 31)


class TestDtRunSearch:
    @pytest.mark.asyncio
    async def test_sends_results(self):
        out = _flight(
            origin="BRS", destination="BCN",
            dep_time=time(7, 0), arr_time=time(10, 0),
            price=40.0,
        )
        ret = _flight(
            airline="wizzair",
            origin="BCN", destination="BRS",
            dep_time=time(18, 0), arr_time=time(21, 0),
            price=35.0,
        )
        mock_results = [DayTripResult(outbound=out, return_flight=ret)]

        update = _make_update("5")
        context = _make_context()
        context.user_data["dt_origin"] = "BRS"
        context.user_data["dt_date_from"] = date(2026, 6, 1)
        context.user_data["dt_date_to"] = date(2026, 6, 30)

        with patch("bot.daytrip_wizard.search_day_trips", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_results
            from telegram.ext import ConversationHandler
            state = await dt_run_search(update, context)

        assert state == ConversationHandler.END
        # At least 2 calls: "Searching..." + results
        assert update.message.reply_text.call_count >= 2
        # Results message should contain the trip info
        all_text = " ".join(
            call[0][0] for call in update.message.reply_text.call_args_list
        )
        assert "BRS" in all_text
        assert "BCN" in all_text
        assert "75.00" in all_text

    @pytest.mark.asyncio
    async def test_no_results_message(self):
        update = _make_update("5")
        context = _make_context()
        context.user_data["dt_origin"] = "XYZ"
        context.user_data["dt_date_from"] = date(2026, 6, 1)
        context.user_data["dt_date_to"] = date(2026, 6, 30)

        with patch("bot.daytrip_wizard.search_day_trips", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            from telegram.ext import ConversationHandler
            state = await dt_run_search(update, context)

        assert state == ConversationHandler.END
        # "Searching..." + "No day trips found"
        assert update.message.reply_text.call_count == 2
        final_msg = update.message.reply_text.call_args_list[-1][0][0]
        assert "no day trips" in final_msg.lower() or "not found" in final_msg.lower() or "😔" in final_msg

    @pytest.mark.asyncio
    async def test_clears_user_data(self):
        update = _make_update("1")
        context = _make_context()
        context.user_data["dt_origin"] = "BRS"
        context.user_data["dt_date_from"] = date(2026, 6, 1)
        context.user_data["dt_date_to"] = date(2026, 6, 30)

        with patch("bot.daytrip_wizard.search_day_trips", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            await dt_run_search(update, context)

        assert context.user_data == {}


class TestDtCancel:
    @pytest.mark.asyncio
    async def test_cancel_clears_state(self):
        update = _make_update("/cancel")
        context = _make_context()
        context.user_data["dt_origin"] = "BRS"
        context.user_data["dt_date_from"] = date(2026, 6, 1)

        from telegram.ext import ConversationHandler
        state = await dt_cancel(update, context)

        assert state == ConversationHandler.END
        assert context.user_data == {}
        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "cancel" in msg.lower()
