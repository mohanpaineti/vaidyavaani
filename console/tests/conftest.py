"""Test setup. Every test runs against the fixture content, never the real content/ directory."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

CONSOLE_DIR = Path(__file__).resolve().parent.parent
FIXTURES = CONSOLE_DIR / "tests" / "fixtures"

REPO_ROOT = CONSOLE_DIR.parent
REAL_CONTENT = REPO_ROOT / "content"

# Tests run against the REAL content/, owned by the content-eval session. There is deliberately
# no snapshot copy under tests/fixtures/: a hand-copied one drifts, and a stale copy once
# manufactured a failure that two sessions chased. Mutation tests take a throwaway copy of the
# real files via the `content_copy` fixture below.
# Must happen before app.config is imported.
os.environ.setdefault("CONSOLE_CONTENT_DIR", str(REAL_CONTENT))
os.environ.setdefault("CONSOLE_TOKEN", "test-console-token")
os.environ.setdefault("CONSOLE_DEV_LOG", str(FIXTURES / "dev.log.sample"))
os.environ.setdefault("CONSOLE_LOG_LEVEL", "WARNING")

sys.path.insert(0, str(CONSOLE_DIR))

from app import config  # noqa: E402

config.CONFIRMATION_LONGPOLL_SECONDS = 1.0
config.DEMAND_LOG_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / "vaidyavaani-test-demand.jsonl"

CONSOLE_TOKEN_HEADER = {"X-Console-Token": config.CONSOLE_TOKEN}


def content_present() -> bool:
    from app import readback

    return all(
        (REAL_CONTENT / "readback" / f"{language}.yaml").exists()
        for language in readback.READBACK_LANGUAGES
    )


requires_content = pytest.mark.skipif(
    not (REAL_CONTENT / "readback" / "ta.yaml").exists(),
    reason=(
        f"{REAL_CONTENT}/readback/*.yaml not present — owned by the content-eval session. "
        "The console renders no read-back without it and ships no snapshot copy."
    ),
)


@pytest.fixture
def content_copy(tmp_path):
    """A writable copy of the real content/, for tests that need to break a template."""
    import shutil

    destination = tmp_path / "content"
    shutil.copytree(REAL_CONTENT, destination)
    return destination


@pytest.fixture
def store():
    from app.sessions import store as session_store

    for session_id in session_store.ids():
        session_store.purge(session_id, "test teardown")
    yield session_store
    for session_id in session_store.ids():
        session_store.purge(session_id, "test teardown")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def run():
    """Run a coroutine in a fresh event loop (there is no pytest-asyncio here)."""

    def _run(coro):
        return asyncio.run(coro)

    return _run


def make_line(**overrides):
    from app.models import RxLine, Schedule

    base = dict(
        id="rx_1",
        drug_text="Paracetamol",
        strength_value=500,
        strength_unit="mg",
        form="tablet",
        schedule=Schedule(morning=1, afternoon=0, night=1),
        food_relation="after_food",
        duration_days=5,
        confidence=0.91,
        confirmed=False,
    )
    base.update(overrides)
    return RxLine(**base)
