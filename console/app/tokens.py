"""LiveKit join tokens for the browser.

A LiveKit access token is a plain HS256 JWT with a `video` grant, so this is hand-rolled on the
stdlib — the console adds no crypto dependency for it.

**The token also dispatches the agent**, and that is not a detail. The generated worker registers
with an explicit `agent_name`, and LiveKit excludes a named worker from automatic dispatch: it
joins only when something asks for it by name. Without that, the room gets LiveKit's default
empty-name dispatch, which matches no worker — the browser sits alone in the room, the patient
speaks, and nothing listens. Nothing errors, either: the token parses, the room exists, the
participant connects. The only symptom is silence.

So every join token carries a `roomConfig` claim naming the agent, applied when the room is
created by this join. The name comes from `config.LIVEKIT_AGENT_NAME`, which documents where the
compiled worker gets it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from . import config


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def mint_join_token(
    room_name: str,
    identity: str,
    *,
    name: str | None = None,
    ttl_seconds: int | None = None,
    can_publish: bool = True,
    can_subscribe: bool = True,
    agent_name: str | None = None,
) -> str:
    """Mint a room-join token. HS256 over the LiveKit API secret, per LiveKit's token format.

    `agent_name` defaults to `config.LIVEKIT_AGENT_NAME`; pass `""` for a token that dispatches
    nothing (a second observer joining a room the agent is already in, say).
    """
    issued = int(time.time())
    ttl = config.LIVEKIT_TOKEN_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    payload = {
        "iss": config.LIVEKIT_API_KEY,
        "sub": identity,
        "iat": issued,
        "nbf": issued,
        "exp": issued + ttl,
        "name": name or identity,
        "video": {
            "room": room_name,
            "roomJoin": True,
            "canPublish": can_publish,
            "canSubscribe": can_subscribe,
            "canPublishData": True,
            # The room is created by this join, so the join is what gets to configure it.
            "roomCreate": True,
        },
    }
    dispatch_to = config.LIVEKIT_AGENT_NAME if agent_name is None else agent_name
    if dispatch_to:
        # LiveKit's RoomConfiguration, a sibling of `video`: dispatch this named agent into the
        # room on creation. A worker registered with an agent_name is not auto-dispatched.
        payload["roomConfig"] = {"agents": [{"agentName": dispatch_to}]}
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        (
            _b64(json.dumps(header, separators=(",", ":")).encode()),
            _b64(json.dumps(payload, separators=(",", ":")).encode()),
        )
    ).encode("ascii")
    signature = hmac.new(
        config.LIVEKIT_API_SECRET.encode(), signing_input, hashlib.sha256
    ).digest()
    return signing_input.decode("ascii") + "." + _b64(signature)


def decode_unverified(token: str) -> dict:
    """Read a token's claims without checking the signature. For tests and /healthz only."""
    _, payload, _ = token.split(".")
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))
