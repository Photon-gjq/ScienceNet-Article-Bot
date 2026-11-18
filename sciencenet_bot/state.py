"""Keep the original JSON list format; refuse corrupt/missing delivery history."""

import json
import os
import tempfile
from pathlib import Path


class StateError(RuntimeError):
    pass


def load_ids(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StateError(
            f"Cannot read delivery history: {path}. Restore it before running the bot."
        ) from None
    if not isinstance(data, list) or any(
        not isinstance(item, str) or not item.isascii() or not item.isdecimal() for item in data
    ):
        raise StateError("Delivery history must be a JSON list of numeric article ID strings")
    return set(data)


def save_ids(path: Path, ids: set[str]) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(sorted(ids, key=int), handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError:
        raise StateError(f"Cannot save delivery history: {path}") from None
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
