import json
from pathlib import Path

import pytest

from dividend_monitor.models import MonitorState
from dividend_monitor.storage import JsonStateStorage, merge_states


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


def test_legacy_state_is_migrated_without_discarding_sent_history(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        '{"schema_version": 4, "sent_items": [], "source_status": {}}', encoding="utf-8"
    )

    state = JsonStateStorage(state_path).load()

    assert state.schema_version == 7
    assert state.identity_version == 2
    assert state_path.with_suffix(".json.bak").exists()


def test_merge_states_retains_identities_from_both_sides() -> None:
    left = MonitorState(identity_index={"left"})
    right = MonitorState(identity_index={"right"})

    assert merge_states(left, right).identity_index == {"left", "right"}
