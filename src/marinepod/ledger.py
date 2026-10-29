from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class Ledger:
    """Append-only JSONL record of every paid generation request and episode-level event."""

    def __init__(self, path: str | Path = "ledger/generation_ledger.jsonl"):
        self.path = Path(path)

    def append(self, **record) -> dict:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def credits_this_month(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        prefix = now.strftime("%Y-%m")
        return sum(
            int(r.get("credits", 0))
            for r in self.records()
            if r.get("event") == "segment_generated" and str(r.get("ts", "")).startswith(prefix)
        )
