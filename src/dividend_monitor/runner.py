"""CLI and orchestration for one complete monitor run."""

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .config import load_companies, load_sources
from .deduplication import is_new, mark_sent
from .models import Company, MonitorState, Publication, SourceConfig, SourceStatus
from .sources.base import FixtureSource, Source
from .sources.lenenergo import LenenergoPressSource
from .sources.moex import MoexRssSource
from .sources.sber import SberOfficialHtmlSource
from .storage import JsonStateStorage
from .summarizer import summarize
from .telegram import TelegramClient, TelegramConfigurationError

LOGGER = logging.getLogger(__name__)


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
    raise ValueError(f"Unsupported source type: {config.type}")


def format_message(publication: Publication) -> str:
    description = summarize(publication.description) or "Описание отсутствует."
    url = str(publication.url) if publication.url else "Ссылка отсутствует."
    return (
        f"{publication.company} ({publication.ticker})\n"
        f"Категория: {publication.category}\n"
        f"Важность: {publication.importance}\n\n"
        f"{publication.title}\n\n"
        f"{description}\n\n"
        f"Дата: {publication.published_at.isoformat()}\n"
        f"Источник: {url}"
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
) -> MonitorState:
    companies_config = load_companies(root / companies_path)
    sources_config = load_sources(root / sources_path)
    companies = {company.ticker: company for company in companies_config.companies}
    state_storage = JsonStateStorage(root / state_path)
    state = state_storage.load()
    checked_at = datetime.now(UTC)

    if send_test_message:
        telegram.send_message(format_test_message(__version__, workflow_name, checked_at))

    for source_config in sources_config.sources:
        if not source_config.enabled:
            continue
        try:
            source = _build_source(source_config, companies, root)
            for publication in source.fetch():
                if is_new(publication, state):
                    telegram.send_message(format_message(publication))
                    mark_sent(publication, state, checked_at)
            state.source_status[source_config.id] = SourceStatus(
                last_checked_at=checked_at, status="ok"
            )
        except Exception as exc:  # isolate one source from the rest of the run
            LOGGER.exception("Source '%s' failed", source_config.id)
            state.source_status[source_config.id] = SourceStatus(
                last_checked_at=checked_at, status="error", error=str(exc)
            )

    state.last_successful_check = checked_at
    state_storage.save(state)
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
