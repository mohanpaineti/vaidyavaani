"""THE GATE. Long-poll the console for the doctor's tap.

The console holds the request open for up to about 25 seconds and answers the
moment the doctor acts, so this returns promptly on a tap and returns `pending`
on a timeout. The confirm_prescription task names this tool in `finish:` with
success on `status: confirmed`, so any other status goes back to the model with
the task still open.

Every failure path here returns `pending`, never `confirmed`. A console that is
unreachable, a reply that will not parse, an HTTP error: all of them mean the
agent waits and asks again. There is no error in this file that can open the
gate.

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


GATE_TIMEOUT_SECONDS = 30  # the console long-polls for ~25s; leave it headroom


def await_doctor_confirmation(session_id):
    url = (
        os.environ["CONSOLE_URL"].rstrip("/")
        + "/api/sessions/"
        + str(session_id)
        + "/confirmation"
    )
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"X-Console-Token": os.environ["CONSOLE_TOKEN"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=GATE_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError):
        return {"status": "pending", "confirmed": False}

    status = result.get("status")
    if status == "confirmed":
        readback_text = result.get("readback_text") or ""
        if not readback_text:
            # Confirmed with nothing to read is not a usable confirmation, and
            # guessing the sentence is the one thing this design forbids.
            return {"status": "pending", "confirmed": False}
        return {"status": "confirmed", "confirmed": True, "readback_text": readback_text}
    if status == "rejected":
        return {
            "status": "rejected",
            "confirmed": False,
            "reason": result.get("reason", ""),
        }
    return {"status": "pending", "confirmed": False}
