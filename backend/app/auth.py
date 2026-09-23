from __future__ import annotations

from fastapi import Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import API_KEY

bearer_scheme = HTTPBearer(auto_error=False)


def verify_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    auth: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> str:
    """Verify request contains valid API Key via X-API-Key header or Bearer token."""
    if x_api_key and x_api_key == API_KEY:
        return x_api_key

    if auth and auth.credentials == API_KEY:
        return auth.credentials

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Invalid or missing API key",
        headers={"WWW-Authenticate": "Bearer"},
    )
