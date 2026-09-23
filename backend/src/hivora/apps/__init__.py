"""Application lifecycle.

Create, edit, revisions, rollback, start/stop, remove, adopt, zone assignment.
"""

from hivora.apps.handlers import AppJobHandlers
from hivora.apps.models import Application, AppRevision, DesiredState, Origin, RevisionStatus
from hivora.apps.ports import PortConflict
from hivora.apps.service import (
    AppNotFoundError,
    AppService,
    DeployPlan,
    DeployRequest,
    PortConflictError,
    RemovalPlan,
    UnsupportedArchitectureError,
    slugify,
)

__all__ = [
    "AppJobHandlers",
    "AppNotFoundError",
    "AppRevision",
    "AppService",
    "Application",
    "DeployPlan",
    "DeployRequest",
    "DesiredState",
    "Origin",
    "PortConflict",
    "PortConflictError",
    "RemovalPlan",
    "RevisionStatus",
    "UnsupportedArchitectureError",
    "slugify",
]
