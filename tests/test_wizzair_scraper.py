import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock
from models import JobConfig, FlightResult
from scrapers.wizzair import WizzairScraper

MOCK_WIZZAIR_RESPONSE = {
    "outboundFlights": [
        {
            "departureStation": "TLV",
            "arrivalStation": "FCO",
            "departureDates": ["2025-06-14T06:00:00"],
            "price": {"amount": 75.0, "currencyCode": "EUR"},
            "flightNumbers": ["W62345"],
        }
    ]
}


@pytest.mark.asyncio
async def test_wizzair_parses_flights():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["wizzair"],
        date_from=date(2025, 6, 1),
        date_to=date(2025, 6, 30),
    )

    with patch.object(WizzairScraper, "_get_session_cookie", new_callable=AsyncMock) as mock_cookie, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_cookie.return_value = "mock_wdc_cookie"
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_WIZZAIR_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert len(flights) == 1
    assert flights[0].airline == "wizzair"
    assert flights[0].price_eur == 75.0
    assert flights[0].departure_date == date(2025, 6, 14)
    assert "wizzair.com" in flights[0].booking_url
