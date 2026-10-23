"""State for the sample flows (checkout pending -> paid, invitation sent -> accepted -> completed).

Kept in one JSON file (settings.SAMPLE_STATE_FILE) behind a file lock, so every server worker on
the machine sees the same state. It is sample data only: it disappears when the machine restarts
and is never written to the database.
"""

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.config import settings


def _path() -> Path:
    return Path(settings.SAMPLE_STATE_FILE)


@contextmanager
def transaction() -> Iterator[dict[str, Any]]:
    """Lock the state, hand it out for reading and changing, and save it on the way out."""
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.seek(0)
            raw = handle.read()
            state: dict[str, Any] = json.loads(raw) if raw.strip() else {}
            yield state
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(state, default=str))
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def next_id(state: dict[str, Any], kind: str, start: int) -> int:
    counters = state.setdefault("next_id", {})
    value = counters.get(kind, start)
    counters[kind] = value + 1
    return value


def reset() -> None:
    """Forget every sample flow (tests, or POST /sample/reset)."""
    _path().unlink(missing_ok=True)
