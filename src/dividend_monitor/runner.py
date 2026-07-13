"""CLI and orchestration for one complete monitor run."""

import argparse
import html
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .calculations import calculate_comparisons
from .config import load_companies, load_sources
from .deduplication import is_new, mark_sent
from .financial_reports import detect_report_context
from .models import Company, MonitorState, Publication, RunStatistics, SourceConfig, SourceStatus
from .sources.base import FixtureSource, Source
from .sources.edisclosure import EdisclosureReportsSource
from .sources.lenenergo import LenenergoPressSource
from .sources.moex_companies import MoexCompaniesRssSource
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


_METRIC_LABELS = {
    "revenue": "Выручка",
    "operating_profit": "Операционная прибыль",
    "ebitda": "EBITDA",
    "net_profit": "Чистая прибыль",
    "free_cash_flow": "Свободный денежный поток",
    "net_debt": "Чистый долг",
    "capital_expenditures": "Капитальные расходы",
}


def _format_report_details(publication: Publication) -> str:
    if publication.category != "financial_report":
        return ""
    details: list[str] = []
    if publication.report_period:
        details.append(f"<b>Период:</b>\n{_escape(publication.report_period, 100)}")
    if publication.report_standard:
        details.append(f"<b>Стандарт:</b>\n{_escape(publication.report_standard, 100)}")
    if not publication.report_metrics:
        details.append(
            "<b>Показатели:</b>\nПоказатели автоматически не извлечены. "
            "Доступен официальный отчет по ссылке."
        )
    else:
        lines = []
        for metric in publication.report_metrics:
            value = format(metric.value, "f").rstrip("0").rstrip(".") or "0"
            lines.append(
                f"• {_escape(_METRIC_LABELS[metric.name], 120)}: "
                f"{_escape(value, 80)} {_escape(metric.currency, 40)} "
                f"({_escape(metric.unit, 80)})"
            )
        details.append("<b>Показатели:</b>\n" + "\n".join(lines))
    if publication.report_comparisons:
        lines = []
        for comparison in publication.report_comparisons:
            if comparison.change_percent is None:
                continue
            percent = format(comparison.change_percent, ".2f")
            kind = "год к году" if comparison.comparison_kind == "yoy" else "квартал к кварталу"
            lines.append(f"• {_METRIC_LABELS[comparison.name]}: {percent}% ({kind})")
        if lines:
            details.append("<b>Изменение:</b>\n" + "\n".join(lines))
    return "\n\n".join(details)


def _report_with_comparisons(publication: Publication, state: MonitorState) -> Publication:
    if (
        publication.category != "financial_report"
        or not publication.report_metrics
        or not publication.report_period
        or not publication.report_period_kind
    ):
        return publication
    period_match = re.fullmatch(r"(\d{4}) (Q[1-4]|H1|9M|FY)", publication.report_period)
    if not period_match:
        return publication
    year = int(period_match.group(1))
    suffix = period_match.group(2)
    previous_year_period = f"{year - 1} {suffix}"
    history = [
        report
        for report in state.financial_reports
        if report.ticker == publication.ticker
        and report.report_standard == publication.report_standard
    ]
    previous_year = next(
        (report for report in history if report.report_period == previous_year_period), None
    )
    previous_quarter = None
    if publication.report_period_kind == "quarter":
        quarter = int(suffix[1])
        previous_suffix = f"Q{quarter - 1}" if quarter > 1 else "Q4"
        previous_year_for_quarter = year if quarter > 1 else year - 1
        previous_quarter_period = f"{previous_year_for_quarter} {previous_suffix}"
        previous_quarter = next(
            (report for report in history if report.report_period == previous_quarter_period), None
        )
    comparisons = calculate_comparisons(
        publication.report_metrics,
        previous_year.report_metrics if previous_year else [],
        publication.report_period_kind,
        previous_quarter.report_metrics if previous_quarter else None,
    )
    return publication.model_copy(update={"report_comparisons": comparisons})


def _enrich_report_context(publication: Publication) -> Publication:
    if publication.category != "financial_report":
        return publication
    period, period_kind, standard = detect_report_context(
        f"{publication.title} {publication.description}"
    )
    updates = {}
    if not publication.report_period:
        updates["report_period"] = period
    if not publication.report_period_kind:
        updates["report_period_kind"] = period_kind
    if not publication.report_standard:
        updates["report_standard"] = standard
    return publication.model_copy(update=updates) if updates else publication


def _remember_report(publication: Publication, state: MonitorState) -> None:
    if publication.category != "financial_report" or not publication.report_metrics:
        return
    state.financial_reports = [
        report
        for report in state.financial_reports
        if report.external_id != publication.external_id
    ]
    state.financial_reports.append(publication)
    state.financial_reports = state.financial_reports[-100:]


def _build_source(config: SourceConfig, companies: dict[str, Company], root: Path) -> Source:
    if config.type == "fixture":
        return FixtureSource(config, companies, root)
    if config.id == "moex-investor-relations-rss":
        return MoexCompaniesRssSource(config, companies)
    if len(config.companies) != 1:
        raise ValueError(f"Source '{config.id}' must target exactly one company")
    company = companies[config.companies[0]]
    if config.id == "rosseti-lenenergo-press":
        return LenenergoPressSource(config, company)
    if config.id == "sber-official-disclosure":
        return SberOfficialHtmlSource(config, company)
    if config.type == "official_html" and config.id.endswith("-edisclosure-reports"):
        return EdisclosureReportsSource(config, company)
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
    report_details = _format_report_details(publication)
    message = (
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

    if report_details:
        candidate = f"{message}\n\n{report_details}"
        if len(candidate) <= 4096:
            message = candidate
    return message


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
            for raw_publication in source.fetch():
                publication = _enrich_report_context(raw_publication)
                if is_new(publication, state):
                    statistics.new_publications += 1
                    publication_to_send = _report_with_comparisons(publication, state)
                    telegram.send_message(format_message(publication_to_send))
                    statistics.sent += 1
                    mark_sent(publication, state, checked_at)
                    _remember_report(publication, state)
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
