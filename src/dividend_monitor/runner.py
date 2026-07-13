"""CLI and orchestration for one complete monitor run."""

import argparse
import html
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .config import load_companies, load_sources
from .deduplication import is_new, mark_sent
from .models import Company, MonitorState, Publication, RunStatistics, SourceConfig, SourceStatus
from .sources.base import FixtureSource, Source
from .sources.lenenergo import LenenergoPressSource
from .sources.moex import MoexRssSource
from .sources.official_news import OfficialNewsListSource
from .sources.sber import SberOfficialHtmlSource
from .storage import JsonStateStorage
from .summarizer import summarize
from .telegram import TelegramClient, TelegramConfigurationError

LOGGER = logging.getLogger(__name__)

_IMPORTANCE_LABELS = {
    "high": "🔴 высокая",
    "medium": "🟡 средняя",
    "low": "⚪ низкая",
}


def _shorten(text: str, max_length: int) -> str:
    """Shorten plain text without leaving a broken HTML entity behind."""
    if len(text) <= max_length:
        return text
    shortened = text[: max_length - 1].rsplit(" ", 1)[0].rstrip()
    return f"{shortened}…"


def _escape(text: str, max_length: int) -> str:
    lower, upper = 0, len(text)
    while lower < upper:
        candidate_length = (lower + upper + 1) // 2
        candidate = _shorten(text, candidate_length)
        if len(html.escape(candidate, quote=True)) <= max_length:
            lower = candidate_length
        else:
            upper = candidate_length - 1
    return html.escape(_shorten(text, lower), quote=True)


def _build_source(config: SourceConfig, companies: dict[str, Company], root: Path) -> Source:
    if config.type == "fixture":
        return FixtureSource(config, companies, root)
    if len(config.companies) != 1:
        raise ValueError(f"Source '{config.id}' must target exactly one company")
    company = companies[config.companies[0]]
    if config.id == "moex-investor-relations-rss":
        return MoexRssSource(config, company)
    if config.id == "rosseti-lenenergo-press":
        return LenenergoPressSource(config, company)
    if config.id == "sber-official-disclosure":
        return SberOfficialHtmlSource(config, company)
    if config.type == "official_html" and config.id in {
        "lukoil-official-news",
        "x5-official-news",
        "headhunter-official-news",
        "interrao-official-news",
    }:
        return OfficialNewsListSource(config, company)
    raise ValueError(f"Unsupported source type: {config.type}")


def format_message(publication: Publication) -> str:
    description = summarize(publication.description, max_length=500) or "Описание отсутствует."
    importance = _IMPORTANCE_LABELS[publication.importance]
    return (
        f"<b>📰 {_escape(publication.company, 150)} · "
        f"{_escape(publication.category, 100)}</b>\n\n"
        f"{_escape(publication.title, 900)}\n\n"
        f"<b>Кратко:</b>\n{_escape(description, 1200)}\n\n"
        f"<b>Важность:</b>\n{importance}\n\n"
        f"<b>Источник:</b>\n"
        f"{_escape(str(publication.url) if publication.url else 'Ссылка отсутствует.', 800)}\n\n"
        f"<b>Опубликовано:</b>\n"
        f"{publication.published_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')}"
    )


def format_test_message(
    app_version: str, workflow_name: str, now: datetime | None = None
) -> str:
    current_time = (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    return (
        "✅ Dividend Monitor успешно подключен к Telegram.\n\n"
        f"Время UTC: {current_time}\n"
        f"Версия приложения: {app_version}\n"
        f"Workflow: {workflow_name}"
    )


def run(
    root: Path,
    telegram: TelegramClient,
    companies_path: Path = Path("config/companies.yaml"),
    sources_path: Path = Path("config/sources.yaml"),
    state_path: Path = Path("data/state.json"),
    send_test_message: bool = False,
    workflow_name: str = "Dividend monitor",
    run_statistics: RunStatistics | None = None,
) -> MonitorState:
    companies_config = load_companies(root / companies_path)
    sources_config = load_sources(root / sources_path)
    companies = {company.ticker: company for company in companies_config.companies}
    state_storage = JsonStateStorage(root / state_path)
    state = state_storage.load()
    checked_at = datetime.now(UTC)
    statistics = run_statistics or RunStatistics()

    if send_test_message:
        telegram.send_message(format_test_message(__version__, workflow_name, checked_at))

    for source_config in sources_config.sources:
        if not source_config.enabled:
            continue
        statistics.sources_checked += 1
        try:
            source = _build_source(source_config, companies, root)
            for publication in source.fetch():
                if is_new(publication, state):
                    statistics.new_publications += 1
                    telegram.send_message(format_message(publication))
                    statistics.sent += 1
                    mark_sent(publication, state, checked_at)
                else:
                    statistics.duplicates += 1
            statistics.successful += 1
            state.source_status[source_config.id] = SourceStatus(
                last_checked_at=checked_at, status="ok"
            )
        except Exception as exc:  # isolate one source from the rest of the run
            statistics.errors += 1
            LOGGER.exception("Source '%s' failed", source_config.id)
            state.source_status[source_config.id] = SourceStatus(
                last_checked_at=checked_at, status="error", error=str(exc)
            )

    state.last_successful_check = checked_at
    state_storage.save(state)
    LOGGER.info(
        "Источников проверено: %s; Успешно: %s; Ошибки: %s; "
        "Новых публикаций: %s; Отправлено: %s; Дубликатов: %s",
        statistics.sources_checked,
        statistics.successful,
        statistics.errors,
        statistics.new_publications,
        statistics.sent,
        statistics.duplicates,
    )
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one dividend monitor check")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--send-test-message", action="store_true")
    parser.add_argument(
        "--workflow-name", default=os.getenv("GITHUB_WORKFLOW", "Dividend monitor")
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        telegram = TelegramClient.from_environment()
    except TelegramConfigurationError as exc:
        parser.error(str(exc))
    run(
        args.root,
        telegram,
        send_test_message=args.send_test_message,
        workflow_name=args.workflow_name,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
