"""The persistent spend ledger, and the check that runs before every request.

One JSON object per line, appended and synced to disk before the request is sent:

    {"event": "reserve", "id": ..., "worst_case_usd": ...}   before the request
    {"event": "settle",  "id": ..., "cost_usd": ...}         when usage came back
    {"event": "release", "id": ..., "reason": ...}           the API answered with an error status

Spend is the settled costs plus the worst case of every reservation still open. So if the process dies
during a request, or a connection drops and nobody knows whether the server ran it, the ledger
assumes the worst. Spend can be overestimated and is not knowingly underestimated. Holds no credentials.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


class BudgetExceeded(Exception):
    pass


class Ledger:
    def __init__(self, path: Path, client_kind: str) -> None:
        self.path = path
        self.client_kind = client_kind

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"client": self.client_kind, "time": time.time(), **record}
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        return [record for record in records if record.get("client") == self.client_kind]

    def spent_usd(self) -> float:
        open_reservations: dict[str, float] = {}
        settled = 0.0
        for record in self._records():
            if record["event"] == "reserve":
                open_reservations[record["id"]] = record["worst_case_usd"]
            elif record["event"] == "settle":
                open_reservations.pop(record["id"], None)
                settled += record["cost_usd"]
            elif record["event"] == "release":
                open_reservations.pop(record["id"], None)
        return settled + sum(open_reservations.values())

    def reserve(self, worst_case_usd: float, cap_usd: float | None, tag: str) -> str:
        """Record the intention to send a request, or raise BudgetExceeded if it might not fit."""
        spent = self.spent_usd()
        if cap_usd is not None and (spent >= cap_usd or spent + worst_case_usd > cap_usd):
            raise BudgetExceeded(
                f"{tag}: spent ${spent:.4f} of ${cap_usd:.2f}, and the next request could cost ${worst_case_usd:.4f}"
            )
        reservation = uuid.uuid4().hex
        self._append({"event": "reserve", "id": reservation, "worst_case_usd": worst_case_usd, "tag": tag})
        return reservation

    def settle(self, reservation: str, cost_usd: float, usage: list[dict[str, Any]], request_id: str | None) -> None:
        self._append({"event": "settle", "id": reservation, "cost_usd": cost_usd, "usage": usage, "request_id": request_id})

    def release(self, reservation: str, reason: str) -> None:
        self._append({"event": "release", "id": reservation, "reason": reason})
