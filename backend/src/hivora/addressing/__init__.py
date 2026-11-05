"""Static addressing: the Hivora range, each zone's subnet, each app's own network and
every container's fixed address (intention, in SQLite); Docker applies it."""

from hivora.addressing.plan import Taken
from hivora.addressing.service import Addressing, AppAddressing, default_network

__all__ = ["Addressing", "AppAddressing", "Taken", "default_network"]
