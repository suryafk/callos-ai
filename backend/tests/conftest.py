from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import database
from app.config import Settings, set_settings
from app.main import create_app

TOOL_KEY = "test-tool-key-000000000000000000"
ADMIN_KEY = "test-admin-key-00000000000000000"
PIN_AARAV = "482916"
PIN_PRIYA = "731205"
TOOL_HEADERS = {"Authorization": f"Bearer {TOOL_KEY}"}
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_KEY}


def _database_url(tmp_path) -> str:
    """SQLite file per test by default. Set CALLOS_TEST_DATABASE_URL to run the suite on PostgreSQL."""
    url = os.environ.get("CALLOS_TEST_DATABASE_URL")
    if not url:
        return f"sqlite:///{tmp_path}/callos-test.db"
    # Shared server: start every app from an empty schema.
    from app import models  # noqa: F401

    probe = Settings(_env_file=None, database_url=url)
    engine = database.init_engine(probe.sqlalchemy_url)
    database.Base.metadata.drop_all(engine)
    return url


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        env="development", database_url=_database_url(tmp_path),
        tool_api_key=TOOL_KEY, admin_api_key=ADMIN_KEY, demo_user_pin=PIN_AARAV,
        demo_second_user_pin=PIN_PRIYA, demo_auth_enabled=True, seed_demo_data=True,
        dev_tools_enabled=True, dev_fallback_session_id="", log_level="WARNING",
        default_timezone="Asia/Kolkata", action_ttl_minutes=15, auth_ttl_minutes=60,
        max_pin_attempts=5, global_pin_failure_limit=20, integration_mode="mock",
        cors_origins="http://localhost:5173",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
    set_settings(None)


class Caller:
    """Drives the API the way the voice agent does for one call."""

    def __init__(self, client: TestClient, session_id: str) -> None:
        self.client, self.session_id = client, session_id

    def tool(self, action: str, **params) -> dict:
        r = self.client.post("/api/voice/action", headers=TOOL_HEADERS,
                             json={"session_id": self.session_id, "action": action, "parameters": params})
        assert r.status_code == 200, r.text
        return r.json()

    def verify(self, pin: str = PIN_AARAV) -> dict:
        return self.tool("verify_identity", access_code=pin)

    def approve(self, action_id, version) -> dict:
        r = self.client.post("/api/actions/approve", headers=TOOL_HEADERS,
                             json={"session_id": self.session_id, "action_id": action_id, "version": version})
        assert r.status_code == 200, r.text
        return r.json()

    def cancel(self, action_id=None) -> dict:
        r = self.client.post("/api/actions/cancel", headers=TOOL_HEADERS,
                             json={"session_id": self.session_id, "action_id": action_id})
        assert r.status_code == 200, r.text
        return r.json()

    def events(self) -> list[dict]:
        r = self.client.get(f"/api/sessions/{self.session_id}/events", headers=TOOL_HEADERS)
        assert r.status_code == 200, r.text
        return r.json()["events"]

    def state(self) -> dict:
        r = self.client.get(f"/api/sessions/{self.session_id}", headers=TOOL_HEADERS)
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture
def anon(client) -> Caller:
    return Caller(client, "call-anon-001")


@pytest.fixture
def caller(client) -> Caller:
    """A call verified as the demo user (Aarav)."""
    c = Caller(client, "call-aarav-001")
    assert c.verify()["ok"]
    return c


@pytest.fixture
def priya(client) -> Caller:
    c = Caller(client, "call-priya-001")
    assert c.verify(PIN_PRIYA)["ok"]
    return c


@pytest.fixture
def db(client):
    session = database.new_session()
    yield session
    session.close()
