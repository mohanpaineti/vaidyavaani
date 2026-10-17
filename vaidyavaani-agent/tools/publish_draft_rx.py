"""Publish the draft prescription to the doctor's editable card.

Nothing here validates a dose. That happens twice elsewhere, and both are
stronger than a check in this file: unmute validates the capture_prescription
task's `assign:` against RxLine in state.py before saving it, and the doctor
confirms every line on screen before the gate opens.

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
def publish_draft_rx(session_id, lines, ambiguities=""):
    payload = {
        "session_id": session_id,
        "lines": lines,
        "ambiguities": ambiguities or [],
    }
    try:
        result = _post("/api/tools/draft-rx", payload)
    except (urllib.error.URLError, OSError, ValueError):
        # Report the failure rather than an empty success: the model is told the
        # card is not on screen, and the doctor cannot confirm what they cannot
        # see, so the gate stays shut.
        return {"ok": False, "line_ids": []}
    return {"ok": True, "line_ids": result.get("line_ids", [])}
