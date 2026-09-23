"""Session and self-service routes (/api/v1/auth)."""

from datetime import datetime

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from hivora.auth.models import Role, User
from hivora.core.errors import NotFoundError
from hivora.web.deps import (
    SESSION_COOKIE,
    Principal,
    RuntimeDep,
    SessionPrincipal,
    Viewer,
    client_ip,
)

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)
    totp_code: str | None = Field(default=None, max_length=32)


class MeOut(BaseModel):
    id: int
    username: str
    role: Role
    must_change_password: bool
    totp_enabled: bool
    csrf_token: str


class PasswordIn(BaseModel):
    current: str = Field(max_length=1024)
    new: str = Field(max_length=1024)


class TotpEnrollOut(BaseModel):
    secret: str
    uri: str


class CodeIn(BaseModel):
    code: str = Field(max_length=32)


class PasswordConfirmIn(BaseModel):
    password: str = Field(max_length=1024)


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class SessionOut(BaseModel):
    id: int
    ip: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime
    current: bool = False


def me_out(user: User | Principal, csrf: str) -> MeOut:
    user_id = user.id if isinstance(user, User) else user.user_id
    return MeOut(
        id=user_id,
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
        totp_enabled=user.totp_enabled,
        csrf_token=csrf,
    )


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, rt: RuntimeDep) -> MeOut:
    result = await rt.auth.login(
        body.username,
        body.password,
        totp_code=body.totp_code,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        SESSION_COOKIE, result.token, httponly=True, samesite="strict", path="/",
        secure=not rt.settings.dev_insecure_cookies,
        max_age=rt.settings.session_max_days * 86400,
    )  # fmt: skip
    return me_out(result.user, result.session.csrf_token)


@router.post("/logout", status_code=204)
async def logout(principal: SessionPrincipal, response: Response, rt: RuntimeDep) -> None:
    await rt.auth.logout(principal.session_id)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(principal: SessionPrincipal) -> MeOut:
    return me_out(principal, principal.csrf_token)


@router.post("/password", status_code=204)
async def change_password(body: PasswordIn, principal: SessionPrincipal, rt: RuntimeDep) -> None:
    """Allowed before anything else: required when ``must_change_password``."""
    await rt.auth.change_password(
        principal.user_id, body.current, body.new, keep_session=principal.session_id
    )


@router.post("/totp/enroll")
async def totp_enroll(principal: Viewer, rt: RuntimeDep) -> TotpEnrollOut:
    enrollment = await rt.auth.totp_enroll(principal.user_id)
    return TotpEnrollOut(secret=enrollment.secret, uri=enrollment.uri)


@router.post("/totp/confirm")
async def totp_confirm(body: CodeIn, principal: Viewer, rt: RuntimeDep) -> RecoveryCodesOut:
    return RecoveryCodesOut(recovery_codes=await rt.auth.totp_confirm(principal.user_id, body.code))


@router.post("/totp/disable", status_code=204)
async def totp_disable(body: PasswordConfirmIn, principal: Viewer, rt: RuntimeDep) -> None:
    await rt.auth.totp_disable(principal.user_id, body.password)


@router.get("/sessions")
async def my_sessions(principal: Viewer, rt: RuntimeDep) -> list[SessionOut]:
    return [
        SessionOut(id=s.id, ip=s.ip, user_agent=s.user_agent, created_at=s.created_at,
                   last_seen_at=s.last_seen_at, current=s.id == principal.session_id)
        for s in await rt.auth.list_sessions(principal.user_id)
    ]  # fmt: skip


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_my_session(session_id: int, principal: Viewer, rt: RuntimeDep) -> None:
    if session_id not in {s.id for s in await rt.auth.list_sessions(principal.user_id)}:
        raise NotFoundError("session not found")
    await rt.auth.logout(session_id)
