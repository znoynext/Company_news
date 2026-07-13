"""JSON state storage."""

import json
import os
from pathlib import Path

from .models import MonitorState


class JsonStateStorage:
    """Read and atomically write the monitor state file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> MonitorState:
        if not self.path.exists():
            return MonitorState()
        try:
            with self.path.open("r", encoding="utf-8") as file:
                state = MonitorState.model_validate(json.load(file))
                if state.schema_version < MonitorState.model_fields["schema_version"].default:
                    state.schema_version = MonitorState.model_fields["schema_version"].default
                return state
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
