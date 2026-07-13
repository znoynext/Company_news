from datetime import UTC, datetime
from decimal import Decimal

from dividend_monitor.dividends import classify_dividend_event
from dividend_monitor.models import Publication
from dividend_monitor.runner import format_message

SOURCE_URL = "https://example.com/dividends"


def test_recommended_dividend_event_extracts_amount_period_and_dates() -> None:
    text = (
        "Совет директоров рекомендовал дивиденды за 2025 год в размере "
        "12,50 рубля на одну обыкновенную акцию. Общее собрание 20.06.2026. "
        "Дата закрытия реестра 01.07.2026."
    )

    event = classify_dividend_event(text, SOURCE_URL)

    assert event is not None
    assert event.status == "recommended"
    assert event.event_type == "recommendation"
    assert event.amount_per_share == Decimal("12.50")
    assert event.share_type == "ordinary"
    assert event.period == "2025 год"
    assert event.general_meeting_date == datetime(2026, 6, 20, tzinfo=UTC)
    assert event.register_close_date == datetime(2026, 7, 1, tzinfo=UTC)


def test_dividend_statuses_and_policy_change_are_separate() -> None:
    approved = classify_dividend_event("approved dividend for FY 2025", SOURCE_URL)
    cancelled = classify_dividend_event("dividend payment cancelled", SOURCE_URL)
    paid = classify_dividend_event("dividend paid", SOURCE_URL)
    policy = classify_dividend_event("изменена дивидендная политика, dividends", SOURCE_URL)

    assert approved and approved.status == "approved"
    assert cancelled and cancelled.status == "cancelled"
    assert paid and paid.status == "paid"
    assert policy and policy.event_type == "policy_change"


def test_lsngp_keeps_rasbu_and_preferred_share_facts() -> None:
    text = (
        "Совет директоров рекомендовал дивиденды LSNGP. Чистая прибыль по РСБУ "
        "составила 100 млн рублей. Дивидендная база определена уставом. "
        "Выплата на привилегированные акции — 5 рублей на акцию."
    )

    event = classify_dividend_event(text, SOURCE_URL, ticker="LSNGP")

    assert event is not None
    assert event.rasbu_net_profit is not None
    assert event.dividend_base is not None
    assert event.preferred_share_payment is not None


def test_dividend_message_does_not_calculate_yield() -> None:
    event = classify_dividend_event("approved dividend for FY 2025", SOURCE_URL)
    assert event is not None
    publication = Publication(
        source_id="fixture",
        company="Company",
        ticker="TEST",
        category="dividend",
        title="Dividend approved",
        description="",
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        url=SOURCE_URL,
        dividend_event=event,
    )

    message = format_message(publication)

    assert "💰 Company — дивиденды" in message
    assert "доходность" not in message.casefold()
    assert "цена" not in message.casefold()
