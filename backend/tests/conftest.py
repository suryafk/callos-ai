import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from store import store  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_store():
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def call(client):
    def _call(action, session_id="t-1", **parameters):
        r = client.post("/api/voice/action",
                        json={"session_id": session_id, "action": action, "parameters": parameters})
        assert r.status_code == 200, r.text
        return r.json()
    return _call
