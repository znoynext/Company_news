import json
from pathlib import Path

import pytest

from dividend_monitor.models import MonitorState
from dividend_monitor.storage import JsonStateStorage


def test_failed_atomic_replace_preserves_existing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "state.json"
    storage = JsonStateStorage(state_path)
    storage.save(MonitorState(last_daily_summary_date="2026-07-13"))

    def fail_replace(_source: Path, _target: Path) -> Path:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(ValueError, match="Cannot save state file"):
        storage.save(MonitorState(last_daily_summary_date="2026-07-14"))

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["last_daily_summary_date"] == "2026-07-13"
