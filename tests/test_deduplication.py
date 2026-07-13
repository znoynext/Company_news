from datetime import UTC, datetime

from dividend_monitor.deduplication import deduplication_id, is_new, mark_sent
from dividend_monitor.models import MonitorState, Publication


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
