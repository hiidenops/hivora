"""Imports every module's models so metadata is complete (migrations, tests).

Only migration tooling and tests import this: it is not a runtime dependency
of the db module on the others.
"""

import hivora.apps.models
import hivora.audit.models
import hivora.auth.models
import hivora.backups.models
import hivora.db.models
import hivora.hostfw.models
import hivora.jobs.models
import hivora.sites.models
import hivora.tasks.models
import hivora.templates.models
import hivora.topology.models
import hivora.vpn.models
import hivora.zones.models  # noqa: F401
