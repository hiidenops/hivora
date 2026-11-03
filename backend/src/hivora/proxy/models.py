"""Public domains served by the HTTPS proxy."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base


class ProxyRoute(Base):
    """A domain of the Internet for an app's web port. Not tied to the proxy app:
    reinstalling the proxy serves the same domains again."""

    __tablename__ = "proxy_route"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(253), unique=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
