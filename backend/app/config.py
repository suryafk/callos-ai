"""Application settings, loaded from environment variables (prefix ``CALLOS_``)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_TOOL_KEY = "dev-tool-key-change-me"
DEV_ADMIN_KEY = "dev-admin-key-change-me"
DEV_DEMO_PIN = "482916"
DEV_SECOND_PIN = "731205"


class ConfigurationError(RuntimeError):
    """Raised at startup when the configuration is unsafe for the chosen environment."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CALLOS_", env_file=(".env", "../.env"), extra="ignore"
    )

    # development: local machine. demo: publicly reachable hackathon demo.
    # production: real users (demo authentication is refused).
    env: str = "development"
    database_url: str = "sqlite:///./callos.db"

    # Server-to-server credential presented by Bolna on every tool call.
    tool_api_key: str = DEV_TOOL_KEY
    # Credential for the admin dashboard / inspection routes.
    admin_api_key: str = DEV_ADMIN_KEY

    cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174,http://localhost:5173"
    default_timezone: str = "Asia/Kolkata"
    action_ttl_minutes: int = 15
    auth_ttl_minutes: int = 60
    max_pin_attempts: int = 5
    global_pin_failure_limit: int = 20  # failures across all sessions per 15 minutes

    # NON-PRODUCTION demo authentication (spoken access code).
    demo_auth_enabled: bool = True
    demo_user_pin: str = DEV_DEMO_PIN
    demo_second_user_pin: str = DEV_SECOND_PIN
    seed_demo_data: bool = True

    # Development-only simulator / reset routes used by the dashboard.
    dev_tools_enabled: bool = True
    # Development-only: session id used when Bolna does not substitute {call_sid}.
    dev_fallback_session_id: str = ""

    integration_mode: str = "mock"
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.env.lower() == "development"

    @property
    def dev_tools_active(self) -> bool:
        return self.dev_tools_enabled and not self.is_production

    @property
    def demo_auth_active(self) -> bool:
        return self.demo_auth_enabled and not self.is_production

    @property
    def fallback_session_id(self) -> str:
        return self.dev_fallback_session_id if self.is_development else ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        # Hosting platforms commonly hand out postgres:// URLs.
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    def validate_for_environment(self) -> None:
        """Refuse to start with development secrets outside local development."""
        if self.is_development:
            return
        problems: list[str] = []
        if self.tool_api_key == DEV_TOOL_KEY or len(self.tool_api_key) < 24:
            problems.append("CALLOS_TOOL_API_KEY must be a unique secret of at least 24 characters")
        if self.admin_api_key == DEV_ADMIN_KEY or len(self.admin_api_key) < 24:
            problems.append("CALLOS_ADMIN_API_KEY must be a unique secret of at least 24 characters")
        if self.tool_api_key == self.admin_api_key:
            problems.append("CALLOS_TOOL_API_KEY and CALLOS_ADMIN_API_KEY must differ")
        if self.integration_mode != "mock":
            problems.append("only CALLOS_INTEGRATION_MODE=mock is implemented")
        if self.is_production and self.demo_auth_enabled:
            problems.append(
                "CALLOS_DEMO_AUTH_ENABLED must be false in production: the spoken access "
                "code is a demo mechanism, not production authentication"
            )
        if not self.is_production and self.demo_auth_enabled and (
            self.demo_user_pin == DEV_DEMO_PIN or self.demo_second_user_pin == DEV_SECOND_PIN
        ):
            problems.append("set CALLOS_DEMO_USER_PIN and CALLOS_DEMO_SECOND_USER_PIN to non-default values")
        if problems:
            raise ConfigurationError("Unsafe configuration: " + "; ".join(problems))


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def set_settings(settings: Settings | None) -> None:
    """Override the cached settings (used by tests and the app factory)."""
    global _settings
    _settings = settings
