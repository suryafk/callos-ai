"""Authentication dependencies for the HTTP API."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.utils.security import keys_equal


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def require_tool_key(authorization: str | None = Header(None),
                     settings: Settings = Depends(get_settings)) -> None:
    """Server-to-server credential presented by the voice platform on tool calls."""
    if not keys_equal(_bearer(authorization), settings.tool_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid tool credential",
                            headers={"WWW-Authenticate": "Bearer"})


def require_admin_key(x_admin_key: str | None = Header(None),
                      settings: Settings = Depends(get_settings)) -> None:
    if not keys_equal(x_admin_key, settings.admin_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid admin credential")


def require_tool_or_admin_key(authorization: str | None = Header(None), x_admin_key: str | None = Header(None),
                              settings: Settings = Depends(get_settings)) -> None:
    if keys_equal(_bearer(authorization), settings.tool_api_key) or keys_equal(x_admin_key, settings.admin_api_key):
        return
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid credential")


def require_dev_tools(settings: Settings = Depends(get_settings)) -> None:
    """Development-only routes do not exist when dev tools are off."""
    if not settings.dev_tools_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
