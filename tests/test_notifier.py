import pytest
from datetime import date
from unittest.mock import AsyncMock, patch
from models import FlightResult
from notifier import format_flight_message, send_flight_alert


def test_format_flight_message():
    flight = FlightResult(
        airline="ryanair",
        origin="TLV",
        destination="FCO",
        departure_date=date(2025, 6, 14),
        price_gbp=89.99,
        booking_url="https://ryanair.com/book",
        flight_number="FR1234",
    )
    msg = format_flight_message(flight, job_name="Summer Europe", job_id=3)
    assert "FR1234" in msg
    assert "Tel Aviv (TLV)" in msg
    assert "Rome Fiumicino (FCO)" in msg
    assert "89.99" in msg
    assert "https://ryanair.com/book" in msg
    assert "Summer Europe" in msg or "#3" in msg


@pytest.mark.asyncio
async def test_send_flight_alert_calls_telegram():
    flight = FlightResult(
        airline="ryanair",
        origin="TLV",
        destination="FCO",
        departure_date=date(2025, 6, 14),
        price_gbp=89.99,
        booking_url="https://ryanair.com/book",
        flight_number="FR1234",
    )

    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock()

    await send_flight_alert(mock_bot, chat_id="123", flight=flight, job_name="Test", job_id=1)
    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == "123"
    assert "FR1234" in call_kwargs["text"]
