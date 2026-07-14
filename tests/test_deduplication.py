from datetime import UTC, datetime

from dividend_monitor.deduplication import (
    cleanup_old_state,
    deduplication_id,
    is_new,
    mark_sent,
    normalize_url,
    sent_item_identity,
)
from dividend_monitor.models import MonitorState, Publication, SentItem


def publication() -> Publication:
    return Publication(
        company="Сбербанк",
        ticker="SBER",
        category="news",
        title="Новость",
        description="Описание",
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        url="https://example.invalid/news/1",
        source_id="fixture",
        external_id="id-1",
    )


def test_same_external_id_is_not_sent_twice() -> None:
    state = MonitorState()
    item = publication()
    assert is_new(item, state)
    mark_sent(item, state)
    assert not is_new(item, state)
    assert state.sent_items[0].deduplication_id == deduplication_id(item)


def test_external_id_identity_ignores_title_and_time_changes() -> None:
    state = MonitorState()
    first = publication()
    changed = first.model_copy(
        update={"title": "Corrected title", "published_at": datetime(2026, 7, 14, tzinfo=UTC)}
    )

    mark_sent(first, state)

    assert not is_new(changed, state)


def test_legacy_saved_item_rebuilds_the_same_v2_identity() -> None:
    current = publication()
    saved = SentItem(
        deduplication_id="legacy",
        company=current.company,
        title=current.title,
        url=str(current.url),
        source_id=current.source_id,
        publication_id=current.external_id,
        published_at=current.published_at,
        sent_at=current.published_at,
    )

    assert sent_item_identity(saved) == deduplication_id(current)


def test_normalize_url_removes_tracking_and_preserves_meaningful_query() -> None:
    assert (
        normalize_url("HTTPS://Example.COM/report/123/?utm_source=rss&b=2&fbclid=x&a=1#section")
        == "https://example.com/report/123?a=1&b=2"
    )
    assert normalize_url("https://example.com/?utm_medium=email#top") == "https://example.com/"


def test_similar_official_reports_with_different_urls_are_not_duplicates() -> None:
    first = publication()
    second = first.model_copy(
        update={
            "external_id": "id-2",
            "url": "https://example.invalid/reports/2",
            "title": "Финансовые результаты",
        }
    )
    state = MonitorState()
    mark_sent(first, state)
    assert is_new(second, state)


def test_mark_sent_preserves_fingerprint_source_and_telegram_status() -> None:
    state = MonitorState()
    item = publication()
    mark_sent(item, state, telegram_message_status="sent")
    saved = state.sent_items[0]
    assert saved.fingerprint == deduplication_id(item)
    assert saved.source_id == "fixture"
    assert saved.publication_id == "id-1"
    assert saved.source_url == str(item.url)
    assert saved.telegram_message_status == "sent"


def test_cleanup_old_state_keeps_history_for_180_days() -> None:
    now = datetime(2026, 7, 13, tzinfo=UTC)
    state = MonitorState(
        sent_items=[
            SentItem(
                deduplication_id="old",
                company="Company",
                title="Old",
                url=None,
                published_at=now,
                sent_at=now.replace(year=2025, month=12, day=1),
            ),
            SentItem(
                deduplication_id="recent",
                company="Company",
                title="Recent",
                url=None,
                published_at=now,
                sent_at=now,
            ),
        ]
    )
    assert cleanup_old_state(state, now) == 1
    assert [item.deduplication_id for item in state.sent_items] == ["recent"]
