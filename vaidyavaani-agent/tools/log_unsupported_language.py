"""Record a request for a language this assistant does not cover.

The demand log is the only thing in this build that outlives a session, and it
holds a language name, not a patient.

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
def log_unsupported_language(session_id, requested_language, note=""):
    payload = {
        "session_id": session_id,
        "requested_language": requested_language,
        "note": note or "",
    }
    try:
        result = _post("/api/tools/unsupported-language", payload)
    except (urllib.error.URLError, OSError, ValueError):
        return {"ok": False, "second_language_offer": "kn"}
    return {
        "ok": True,
        "second_language_offer": result.get("second_language_offer", "kn"),
    }
