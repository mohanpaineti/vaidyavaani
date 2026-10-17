"""Compare the patient's read-back against the confirmed prescription.

The comparison itself is arithmetic in console/app/teachback.py — numbers are
compared as numbers, not judged by a model. This handler only carries the
patient's words there and the verdict back.

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


def compare_teachback(session_id, patient_text, english_text):
    payload = {
        "session_id": session_id,
        "patient_text": patient_text,
        "english_text": english_text,
    }
    try:
        result = _post("/api/tools/teachback", payload)
    except (urllib.error.URLError, OSError, ValueError):
        # not_attempted does not satisfy the task's success check, so the task
        # stays open and the agent can try again rather than recording a match
        # nobody computed.
        return {"overall": "not_attempted"}

    overall = result.get("overall")
    if overall not in ("match", "mismatch"):
        return {"overall": "not_attempted"}
    return {
        "overall": overall,
        "teachback": {
            "overall": overall,
            "mismatched_fields": result.get("mismatched_fields", []),
        },
        "simplest_restatement": result.get("simplest_restatement", ""),
    }
