from datetime import UTC, datetime
from pathlib import Path

import dividend_monitor.runner as runner_module
from dividend_monitor.github_models import GitHubModelsUnavailable
from dividend_monitor.models import (
    MonitorState,
    Publication,
    RunStatistics,
    SentItem,
    SourceConfig,
    SourcesConfig,
)
from dividend_monitor.runner import format_message, format_saved_item_test, format_test_message, run
from dividend_monitor.storage import JsonStateStorage


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, text: str) -> None:
        self.messages.append(text)


def test_runner_sends_fixture_once(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).parents[1]
    telegram = FakeTelegram()
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(
        runner_module,
        "load_sources",
        lambda _: SourcesConfig(
            version=1,
            sources=[
                SourceConfig(
                    id="local-fixture",
                    name="Local fixture",
                    type="fixture",
                    path="tests/fixtures/news.xml",
                    companies=["SBER"],
                    categories=["news"],
                )
            ],
        ),
    )
    first_statistics = RunStatistics()
    second_statistics = RunStatistics()
    first = run(root, telegram, state_path=state_path, run_statistics=first_statistics)
    second = run(root, telegram, state_path=state_path, run_statistics=second_statistics)
    assert len(telegram.messages) == 1
    assert len(first.sent_items) == 1
    assert len(second.sent_items) == 1
    assert first_statistics.model_dump() == {
        "sources_checked": 1,
        "successful": 1,
        "errors": 0,
        "new_publications": 1,
        "sent": 1,
        "duplicates": 0,
    }
    assert second_statistics.duplicates == 1
    assert "Сбербанк" in telegram.messages[0]


def test_source_failure_alert_is_sent_once_and_recovery_is_reported(
    tmp_path: Path, monkeypatch
) -> None:
    telegram = FakeTelegram()
    attempts = 0

    class FlakySource:
        def fetch(self):
            nonlocal attempts
            attempts += 1
            if attempts <= 3:
                raise RuntimeError("temporary failure")
            return []

    monkeypatch.setattr(
        runner_module,
        "load_sources",
        lambda _: SourcesConfig(
            version=1,
            sources=[
                SourceConfig(
                    id="flaky",
                    name="Flaky source",
                    type="fixture",
                    path="unused",
                    companies=["SBER"],
                    categories=["news"],
                )
            ],
        ),
    )
    monkeypatch.setattr(runner_module, "_build_source", lambda *_args: FlakySource())

    states = [
        run(Path(__file__).parents[1], telegram, state_path=tmp_path / "state.json")
        for _ in range(4)
    ]

    assert len(telegram.messages) == 2
    assert "Источник недоступен" in telegram.messages[0]
    assert "temporary failure" in telegram.messages[0]
    assert "Источник восстановлен" in telegram.messages[1]
    assert states[2].source_status["flaky"].consecutive_errors == 3
    assert states[2].source_status["flaky"].failure_alert_sent is True
    assert states[3].source_status["flaky"].status == "ok"
    assert states[3].source_status["flaky"].failure_alert_sent is False


def test_test_message_contains_connection_details_without_token() -> None:
    message = format_test_message(
        "0.1.0",
        "Dividend monitor",
        datetime(2026, 7, 13, 12, 30, tzinfo=UTC),
    )
    assert message.startswith("✅ Dividend Monitor успешно подключен к Telegram.")
    assert "Время UTC: 2026-07-13T12:30:00Z" in message
    assert "Версия приложения: 0.1.0" in message
    assert "Workflow: Dividend monitor" in message
    assert "TELEGRAM_BOT_TOKEN" not in message


def test_test_message_escapes_workflow_name() -> None:
    message = format_test_message(
        "0.1.0",
        "<unsafe> & workflow",
        datetime(2026, 7, 13, 12, 30, tzinfo=UTC),
    )

    assert "Workflow: &lt;unsafe&gt; &amp; workflow" in message
    assert "<unsafe>" not in message


def test_saved_item_test_message_uses_saved_fields_and_escapes_external_text() -> None:
    message = format_saved_item_test(
        SentItem(
            deduplication_id="fingerprint",
            company="A&B <Corp>",
            title="<Previously sent> & title",
            url="https://example.com/news?a=1&b=2",
            source_url="https://example.com/news?a=1&b=2",
            published_at=datetime(2026, 7, 13, 12, 30, tzinfo=UTC),
            sent_at=datetime(2026, 7, 13, 12, 31, tzinfo=UTC),
            category="news",
            importance="high",
        )
    )

    assert "🧪 ТЕСТ: сохранённая публикация" in message
    assert "A&amp;B &lt;Corp&gt;" in message
    assert "&lt;Previously sent&gt; &amp; title" in message
    assert "https://example.com/news?a=1&amp;b=2" in message
    assert "13.07.2026 12:30 UTC" in message
    assert "<Previously sent>" not in message


def test_runner_sends_latest_saved_item_without_fetching_or_changing_state(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "state.json"
    saved_state = JsonStateStorage(state_path)
    saved_state.save(
        MonitorState(
            sent_items=[
                SentItem(
                    deduplication_id="old",
                    company="Old",
                    title="Old title",
                    url="https://example.com/old",
                    published_at=datetime(2026, 7, 12, tzinfo=UTC),
                    sent_at=datetime(2026, 7, 12, tzinfo=UTC),
                ),
                SentItem(
                    deduplication_id="new",
                    company="New",
                    title="Latest title",
                    url="https://example.com/new",
                    published_at=datetime(2026, 7, 13, tzinfo=UTC),
                    sent_at=datetime(2026, 7, 13, tzinfo=UTC),
                ),
            ]
        )
    )
    before = state_path.read_bytes()
    telegram = FakeTelegram()

    monkeypatch.setattr(
        runner_module,
        "load_companies",
        lambda _: (_ for _ in ()).throw(AssertionError("configuration should not be loaded")),
    )
    monkeypatch.setattr(
        runner_module,
        "load_sources",
        lambda _: (_ for _ in ()).throw(AssertionError("sources should not be loaded")),
    )

    state = run(
        tmp_path,
        telegram,
        state_path=Path("state.json"),
        send_existing_item=True,
    )

    assert len(telegram.messages) == 1
    assert "Latest title" in telegram.messages[0]
    assert "Old title" not in telegram.messages[0]
    assert state.sent_items[-1].title == "Latest title"
    assert state_path.read_bytes() == before


def test_format_message_uses_requested_html_layout_and_escapes_external_text() -> None:
    publication = Publication(
        source_id="fixture",
        company="A&B <Corp>",
        ticker="AB",
        category="news",
        title="<Breaking> & dividend update",
        description="<b>Unsafe</b> & important details",
        published_at=datetime(2026, 7, 13, 12, 30, tzinfo=UTC),
        url="https://example.com/news?a=1&b=2",
        importance="high",
    )

    message = format_message(publication)

    assert message == (
        "<b>📰 A&amp;B &lt;Corp&gt; · news</b>\n\n"
        "&lt;Breaking&gt; &amp; dividend update\n\n"
        "<b>Кратко:</b>\nUnsafe &amp; important details\n\n"
        "<b>Важность:</b>\n🔴 высокая\n\n"
        "<b>Источник:</b>\nhttps://example.com/news?a=1&amp;b=2\n\n"
        "<b>Опубликовано:</b>\n2026-07-13 12:30 UTC"
    )
    assert "<Breaking>" not in message
    assert "<b>Unsafe</b>" not in message


def test_format_message_limits_description_to_500_characters() -> None:
    publication = Publication(
        source_id="fixture",
        company="Company",
        ticker="ABC",
        category="news",
        title="Title",
        description="слово " * 200,
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        importance="low",
    )

    message = format_message(publication)
    description = message.split("<b>Кратко:</b>\n", 1)[1].split("\n\n<b>Важность:", 1)[0]

    assert len(description) <= 500
    assert description.endswith("…")


def test_runner_enriches_only_new_publications_with_ai(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).parents[1]
    telegram = FakeTelegram()
    state_path = tmp_path / "state.json"

    class FakeAi:
        def __init__(self) -> None:
            self.calls = 0

        def enhance(self, publication: Publication) -> Publication:
            self.calls += 1
            return publication.model_copy(
                update={"ai_summary": "Краткое AI-резюме.", "importance": "high"}
            )

    monkeypatch.setattr(
        runner_module,
        "load_sources",
        lambda _: SourcesConfig(
            version=1,
            sources=[
                SourceConfig(
                    id="local-fixture",
                    name="Local fixture",
                    type="fixture",
                    path="tests/fixtures/news.xml",
                    companies=["SBER"],
                    categories=["news"],
                )
            ],
        ),
    )
    ai = FakeAi()

    first = run(root, telegram, state_path=state_path, ai_client=ai)
    second = run(root, telegram, state_path=state_path, ai_client=ai)

    assert ai.calls == 1
    assert "Краткое AI-резюме." in telegram.messages[0]
    assert first.sent_items[0].importance == "high"
    assert len(second.sent_items) == 1


def test_runner_delivers_deterministic_message_when_ai_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    root = Path(__file__).parents[1]
    telegram = FakeTelegram()

    class UnavailableAi:
        def enhance(self, publication: Publication) -> Publication:
            raise GitHubModelsUnavailable("GitHub Models is unavailable (HTTP 429)")

    monkeypatch.setattr(
        runner_module,
        "load_sources",
        lambda _: SourcesConfig(
            version=1,
            sources=[
                SourceConfig(
                    id="local-fixture",
                    name="Local fixture",
                    type="fixture",
                    path="tests/fixtures/news.xml",
                    companies=["SBER"],
                    categories=["news"],
                )
            ],
        ),
    )

    state = run(root, telegram, state_path=tmp_path / "state.json", ai_client=UnavailableAi())

    assert len(telegram.messages) == 2
    assert "GitHub Models недоступен" in telegram.messages[0]
    assert "HTTP 429" in telegram.messages[0]
    assert state.sent_items[0].telegram_message_status == "sent"
    assert state.ai_failure_alert_sent is True


def test_error_notification_redacts_credentials() -> None:
    token_name = "GITHUB_" + "TOKEN"
    bearer_value = "gh" + "o_test"
    reason = runner_module._safe_error_reason(f"{token_name}=secret-value Bearer {bearer_value}")

    assert "secret-value" not in reason
    assert "gho_test" not in reason
    assert "[скрыто]" in reason


def test_runner_dry_run_uses_fake_ai_without_delivery_or_state_write(
    tmp_path: Path, monkeypatch
) -> None:
    root = Path(__file__).parents[1]
    telegram = FakeTelegram()
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(
        runner_module,
        "load_sources",
        lambda _: SourcesConfig(
            version=1,
            sources=[
                SourceConfig(
                    id="local-fixture",
                    name="Local fixture",
                    type="fixture",
                    path="tests/fixtures/news.xml",
                    companies=["SBER"],
                    categories=["news"],
                )
            ],
        ),
    )

    state = run(
        root,
        telegram,
        state_path=state_path,
        ai_client=runner_module.FakeAIClient(),
        dry_run=True,
    )

    assert telegram.messages == []
    assert not state_path.exists()
    assert state.sent_items[0].telegram_message_status == "dry-run"


def test_format_message_stays_within_telegram_limit_for_hostile_long_text() -> None:
    publication = Publication(
        source_id="fixture",
        company="<company> & " * 100,
        ticker="ABC",
        category="news",
        title="<title> & " * 1000,
        description="<description> & " * 1000,
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        url="https://example.com/?q=" + ("&x=<value>" * 150),
    )

    assert len(format_message(publication)) <= 4096
