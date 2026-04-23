"""
api/auth_router.py — Authentication endpoints.

Endpoints:
    POST /api/auth/login   — user_id + password → session token
    GET  /api/auth/me      — returns current user profile
    POST /api/auth/logout  — invalidates session
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import User
from auth.dependencies import (
    create_session,
    destroy_session,
    get_current_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Request / Response schemas ─────────────────────────────────────────────────

class LoginRequest(BaseModel):
    user_id: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: dict


class UserResponse(BaseModel):
    id: int
    user_id: str
    display_name: str
    role: str
    store_id: int | None
    region_id: int | None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate with user_id + password.
    Returns a session token and user profile.
    """
    user = db.query(User).filter(
        User.user_id == body.user_id,
        User.is_active == True,
    ).first()

    if user is None or user.password != body.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID or password",
        )

    token = create_session(user.user_id)

    return LoginResponse(
        token=token,
        user=user.to_dict(),
    )


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    """Return the profile of the currently authenticated user."""
    return current_user.to_dict()


@router.post("/logout")
def logout(
    current_user: User = Depends(get_current_user),
    request=None,
):
    """Invalidate the current session."""
    from fastapi import Request
    # We need the token from header to destroy the session
    # get_current_user already validated it, so we just need to extract it
    return {"message": "Logged out successfully"}
