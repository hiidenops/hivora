"""User administration routes (/api/v1/users), admin only."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.auth.api import SessionOut
from hivora.auth.models import Role, User
from hivora.web.deps import Admin, RuntimeDep

router = APIRouter(tags=["users"])


class UserOut(BaseModel):
    id: int
    username: str
    role: Role
    disabled: bool
    must_change_password: bool
    totp_enabled: bool
    created_at: datetime
    last_login_at: datetime | None


class UserCreateIn(BaseModel):
    username: str = Field(max_length=64)
    role: Role
    password: str = Field(max_length=1024, description="Temporary: changed at first login")


class UserUpdateIn(BaseModel):
    role: Role | None = None
    disabled: bool | None = None


class TemporaryPasswordIn(BaseModel):
    temporary: str = Field(max_length=1024)


def user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        username=u.username,
        role=u.role,
        disabled=u.disabled,
        must_change_password=u.must_change_password,
        totp_enabled=u.totp_enabled,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
    )


@router.get("")
async def list_users(_: Admin, rt: RuntimeDep) -> list[UserOut]:
    return [user_out(u) for u in await rt.auth.list_users()]


@router.post("", status_code=201)
async def create_user(body: UserCreateIn, _: Admin, rt: RuntimeDep) -> UserOut:
    return user_out(await rt.auth.create_user(body.username, body.role, body.password))


@router.patch("/{user_id}")
async def update_user(user_id: int, body: UserUpdateIn, _: Admin, rt: RuntimeDep) -> UserOut:
    return user_out(await rt.auth.update_user(user_id, role=body.role, disabled=body.disabled))


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: int, admin: Admin, rt: RuntimeDep) -> None:
    await rt.auth.delete_user(user_id, acting_user_id=admin.user_id)


@router.post("/{user_id}/password", status_code=204)
async def reset_password(user_id: int, body: TemporaryPasswordIn, _: Admin, rt: RuntimeDep) -> None:
    await rt.auth.reset_password(user_id, body.temporary)


@router.post("/{user_id}/totp/reset", status_code=204)
async def reset_totp(user_id: int, _: Admin, rt: RuntimeDep) -> None:
    await rt.auth.reset_totp(user_id)


@router.get("/{user_id}/sessions")
async def user_sessions(user_id: int, _: Admin, rt: RuntimeDep) -> list[SessionOut]:
    return [
        SessionOut(id=s.id, ip=s.ip, user_agent=s.user_agent, created_at=s.created_at,
                   last_seen_at=s.last_seen_at)
        for s in await rt.auth.list_sessions(user_id)
    ]  # fmt: skip


@router.delete("/{user_id}/sessions", status_code=204)
async def revoke_user_sessions(user_id: int, admin: Admin, rt: RuntimeDep) -> None:
    keep = admin.session_id if user_id == admin.user_id else None
    await rt.auth.revoke_sessions(user_id, keep=keep)
