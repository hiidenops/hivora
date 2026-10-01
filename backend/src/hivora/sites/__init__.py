"""Static sites: nginx apps created and managed as websites."""

from hivora.sites.core import SITE_KIND, SiteNotFoundError
from hivora.sites.service import Site, SiteService

__all__ = ["SITE_KIND", "Site", "SiteNotFoundError", "SiteService"]
