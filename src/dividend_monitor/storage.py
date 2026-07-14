"""JSON state storage."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .deduplication import sent_item_identity
from .models import MonitorState, SentItem

CURRENT_SCHEMA_VERSION = 7


class UnsupportedStateVersion(ValueError):
    """Raised when state was written by a newer application version."""


def migrate_v6_to_v7(payload: dict[str, Any]) -> dict[str, Any]:
    """Add stable identity and delivery metadata without re-sending history."""
    identity_index = set(payload.get("identity_index", []))
    for item in payload.get("sent_items", []):
        if isinstance(item, dict):
            identifier = item.get("fingerprint") or item.get("deduplication_id")
            if isinstance(identifier, str):
                identity_index.add(identifier)
            try:
                identity_index.add(sent_item_identity(SentItem.model_validate(item)))
            except ValueError:
                continue
    for status in payload.get("source_status", {}).values():
        if isinstance(status, dict) and status.get("status") == "error":
            status["status"] = "failed"
    payload["identity_version"] = 2
    payload["identity_index"] = sorted(identity_index)
    payload.setdefault("ai_usage", {})
    payload.setdefault("source_cursors", {})
    payload.setdefault("bootstrap_completed", bool(payload.get("sent_items")))
    payload["schema_version"] = 7
    return payload


def migrate_v4_to_v5(payload: dict[str, Any]) -> dict[str, Any]:
    """Preserve legacy state while introducing the v5 optional AI fields."""
    payload.setdefault("ai_failure_alert_sent", False)
    payload.setdefault("ai_last_error", None)
    payload.setdefault("ai_cache", {})
    payload["schema_version"] = 5
    return payload


def migrate_v5_to_v6(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the v6 schema transition explicit for future state evolution."""
    payload.setdefault("financial_reports", [])
    payload.setdefault("source_status", {})
    payload["schema_version"] = 6
    return payload


MIGRATIONS = {4: migrate_v4_to_v5, 5: migrate_v5_to_v6, 6: migrate_v6_to_v7}


def merge_states(local: MonitorState, remote: MonitorState) -> MonitorState:
    """Deterministically merge state after a concurrent Git update.

    It intentionally favours the newest delivery record while retaining every
    stable identity so a conflict cannot resurrect an old publication.
    """
    merged = remote.model_copy(deep=True)
    by_identity = {
        item.fingerprint or item.deduplication_id: item
        for item in [*remote.sent_items, *local.sent_items]
    }
    merged.sent_items = sorted(by_identity.values(), key=lambda item: item.sent_at)
    merged.identity_index = remote.identity_index | local.identity_index | set(by_identity)
    merged.ai_cache = {**remote.ai_cache, **local.ai_cache}
    merged.source_cursors = {**remote.source_cursors, **local.source_cursors}
    merged.financial_reports = [*remote.financial_reports, *local.financial_reports][-100:]
    merged.last_run_at = _latest_datetime(remote.last_run_at, local.last_run_at)
    merged.last_successful_check = _latest_datetime(
        remote.last_successful_check, local.last_successful_check
    )
    merged.last_fully_successful_run_at = _latest_datetime(
        remote.last_fully_successful_run_at, local.last_fully_successful_run_at
    )
    merged.last_degraded_run_at = _latest_datetime(
        remote.last_degraded_run_at, local.last_degraded_run_at
    )
    merged.bootstrap_completed = remote.bootstrap_completed or local.bootstrap_completed
    return merged


def _latest_datetime(first: Any, second: Any) -> Any:
    return max((value for value in (first, second) if value is not None), default=None)


class JsonStateStorage:
    """Read and atomically write the monitor state file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> MonitorState:
        if not self.path.exists():
            return MonitorState()
        try:
            with self.path.open("r", encoding="utf-8") as file:
                payload: dict[str, Any] = json.load(file)
            version = int(payload.get("schema_version", 6))
            if version > CURRENT_SCHEMA_VERSION:
                raise UnsupportedStateVersion(
                    "State schema "
                    f"{version} is newer than supported schema {CURRENT_SCHEMA_VERSION}"
                )
            migrated = False
            while version < CURRENT_SCHEMA_VERSION:
                migration = MIGRATIONS.get(version)
                if migration is None:
                    raise ValueError(f"No migration from state schema {version}")
                if not migrated:
                    shutil.copy2(self.path, self.path.with_suffix(f"{self.path.suffix}.bak"))
                    migrated = True
                payload = migration(payload)
                version = int(payload["schema_version"])
            state = MonitorState.model_validate(payload)
            state.identity_index.update(
                item.fingerprint or item.deduplication_id for item in state.sent_items
            )
            state.identity_index.update(sent_item_identity(item) for item in state.sent_items)
            return state
        except UnsupportedStateVersion:
            raise
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid state file: {self.path}") from exc

    def save(self, state: MonitorState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        payload = state.model_dump(mode="json")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            temporary_path.replace(self.path)
        except OSError as exc:
            raise ValueError(f"Cannot save state file: {self.path}") from exc
