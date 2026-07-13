"""CLI and orchestration for one complete monitor run."""

# Keep the notification templates readable despite escaped Russian literals.
# ruff: noqa: E501

import argparse
import html
import logging
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import __version__
from .calculations import calculate_comparisons
from .config import load_companies, load_sources
from .deduplication import cleanup_old_state, fingerprint, is_new, mark_sent
from .dividends import classify_dividend_event
from .financial_reports import detect_report_context
from .github_models import (
    FakeAIClient,
    GitHubModelsClient,
    GitHubModelsUnavailable,
    client_from_environment,
    filter_from_environment,
)
from .health import run_exit_code
from .models import (
    AiCacheEntry,
    AiConfig,
    Company,
    MonitorState,
    Publication,
    RunStatistics,
    SentItem,
    SourceConfig,
    SourceStatus,
)
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
_SENSITIVE_ERROR_VALUE = re.compile(
    r"(?i)(?:github_pat_|ghp_|gho_|Bearer\s+|bot\d+:)[A-Za-z0-9_\-.:]+"
)
_SENSITIVE_ERROR_ASSIGNMENT = re.compile(
    r"(?i)(?:GITHUB_TOKEN|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID|API_KEY|SECRET|PASSWORD)=[^\s]+"
)


class DryRunTelegram:
    """Delivery replacement that never contacts Telegram or writes credentials."""

    def send_message(self, message: str) -> str:
        LOGGER.info("Dry run prepared a Telegram message (%s characters)", len(message))
        return "dry-run"


_IMPORTANCE_LABELS = {
    "high": "🔴 высокая",
    "medium": "🟡 средняя",
    "low": "⚪ низкая",
}
_IMPORTANCE_RANK = {"low": 0, "medium": 1, "high": 2}
_CURRENCY_SYMBOLS = {"RUB": "₽", "USD": "$", "EUR": "€", "CNY": "¥"}


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


def format_money(amount: object, currency: str) -> str:
    """Format an already verified monetary amount without assuming rubles."""
    value = format(amount, "f").rstrip("0").rstrip(".") or "0"
    return f"{value} {_CURRENCY_SYMBOLS.get(currency.upper(), currency.upper())}"


_METRIC_LABELS = {
    "revenue": "Выручка",
    "operating_profit": "Операционная прибыль",
    "ebitda": "EBITDA",
    "net_profit": "Чистая прибыль",
    "free_cash_flow": "Свободный денежный поток",
    "net_debt": "Чистый долг",
    "capital_expenditures": "Капитальные расходы",
}

_DIVIDEND_STATUS_LABELS = {
    "recommended": "рекомендованы",
    "approved": "утверждены",
    "cancelled": "отменены",
    "paid": "выплачены",
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


def _format_dividend_message(publication: Publication) -> str:
    event = publication.dividend_event
    if event is None:
        return format_message(publication)
    amount = (
        f"{format(event.amount_per_share, 'f').rstrip('0').rstrip('.') or '0'} "
        f"{_escape(event.currency, 20)} на акцию"
        if event.amount_per_share is not None
        else "не указано"
    )
    period = _escape(event.period or "не указано", 120)
    register_date = (
        event.register_close_date.astimezone(UTC).strftime("%Y-%m-%d")
        if event.register_close_date
        else "не указана"
    )
    message = (
        f"<b>💰 {_escape(publication.company, 150)} — дивиденды</b>\n\n"
        f"<b>Статус:</b>\n{_DIVIDEND_STATUS_LABELS[event.status]}\n\n"
        f"<b>Размер:</b>\n{amount}\n\n"
        f"<b>Период:</b>\n{period}\n\n"
        f"<b>Дата закрытия реестра:</b>\n{register_date}\n\n"
        f"<b>Тип акции:</b>\n{event.share_type}\n\n"
        f"<b>Источник:</b>\n{_escape(str(event.source_url), 800)}"
    )
    if publication.ticker == "LSNGP":
        details = []
        if event.rasbu_net_profit:
            details.append(f"Чистая прибыль по РСБУ: {_escape(event.rasbu_net_profit, 300)}")
        if event.dividend_base:
            details.append(f"Дивидендная база: {_escape(event.dividend_base, 300)}")
        if event.preferred_share_payment:
            details.append(
                f"Привилегированные акции: {_escape(event.preferred_share_payment, 300)}"
            )
        if details:
            message += "\n\n<b>LSNGP:</b>\n" + "\n".join(details)
    return message


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
    if publication.url and not publication.dividend_event:
        dividend_event = classify_dividend_event(
            f"{publication.title} {publication.description}",
            publication.url,
            publication.ticker,
        )
        if dividend_event:
            publication = publication.model_copy(
                update={"category": "dividend", "dividend_event": dividend_event}
            )
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


def _format_dividend_message_v2(publication: Publication) -> str:
    event = publication.dividend_event
    if event is None:
        return ""
    labels = {
        "recommended": "\u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u043e\u0432\u0430\u043d\u044b",
        "approved": "\u0443\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u044b",
        "cancelled": "\u043e\u0442\u043c\u0435\u043d\u0435\u043d\u044b",
        "paid": "\u0432\u044b\u043f\u043b\u0430\u0447\u0435\u043d\u044b",
    }
    amount = (
        f"{format_money(event.amount_per_share, event.currency)} \u043d\u0430 \u0430\u043a\u0446\u0438\u044e"
        if event.amount_per_share is not None
        else "\u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d\u043e"
    )
    register_date = (
        event.register_close_date.astimezone(UTC).strftime("%Y-%m-%d")
        if event.register_close_date
        else "\u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d\u0430"
    )
    period = _escape(event.period or "\u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d", 120)
    meeting_date = (
        event.general_meeting_date.astimezone(UTC).strftime("%Y-%m-%d")
        if event.general_meeting_date
        else "\u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d\u0430"
    )
    message = (
        f"<b>\U0001f4b0 {_escape(publication.company, 150)} \u2014 \u0434\u0438\u0432\u0438\u0434\u0435\u043d\u0434\u044b</b>\n\n"
        f"<b>\u0421\u0442\u0430\u0442\u0443\u0441:</b>\n{labels[event.status]}\n\n"
        f"<b>\u0420\u0430\u0437\u043c\u0435\u0440:</b>\n{amount}\n\n"
        f"<b>\u041f\u0435\u0440\u0438\u043e\u0434:</b>\n{period}\n\n"
        f"<b>\u0414\u0430\u0442\u0430 \u043e\u0431\u0449\u0435\u0433\u043e \u0441\u043e\u0431\u0440\u0430\u043d\u0438\u044f:</b>\n{meeting_date}\n\n"
        f"<b>\u0414\u0430\u0442\u0430 \u0437\u0430\u043a\u0440\u044b\u0442\u0438\u044f \u0440\u0435\u0435\u0441\u0442\u0440\u0430:</b>\n{register_date}\n\n"
        f"<b>\u0422\u0438\u043f \u0430\u043a\u0446\u0438\u0438:</b>\n{event.share_type}\n\n"
        f"<b>\u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a:</b>\n{_escape(str(event.source_url), 800)}"
    )
    if publication.ticker == "LSNGP":
        details = []
        if event.rasbu_net_profit:
            details.append(
                f"\u0427\u0438\u0441\u0442\u0430\u044f \u043f\u0440\u0438\u0431\u044b\u043b\u044c \u043f\u043e \u0420\u0421\u0411\u0423: {_escape(event.rasbu_net_profit, 300)}"
            )
        if event.dividend_base:
            details.append(
                f"\u0414\u0438\u0432\u0438\u0434\u0435\u043d\u0434\u043d\u0430\u044f \u0431\u0430\u0437\u0430: {_escape(event.dividend_base, 300)}"
            )
        if event.preferred_share_payment:
            details.append(
                f"\u041f\u0440\u0438\u0432\u0438\u043b\u0435\u0433\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0435 \u0430\u043a\u0446\u0438\u0438: {_escape(event.preferred_share_payment, 300)}"
            )
        if details:
            message += "\n\n<b>LSNGP:</b>\n" + "\n".join(details)
    return message


def format_message(publication: Publication) -> str:
    if publication.dividend_event:
        return _format_dividend_message_v2(publication)
    description = publication.ai_summary or summarize(publication.description, max_length=500)
    description = description or "Описание отсутствует."
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


def format_test_message(app_version: str, workflow_name: str, now: datetime | None = None) -> str:
    current_time = (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    return (
        "✅ Dividend Monitor успешно подключен к Telegram.\n\n"
        f"Время UTC: {current_time}\n"
        f"Версия приложения: {_escape(app_version, 100)}\n"
        f"Workflow: {_escape(workflow_name, 200)}"
    )


def format_saved_item_test(item: SentItem) -> str:
    """Format a saved publication for a manual Telegram preview."""
    category_labels = {
        "news": "корпоративная новость",
        "corporate": "корпоративное событие",
        "dividend": "дивиденды",
        "financial_report": "финансовый отчёт",
    }
    importance_labels = {
        "high": "🔴 высокая",
        "medium": "🟡 средняя",
        "low": "🟢 низкая",
    }
    published_at = item.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    published_text = published_at.astimezone(UTC).strftime("%d.%m.%Y %H:%M UTC")
    source_url = item.source_url or item.url or "Ссылка отсутствует."
    category = category_labels.get(item.category, item.category)

    if item.category == "dividend":
        status = _DIVIDEND_STATUS_LABELS.get(item.dividend_status or "", "не указан")
        return (
            f"<b>🧪 ТЕСТ: сохранённая публикация</b>\n\n"
            f"<b>💰 {_escape(item.company, 150)} — дивиденды</b>\n\n"
            f"<b>Статус:</b>\n{_escape(status, 100)}\n\n"
            f"<b>Размер:</b>\nсохранённая запись не содержит размера выплаты\n\n"
            f"<b>Период:</b>\nсохранённая запись не содержит периода\n\n"
            f"<b>Дата закрытия реестра:</b>\nбудет уточнена\n\n"
            f"<b>Источник:</b>\n{_escape(source_url, 800)}\n\n"
            f"<b>Опубликовано:</b>\n{published_text}"
        )

    return (
        f"<b>🧪 ТЕСТ: сохранённая публикация</b>\n\n"
        f"<b>📰 {_escape(item.company, 150)} · {_escape(category, 100)}</b>\n\n"
        f"{_escape(item.title, 900)}\n\n"
        f"<b>Кратко:</b>\nЭто тестовая повторная отправка сохранённой публикации.\n\n"
        f"<b>Важность:</b>\n{importance_labels.get(item.importance, item.importance)}\n\n"
        f"<b>Источник:</b>\n{_escape(source_url, 800)}\n\n"
        f"<b>Опубликовано:</b>\n{published_text}"
    )


def _enhance_new_publications(
    publications: list[Publication],
    state: MonitorState,
    ai_client: GitHubModelsClient | FakeAIClient | object | None,
    checked_at: datetime,
    ai_config: AiConfig,
) -> tuple[list[Publication], GitHubModelsClient | FakeAIClient | object | None, str | None, bool]:
    """Use cache first, then enrich bounded batches without blocking delivery."""
    if ai_client is None or not ai_config.enabled or not publications:
        return publications, ai_client, None, False

    _reset_daily_ai_usage(state, checked_at)

    cache_key = getattr(ai_client, "cache_key", None)
    batch_size = getattr(ai_client, "batch_size", 1)
    enhance_batch = getattr(ai_client, "enhance_batch", None)
    if not callable(cache_key) or not callable(enhance_batch) or not isinstance(batch_size, int):
        # Compatibility with small test doubles and legacy providers.
        enhance_one = getattr(ai_client, "enhance", None)
        if not callable(enhance_one):
            return publications, None, None, False
        try:
            return [enhance_one(publication) for publication in publications], ai_client, None, True
        except GitHubModelsUnavailable as exc:
            LOGGER.warning("GitHub Models disabled for this run: %s", exc)
            return publications, None, _safe_error_reason(exc), True

    enhanced_by_id: dict[str, Publication] = {}
    pending: list[Publication] = []
    keys: dict[str, str] = {}
    for publication in publications:
        key = cache_key(publication)
        cached = state.ai_cache.get(key)
        publication_id = fingerprint(publication)
        if cached is None or cached.created_at < checked_at - timedelta(
            days=ai_config.cache_ttl_days
        ):
            pending.append(publication)
            keys[publication_id] = key
        else:
            state.ai_usage.cache_hits += 1
            enhanced_by_id[publication_id] = publication.model_copy(
                update={"ai_summary": cached.summary, "importance": cached.importance}
            )

    pending.sort(key=lambda item: _IMPORTANCE_RANK[item.importance], reverse=True)
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        if not _can_spend_ai_request(state, ai_config, batch):
            state.ai_usage.skipped += len(batch)
            continue
        try:
            results = enhance_batch(batch)
        except GitHubModelsUnavailable as exc:
            LOGGER.warning("GitHub Models disabled for this run: %s", exc)
            return (
                [enhanced_by_id.get(fingerprint(item), item) for item in publications],
                None,
                _safe_error_reason(exc),
                True,
            )
        state.ai_usage.requests += 1
        for publication in batch:
            publication_id = fingerprint(publication)
            result = results.get(publication_id)
            if result is None:
                continue
            enhanced_by_id[publication_id] = result
            state.ai_cache[keys[publication_id]] = AiCacheEntry(
                summary=result.ai_summary or result.description,
                importance=result.importance,
                created_at=checked_at,
            )
    _trim_ai_cache(state, ai_config)
    return (
        [enhanced_by_id.get(fingerprint(item), item) for item in publications],
        ai_client,
        None,
        bool(pending),
    )


def _reset_daily_ai_usage(state: MonitorState, checked_at: datetime) -> None:
    """Reset the state-backed daily AI counter at the UTC day boundary."""
    today = checked_at.date().isoformat()
    if state.ai_usage.date != today:
        state.ai_usage.date = today
        state.ai_usage.requests = 0
        state.ai_usage.cache_hits = 0
        state.ai_usage.rate_limit_hits = 0
        state.ai_usage.skipped = 0


def _can_spend_ai_request(state: MonitorState, config: AiConfig, batch: list[Publication]) -> bool:
    """Reserve the tail of each budget for high-priority events."""
    is_high = any(publication.importance == "high" for publication in batch)
    remaining_run = config.max_requests_per_run - state.ai_usage.requests
    remaining_day = config.max_requests_per_day - state.ai_usage.requests
    if min(remaining_run, remaining_day) <= 0:
        return False
    return is_high or min(remaining_run, remaining_day) > config.reserve_requests_for_high_priority


def _trim_ai_cache(state: MonitorState, config: AiConfig) -> None:
    """Bound cache size while retaining the most recently created results."""
    if len(state.ai_cache) <= config.cache_max_items:
        return
    newest = sorted(state.ai_cache.items(), key=lambda item: item[1].created_at, reverse=True)
    state.ai_cache = dict(newest[: config.cache_max_items])


def _is_recent(publication: Publication, checked_at: datetime, max_age_hours: int) -> bool:
    """Return whether a publication is within a configured delivery window."""
    published_at = publication.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    return published_at.astimezone(UTC) >= checked_at - timedelta(hours=max_age_hours)


def _remember_bootstrap_publications(
    publications: list[Publication], state: MonitorState, checked_at: datetime
) -> None:
    """Remember a first snapshot without creating an archival Telegram burst."""
    for publication in publications:
        mark_sent(publication, state, checked_at, "remembered")
        _remember_report(publication, state)


def run(
    root: Path,
    telegram: TelegramClient,
    companies_path: Path = Path("config/companies.yaml"),
    sources_path: Path = Path("config/sources.yaml"),
    state_path: Path = Path("data/state.json"),
    send_test_message: bool = False,
    workflow_name: str = "Dividend monitor",
    run_statistics: RunStatistics | None = None,
    send_existing_item: bool = False,
    ai_client: GitHubModelsClient | FakeAIClient | object | None = None,
    dry_run: bool = False,
    ai_filter_enabled: bool = False,
    ai_min_importance: str = "low",
    backfill: bool = False,
    backfill_days: int | None = None,
) -> MonitorState:
    started_at = time.perf_counter()
    state_storage = JsonStateStorage(root / state_path)
    state = state_storage.load()
    if send_existing_item:
        if not state.sent_items:
            raise ValueError("No previously sent publications are saved in state.json")
        item = max(state.sent_items, key=lambda saved_item: saved_item.sent_at)
        if dry_run:
            LOGGER.info("Dry run prepared a saved publication preview")
        else:
            telegram.send_message(format_saved_item_test(item))
        duration_seconds = time.perf_counter() - started_at
        print(f"Duration: {duration_seconds:.2f}s")
        print("Sources: 0")
        print("New publications: 0")
        print(f"Telegram messages: {0 if dry_run else 1}")
        print("Errors: 0")
        return state

    companies_config = load_companies(root / companies_path)
    sources_config = load_sources(root / sources_path)
    companies = {company.ticker: company for company in companies_config.companies}
    for source_config in sources_config.sources:
        unknown = set(source_config.companies) - companies.keys()
        if unknown:
            raise ValueError(
                f"Source '{source_config.id}' references unknown companies: {sorted(unknown)}"
            )
    checked_at = datetime.now(UTC)
    cleanup_old_state(state, checked_at)
    statistics = run_statistics or RunStatistics()
    telegram_messages = 0

    if send_test_message and not dry_run:
        telegram.send_message(format_test_message(__version__, workflow_name, checked_at))
        telegram_messages += 1

    for source_config in sources_config.sources:
        if not source_config.enabled:
            continue
        statistics.sources_checked += 1
        try:
            source = _build_source(source_config, companies, root)
            new_publications: list[Publication] = []
            fetched_publications = source.fetch()
            for raw_publication in fetched_publications:
                publication = _enrich_report_context(raw_publication)
                if is_new(publication, state):
                    statistics.new_publications += 1
                    new_publications.append(_report_with_comparisons(publication, state))
                else:
                    statistics.duplicates += 1
            if (
                not state.bootstrap_completed
                and not backfill
                and sources_config.initial_sync_mode == "remember_only"
            ):
                _remember_bootstrap_publications(new_publications, state, checked_at)
                statistics.duplicates += len(new_publications)
                new_publications = []
            elif not backfill and sources_config.initial_sync_mode == "recent_only":
                new_publications = [
                    publication
                    for publication in new_publications
                    if _is_recent(publication, checked_at, sources_config.max_item_age_hours)
                ]
            elif backfill and backfill_days is not None:
                new_publications = [
                    publication
                    for publication in new_publications
                    if _is_recent(publication, checked_at, backfill_days * 24)
                ]
            new_publications, ai_client, ai_error, ai_attempted = _enhance_new_publications(
                new_publications, state, ai_client, checked_at, sources_config.ai
            )
            if ai_error:
                state.ai_last_error = ai_error
                if (
                    not dry_run
                    and not state.ai_failure_alert_sent
                    and _send_health_message(telegram, _ai_failure_message(ai_error))
                ):
                    state.ai_failure_alert_sent = True
                    telegram_messages += 1
            elif ai_attempted and state.ai_failure_alert_sent:
                state.ai_failure_alert_sent = False
                state.ai_last_error = None
                if not dry_run and _send_health_message(telegram, _ai_recovery_message()):
                    telegram_messages += 1
            for publication_to_send in new_publications:
                if (
                    publication_to_send.importance == "low"
                    and not sources_config.telegram.send_low_priority_immediately
                    and not backfill
                ):
                    mark_sent(publication_to_send, state, checked_at, "filtered")
                    _remember_report(publication_to_send, state)
                    continue
                if (
                    telegram_messages >= sources_config.telegram.max_messages_per_run
                    and publication_to_send.importance != "high"
                ):
                    LOGGER.warning(
                        "Telegram per-run limit reached; keeping %s for digest",
                        publication_to_send.ticker,
                    )
                    mark_sent(publication_to_send, state, checked_at, "filtered")
                    _remember_report(publication_to_send, state)
                    continue
                if (
                    ai_filter_enabled
                    and publication_to_send.ai_summary is not None
                    and _IMPORTANCE_RANK[publication_to_send.importance]
                    < _IMPORTANCE_RANK[ai_min_importance]
                ):
                    LOGGER.info(
                        "AI filter skipped a low-priority publication for %s",
                        publication_to_send.ticker,
                    )
                    mark_sent(publication_to_send, state, checked_at, "filtered")
                    _remember_report(publication_to_send, state)
                    continue
                if dry_run:
                    LOGGER.info(
                        "Dry run prepared publication for %s (%s)",
                        publication_to_send.ticker,
                        publication_to_send.category,
                    )
                    telegram_status = "dry-run"
                else:
                    delivery_result = telegram.send_message(format_message(publication_to_send))
                    telegram_status = "sent"
                statistics.sent += 1
                mark_sent(
                    publication_to_send,
                    state,
                    checked_at,
                    telegram_status,
                    delivery_result if not dry_run and isinstance(delivery_result, int) else None,
                )
                _remember_report(publication_to_send, state)
            statistics.successful += 1
            previous_status = state.source_status.get(source_config.id)
            source_health = (
                "degraded" if not fetched_publications and source_config.type != "fixture" else "ok"
            )
            current_status = SourceStatus(
                last_checked_at=checked_at,
                status=source_health,
                last_successful_check=(checked_at if source_health == "ok" else None),
                last_attempt_at=checked_at,
                last_success_at=(checked_at if source_health == "ok" else None),
                last_degraded_at=(checked_at if source_health == "degraded" else None),
                consecutive_errors=0,
                failure_alert_sent=(
                    previous_status.failure_alert_sent if previous_status else False
                ),
            )
            if (
                not dry_run
                and current_status.failure_alert_sent
                and _send_health_message(
                    telegram,
                    _source_recovery_message(source_config, checked_at),
                )
            ):
                current_status.failure_alert_sent = False
                telegram_messages += 1
            state.source_status[source_config.id] = current_status
        except Exception as exc:  # isolate one source from the rest of the run
            statistics.errors += 1
            LOGGER.exception("Source '%s' failed", source_config.id)
            previous_status = state.source_status.get(source_config.id)
            current_status = SourceStatus(
                last_checked_at=checked_at,
                status="failed",
                error=_safe_error_reason(exc),
                last_successful_check=(
                    previous_status.last_successful_check if previous_status else None
                ),
                last_attempt_at=checked_at,
                consecutive_errors=(previous_status.consecutive_errors if previous_status else 0)
                + 1,
                failure_alert_sent=(
                    previous_status.failure_alert_sent if previous_status else False
                ),
            )
            if (
                not dry_run
                and not current_status.failure_alert_sent
                and _send_health_message(
                    telegram,
                    _source_failure_message(source_config, current_status),
                )
            ):
                current_status.failure_alert_sent = True
                telegram_messages += 1
            state.source_status[source_config.id] = current_status

    state.bootstrap_completed = state.bootstrap_completed or (
        statistics.sources_checked > 0 and statistics.errors == 0
    )
    state.last_run_at = checked_at
    if statistics.errors == 0:
        state.last_successful_check = checked_at
        state.last_fully_successful_run_at = checked_at
    else:
        state.last_degraded_run_at = checked_at
    duration_seconds = time.perf_counter() - started_at
    state.last_run_duration_seconds = duration_seconds
    state.last_run_new_publications = statistics.new_publications
    state.last_run_telegram_messages = statistics.sent + telegram_messages
    state.last_run_errors = statistics.errors
    if not dry_run:
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
    print(f"Duration: {duration_seconds:.2f}s")
    print(f"Sources: {statistics.sources_checked}")
    print(f"New publications: {statistics.new_publications}")
    print(f"Telegram messages: {0 if dry_run else state.last_run_telegram_messages}")
    print(f"Errors: {statistics.errors}")
    return state


def _send_health_message(telegram: TelegramClient, message: str) -> bool:
    try:
        telegram.send_message(message)
    except Exception:  # keep a health notification failure isolated from monitoring
        LOGGER.exception("Health notification failed")
        return False
    return True


def _source_failure_message(source: SourceConfig, status: SourceStatus) -> str:
    error = html.escape((status.error or "неизвестная ошибка")[:500])
    return (
        "⚠️ <b>Источник недоступен</b>\n\n"
        f"Источник: <b>{html.escape(source.name)}</b>\n"
        f"Ошибок подряд: <b>{status.consecutive_errors}</b>\n"
        f"Последняя успешная проверка: <b>"
        f"{_format_health_datetime(status.last_successful_check)}</b>\n"
        f"Ошибка: <code>{error}</code>"
    )


def _source_recovery_message(source: SourceConfig, checked_at: datetime) -> str:
    return (
        "✅ <b>Источник восстановлен</b>\n\n"
        f"Источник: <b>{html.escape(source.name)}</b>\n"
        f"Успешная проверка: <b>{_format_health_datetime(checked_at)}</b>"
    )


def _format_health_datetime(value: datetime | None) -> str:
    if value is None:
        return "никогда"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _ai_failure_message(error: str) -> str:
    return (
        "⚠️ <b>GitHub Models недоступен</b>\n\n"
        "AI-анализ отключён до конца этого запуска, а новости продолжат отправляться "
        "в обычном формате.\n"
        f"Причина: <code>{html.escape(error)}</code>"
    )


def _ai_recovery_message() -> str:
    return "✅ <b>GitHub Models восстановлен</b>\n\nAI-анализ новостей снова доступен."


def _run_failure_message(error: str) -> str:
    return (
        "🚨 <b>Запуск Dividend Monitor завершился с ошибкой</b>\n\n"
        f"Причина: <code>{html.escape(error)}</code>"
    )


def _safe_error_reason(error: BaseException | str) -> str:
    """Keep Telegram diagnostics useful without leaking credentials or long input text."""
    reason = str(error)
    reason = _SENSITIVE_ERROR_VALUE.sub("[скрыто]", reason)
    reason = _SENSITIVE_ERROR_ASSIGNMENT.sub("[скрыто]", reason)
    return _shorten(reason, 500)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one dividend monitor check")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--send-test-message", action="store_true")
    parser.add_argument("--send-existing-item", action="store_true")
    parser.add_argument(
        "--backfill", action="store_true", help="Explicitly deliver historical items"
    )
    parser.add_argument("--days", type=int, help="Limit explicit backfill to this many days")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.getenv("DRY_RUN", "").strip().lower() == "true",
        help="Prepare messages without Telegram delivery or state writes",
    )
    parser.add_argument("--workflow-name", default=os.getenv("GITHUB_WORKFLOW", "Dividend monitor"))
    args = parser.parse_args()
    if args.days is not None and (not args.backfill or args.days < 1):
        parser.error("--days must be a positive value used together with --backfill")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.dry_run:
        telegram: TelegramClient | DryRunTelegram = DryRunTelegram()
    else:
        try:
            telegram = TelegramClient.from_environment()
        except TelegramConfigurationError as exc:
            parser.error(str(exc))
    try:
        ai_client = client_from_environment()
        ai_filter_enabled, ai_min_importance = filter_from_environment()
        state = run(
            args.root,
            telegram,
            send_test_message=args.send_test_message,
            send_existing_item=args.send_existing_item,
            workflow_name=args.workflow_name,
            ai_client=ai_client,
            dry_run=args.dry_run,
            ai_filter_enabled=ai_filter_enabled,
            ai_min_importance=ai_min_importance,
            backfill=args.backfill,
            backfill_days=args.days,
        )
        sources = load_sources(args.root / Path("config/sources.yaml"))
    except ValueError as exc:
        if not args.dry_run:
            _send_health_message(telegram, _run_failure_message(_safe_error_reason(exc)))
        parser.error(str(exc))
    except Exception as exc:
        safe_error = _safe_error_reason(exc)
        LOGGER.exception("Dividend Monitor failed")
        if not args.dry_run:
            _send_health_message(telegram, _run_failure_message(safe_error))
        return 1
    return run_exit_code(state, sources)


if __name__ == "__main__":
    raise SystemExit(main())
