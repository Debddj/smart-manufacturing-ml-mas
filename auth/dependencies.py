"""
auth/dependencies.py — FastAPI auth dependencies.

Simple session-based authentication:
    - Login returns a UUID token
    - Token is stored in an in-memory dict mapping token → user_id
    - Protected routes read the token from Authorization header
"""

from __future__ import annotations

import uuid
from typing import Dict, Optional
from functools import wraps

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import User

# ── In-memory session store ───────────────────────────────────────────────────
# {token_string: user_id_string}
_sessions: Dict[str, str] = {}


def create_session(user_id: str) -> str:
    """Create a new session for a user and return the token."""
    token = str(uuid.uuid4())
    _sessions[token] = user_id
    return token


def destroy_session(token: str) -> bool:
    """Remove a session. Returns True if found, False otherwise."""
    return _sessions.pop(token, None) is not None


def get_user_id_from_token(token: str) -> Optional[str]:
    """Look up the user_id for a session token."""
    return _sessions.get(token)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency — extracts and validates the session token.

    Expects header: Authorization: Bearer <token>
    Returns the User ORM object.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header[7:]  # strip "Bearer "
    user_id = get_user_id_from_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
        )

    user = db.query(User).filter(User.user_id == user_id, User.is_active == True).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


def require_role(*allowed_roles: str):
    """
    FastAPI dependency factory — ensures the current user has one of the allowed roles.

    Usage:
        @router.get("/admin", dependencies=[Depends(require_role("regional_manager"))])
        def admin_view(...): ...
    """
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {', '.join(allowed_roles)}",
            )
        return current_user
    return role_checker


def require_store_access(store_id: int):
    """
    Check that the current user has access to the given store.
    Store managers and sales persons can only access their own store.
    Regional managers can access any store in their region.
    """
    def checker(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        if current_user.role == "regional_manager":
            # Regional managers can access stores in their region
            from db.models import Store
            store = db.query(Store).filter(Store.id == store_id).first()
            if store and store.region_id == current_user.region_id:
                return current_user
            raise HTTPException(status_code=403, detail="Store not in your region")

        if current_user.store_id != store_id:
            raise HTTPException(status_code=403, detail="Access denied to this store")

        return current_user
    return checker
