import pytest
from bot.wizard import parse_airlines, parse_iata_list, parse_date_range
from datetime import date


def test_parse_iata_list():
    assert parse_iata_list("TLV FCO BCN") == ["TLV", "FCO", "BCN"]
    assert parse_iata_list("tlv, fco") == ["TLV", "FCO"]
    assert parse_iata_list("FCO") == ["FCO"]


def test_parse_airlines_all():
    assert set(parse_airlines("4")) == {"ryanair", "easyjet", "wizzair"}
    assert set(parse_airlines("all")) == {"ryanair", "easyjet", "wizzair"}


def test_parse_airlines_single():
    result = parse_airlines("1")
    assert result == ["ryanair"]


def test_parse_airlines_multiple():
    result = parse_airlines("1 2")
    assert set(result) == {"ryanair", "easyjet"}


def test_parse_date_range_iso():
    start, end = parse_date_range("2025-06-01 to 2025-08-31")
    assert start == date(2025, 6, 1)
    assert end == date(2025, 8, 31)


def test_parse_date_range_natural():
    start, end = parse_date_range("June to August 2025")
    assert start == date(2025, 6, 1)
    assert end == date(2025, 8, 31)


def test_parse_date_range_invalid_raises():
    with pytest.raises(ValueError):
        parse_date_range("not a date")
