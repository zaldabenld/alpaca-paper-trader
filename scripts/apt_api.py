"""Tiny client for local maintenance scripts that call the running trader's API.

POST/DELETE requests need the per-launch token the app writes to instance.json:

    from apt_api import get, post
    post("/api/start", {"account_id": "..."})
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

INSTANCE_PATH = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader" / "instance.json"


def _instance() -> dict[str, Any]:
    return json.loads(INSTANCE_PATH.read_text(encoding="utf-8"))


def get(path: str) -> Any:
    with urllib.request.urlopen(_instance()["url"] + path, timeout=30) as response:
        return json.load(response)


def post(path: str, body: dict[str, Any], method: str = "POST") -> Any:
    instance = _instance()
    request = urllib.request.Request(
        instance["url"] + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-APT-Token": instance.get("api_token", "")},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)
