"""The demand log — the only thing that outlives a session.

Append-only JSONL: which language was asked for that we cannot serve. No patient identifiers, no
transcript, no audio. This file is the entire persistence story of the console.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import config
from .models import now_iso

log = logging.getLogger("console.demand_log")

# The second language we offer when the requested one is unsupported, in Bengaluru.
SECOND_LANGUAGE_OFFER = "kn"


def log_unsupported_language(
    requested_language: str, note: str = "", path: Path | None = None
) -> dict:
    """Record a request for a language we do not serve (Tulu, Kodava, Bhojpuri, …)."""
    target = Path(path) if path is not None else config.DEMAND_LOG_PATH
    record = {
        "at": now_iso(),
        "requested_language": (requested_language or "").strip()[:64],
        "note": (note or "").strip()[:280],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        log.exception("could not append to the demand log at %s", target)
    return {"ok": True, "second_language_offer": SECOND_LANGUAGE_OFFER}


def read_all(path: Path | None = None) -> list[dict]:
    target = Path(path) if path is not None else config.DEMAND_LOG_PATH
    if not target.exists():
        return []
    records = []
    for raw in target.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return records
