"""Health alerts and deterministic weekly system status reports."""

import html
from datetime import UTC, datetime, timedelta

from .models import MonitorState, SourceResult, SourcesConfig

WORKFLOW_STALE_AFTER = timedelta(hours=2)
EXIT_OK = 0
EXIT_DEGRADED = 2
EXIT_CRITICAL = 3


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "никогда"
    return _as_utc(value).strftime("%Y-%m-%d %H:%M UTC")


def _enabled_source_ids(sources: SourcesConfig) -> list[str]:
    return [source.id for source in sources.sources if source.enabled]


def run_exit_code(state: MonitorState, sources: SourcesConfig) -> int:
    """Return a non-zero process exit when monitoring produced no useful data."""
    enabled = [source for source in sources.sources if source.enabled]
    primary = [source for source in enabled if source.primary]
    statuses = state.source_status
    failed_primary = [
        source
        for source in primary
        if statuses.get(source.id) is None or statuses[source.id].status == "failed"
    ]
    if primary and len(failed_primary) == len(primary):
        return EXIT_CRITICAL
    if state.last_run_errors or any(
        statuses.get(source.id) and statuses[source.id].status == "degraded" for source in enabled
    ):
        return EXIT_DEGRADED
    return EXIT_OK


def source_result_from_status(source_id: str, state: MonitorState) -> SourceResult:
    """Provide a structured result for summaries from persisted source health."""
    status = state.source_status.get(source_id)
    if status is None:
        return SourceResult(source_id=source_id, status="failed", error_message="Not checked")
    return SourceResult(
        source_id=source_id,
        status=status.status,
        error_message=status.error,
        newest_publication_at=status.last_success_at,
    )


def build_workflow_stale_warning(state: MonitorState, now: datetime) -> str | None:
    last_run = state.last_successful_check
    if last_run is not None and _as_utc(now) - _as_utc(last_run) <= WORKFLOW_STALE_AFTER:
        return None
    return (
        "⚠️ <b>Основной workflow не выполнялся более 2 часов</b>\n\n"
        f"Последняя успешная проверка: <b>{html.escape(_format_datetime(last_run))}</b>."
    )


def build_weekly_health_report(
    state: MonitorState, sources: SourcesConfig, now: datetime
) -> str | None:
    checked_at = _as_utc(now)
    report_date = checked_at.date().isoformat()
    if checked_at.isoweekday() != 1 or state.last_weekly_health_report_date == report_date:
        return None

    source_ids = _enabled_source_ids(sources)
    source_names = {source.id: source.name for source in sources.sources if source.enabled}
    statuses = [state.source_status.get(source_id) for source_id in source_ids]
    nonworking = [status for status in statuses if status is None or status.status != "ok"]
    week_ago = checked_at - timedelta(days=7)
    new_publications = sum(_as_utc(item.sent_at) >= week_ago for item in state.sent_items)
    lines = [
        "📊 <b>Еженедельный отчёт состояния</b>",
        "",
        f"Активных источников: <b>{len(source_ids)}</b>",
        f"Неработающих источников: <b>{len(nonworking)}</b>",
        f"Новых публикаций за 7 дней: <b>{new_publications}</b>",
        f"Последний запуск: <b>{_format_datetime(state.last_successful_check)}</b>",
        "Источники:",
    ]
    for source_id, status in zip(source_ids, statuses, strict=True):
        if status is None:
            details = "не проверен"
        elif status.status == "ok":
            last_successful_check = status.last_successful_check or status.last_checked_at
            details = f"работает, {_format_datetime(last_successful_check)}"
        else:
            details = (
                f"ошибка ({status.consecutive_errors} подряд), "
                f"последняя успешная: {_format_datetime(status.last_successful_check)}"
            )
        lines.append(f"• <b>{html.escape(source_names[source_id])}</b>: {html.escape(details)}")

    duration = (
        f"{state.last_run_duration_seconds:.2f} с"
        if state.last_run_duration_seconds is not None
        else "нет данных"
    )
    lines.extend(
        [
            "",
            f"Время выполнения GitHub Actions: <b>{duration}</b>",
            f"Ошибок в последнем запуске: <b>{state.last_run_errors}</b>",
        ]
    )
    return "\n".join(lines)
