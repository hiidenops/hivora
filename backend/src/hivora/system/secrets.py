"""Secret global settings (third-party API keys), AES-GCM encrypted in `setting`."""

import base64
from enum import StrEnum

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.core.events import EventBus
from hivora.crypto.cipher import Purpose, Sealed, SecretBox
from hivora.db.models import Setting


class SecretSetting(StrEnum):
    CURSEFORGE_API_KEY = "curseforge_api_key"


def _row_key(name: SecretSetting) -> str:
    return f"secret:{name.value}"


class SecretSettings:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], box: SecretBox, bus: EventBus
    ) -> None:
        self.sessions = sessions
        self.box = box
        self.bus = bus

    async def get(self, name: SecretSetting) -> str | None:
        async with self.sessions() as session:
            row = await session.get(Setting, _row_key(name))
        if row is None:
            return None
        sealed = Sealed(
            base64.b64decode(row.value["nonce"]), base64.b64decode(row.value["ciphertext"])
        )
        return self.box.open(Purpose.SETTING, sealed, _row_key(name))

    async def is_set(self, name: SecretSetting) -> bool:
        async with self.sessions() as session:
            return await session.get(Setting, _row_key(name)) is not None

    async def set(self, name: SecretSetting, value: str | None) -> None:
        """Store (or clear, with None/empty) a secret setting. Its value is never logged."""
        async with self.sessions() as session, session.begin():
            await session.execute(delete(Setting).where(Setting.key == _row_key(name)))
            if value:
                sealed = self.box.seal(Purpose.SETTING, value, _row_key(name))
                session.add(Setting(key=_row_key(name), value={
                    "nonce": base64.b64encode(sealed.nonce).decode(),
                    "ciphertext": base64.b64encode(sealed.ciphertext).decode(),
                }))  # fmt: skip
        self.bus.publish("settings.secret_updated", target=name.value, cleared=not value)
