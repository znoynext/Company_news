from datetime import UTC, datetime, timedelta

from dividend_monitor.health import build_weekly_health_report, build_workflow_stale_warning
from dividend_monitor.models import MonitorState, SourcesConfig, SourceStatus


def sources_config() -> SourcesConfig:
    return SourcesConfig(
        version=1,
        sources=[
            {
                "id": "working",
                "name": "Working source",
                "type": "fixture",
                "companies": ["SBER"],
                "categories": ["news"],
            },
            {
                "id": "broken",
                "name": "Broken source",
                "type": "fixture",
                "companies": ["SBER"],
                "categories": ["news"],
            },
        ],
    )


def test_weekly_report_contains_source_health_and_run_metrics() -> None:
    now = datetime(2026, 7, 13, 8, 17, tzinfo=UTC)
    state = MonitorState(
        last_successful_check=now,
        last_run_duration_seconds=12.5,
        last_run_new_publications=3,
        last_run_errors=1,
        sent_items=[],
        source_status={
            "working": SourceStatus(
                last_checked_at=now,
                last_successful_check=now,
                status="ok",
            ),
            "broken": SourceStatus(
                last_checked_at=now,
                status="error",
                consecutive_errors=3,
                error="timeout",
            ),
        },
    )

    report = build_weekly_health_report(state, sources_config(), now)

    assert report is not None
    assert "Активных источников: <b>2</b>" in report
    assert "Неработающих источников: <b>1</b>" in report
    assert "Working source" in report
    assert "Broken source" in report
    assert "12.50 с" in report


def test_workflow_stale_warning_is_only_for_old_or_missing_run() -> None:
    now = datetime(2026, 7, 13, 8, 17, tzinfo=UTC)
    assert build_workflow_stale_warning(MonitorState(last_successful_check=now), now) is None
    warning = build_workflow_stale_warning(
        MonitorState(last_successful_check=now - timedelta(hours=2, minutes=1)), now
    )
    assert warning is not None
    assert "более 2 часов" in warning
