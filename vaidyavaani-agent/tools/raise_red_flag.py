"""Put a danger sign on the doctor's half of the screen.

Standard library only (json, os, urllib) so that nothing has to be added to the
generated pyproject.toml — the compiler builds that list from the chosen
providers, and `local.dependencies` is refused on LiveKit.

The _post helper is copy-pasted into every handler on purpose. unmute compiles
each handler into its own module under tools/<tool-name>.py and does not follow
its imports, so a shared tools/shared.py would simply not be bundled. (One
authored file naming itself as the handler of several tools is also supported;
we keep one file per tool so each contract and its code sit together.)
"""

import json
import os
import urllib.error
import urllib.request

CONSOLE_TIMEOUT_SECONDS = 10


def _post(path, payload):
    """POST JSON to the Clinic Console and return its decoded reply.

    Raises urllib.error.URLError or OSError if the console cannot be reached;
    each handler decides what a failure means for the consultation.
    """
    url = os.environ["CONSOLE_URL"].rstrip("/") + path
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Console-Token": os.environ["CONSOLE_TOKEN"],
        },
    )
    with urllib.request.urlopen(request, timeout=CONSOLE_TIMEOUT_SECONDS) as response:
        body = response.read()
    return json.loads(body) if body else {}


def raise_red_flag(session_id, phrase, english, severity, source):
    payload = {
        "session_id": session_id,
        "phrase": phrase,
        "english": english,
        "severity": severity,
        "source": source,
    }
    try:
        _post("/api/tools/red-flag", payload)
    except (urllib.error.URLError, OSError, ValueError):
        return {"ok": False}
    return {"ok": True}
