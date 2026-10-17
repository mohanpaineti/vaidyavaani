"""Push one interpreted turn to the Clinic Console.

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


# An optional `input` property is ALWAYS passed, as an empty string. unmute
# builds the call by keyword every time, so a Python default here is dead code:
# this receives "", never None. Hence `""` defaults and falsy checks below —
# rewriting one as `if x is None:` compiles clean and misbehaves on the first
# call, and neither validate nor compile says a word about it.
def push_turn(
    session_id,
    side,
    original_text,
    english_text,
    detected_language,
    lay_terms="",
    negations="",
):
    payload = {
        "session_id": session_id,
        "side": side,
        "original_text": original_text,
        "english_text": english_text,
        "detected_language": detected_language,
        "lay_terms": lay_terms or [],
        "negations": negations or [],
    }
    try:
        result = _post("/api/tools/turn", payload)
    except (urllib.error.URLError, OSError, ValueError):
        # A console that is down must not stop the interpreting. The turn was
        # already spoken aloud; losing it from the screen is the lesser harm.
        return {"ok": False}
    return {"ok": True, "turn_id": result.get("turn_id", "")}
