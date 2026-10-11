"""Small, safe .env editor used by the setup wizard.

Keeps comments and ordering, replaces a value in place (or un-comments a `# KEY=` template line),
appends new keys at the end, and always writes a one-time backup before the first change.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

_LINE = re.compile(r"^\s*(#\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def read_env(path: Path) -> dict[str, str]:
    """Active (non-commented) KEY=VALUE pairs."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(raw)
        if m and not m.group(1):
            values[m.group(2)] = m.group(3).strip().strip('"').strip("'")
    return values


def _format(value: str) -> str:
    return f'"{value}"' if re.search(r"\s|#", value) else value


def set_values(path: Path, updates: dict[str, str], *, backup: bool = True) -> list[str]:
    """Apply updates; returns the keys that actually changed."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    current = read_env(path)
    changed = [k for k, v in updates.items() if current.get(k) != v]
    if not changed:
        return []
    if backup and path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))

    pending = {k: updates[k] for k in changed}
    out: list[str] = []
    for raw in lines:
        m = _LINE.match(raw)
        if m and m.group(2) in pending:
            key = m.group(2)  # replaces the active line, or revives a `# KEY=` template line
            out.append(f"{key}={_format(pending.pop(key))}")
        else:
            out.append(raw)
    # Duplicate active lines for the same key would shadow our value: drop later duplicates.
    seen: set[str] = set()
    deduped = []
    for raw in out:
        m = _LINE.match(raw)
        if m and not m.group(1) and m.group(2) in updates:
            if m.group(2) in seen:
                continue
            seen.add(m.group(2))
        deduped.append(raw)
    out = deduped
    if pending:
        if out and out[-1].strip():
            out.append("")
        out.extend(f"{k}={_format(v)}" for k, v in pending.items())
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed
