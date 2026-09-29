import hashlib
from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import API_KEY

bearer_scheme = HTTPBearer(auto_error=False)


def hash_token(token: str) -> str:
    """Hash raw reviewer token using SHA-256."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    auth: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> str:
    """Verify service request contains valid API Key via X-API-Key header or Bearer token (service/dev only)."""
    if x_api_key and x_api_key == API_KEY:
        return x_api_key

    if auth and auth.credentials == API_KEY:
        return auth.credentials

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Invalid or missing API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_reviewer(
    auth: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> dict:
    """Resolve Bearer token to an active reviewer record in the database."""
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing reviewer Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_h = hash_token(auth.credentials)
    from . import db

    rows = db.query("SELECT * FROM reviewers WHERE token_hash = ? AND active = 1", (token_h,))
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid reviewer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return dict(rows[0])


def require_reviewer(reviewer: dict = Depends(get_current_reviewer)) -> dict:
    """Ensure authenticated reviewer has the 'reviewer' role (viewers get 403 Forbidden)."""
    if reviewer.get("role") != "reviewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Reviewer role required for this action",
        )
    return reviewer


def create_reviewer(name: str, role: str, raw_token: str, active: int = 1) -> dict:
    """Helper to insert/replace a reviewer with a SHA-256 hashed token."""
    from . import db

    token_h = hash_token(raw_token)
    cur = db.execute(
        "INSERT OR REPLACE INTO reviewers (name, role, token_hash, active) VALUES (?, ?, ?, ?)",
        (name, role, token_h, active),
    )
    return {"id": cur.lastrowid, "name": name, "role": role, "active": active}
