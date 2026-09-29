"""Application routes (/api/v1/apps), assembled from one module per sub-domain.

The registration order below is the public route order: FastAPI matches routes in that
order, so fixed paths (/plan, /discover, /images/inspect, /custom) stay before /{app_id}.
Some modules have several routers to keep it; routes with an empty path are registered
here, since FastAPI refuses an empty path in an included router.
"""

from fastapi import APIRouter

from hivora.apps.api import adoption, compose_edit, deploy, lifecycle, queries, revisions
from hivora.apps.api.common import (  # re-exported: imported from here by pyapps and backups
    DeployOut as DeployOut,
)
from hivora.apps.api.common import (
    JobRef as JobRef,
)
from hivora.apps.api.common import (
    app_out as app_out,
)
from hivora.apps.api.common import (
    job_ref as job_ref,
)

router = APIRouter(tags=["apps"])


router.get("")(queries.list_apps)  # empty path: cannot sit in an included router


router.include_router(deploy.plan_router)


router.include_router(adoption.router)


router.include_router(deploy.router)
router.post("", status_code=202)(deploy.deploy)  # empty path: cannot sit in an included router


router.include_router(queries.router)


router.include_router(lifecycle.router)


router.include_router(revisions.zone_router)


router.include_router(lifecycle.removal_router)


router.include_router(revisions.router)


router.include_router(compose_edit.router)
