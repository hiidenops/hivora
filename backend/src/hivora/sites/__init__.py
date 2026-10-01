"""Static sites: nginx apps created and managed as websites."""

from hivora.sites.service import SITE_KIND, Site, SiteNotFoundError, SiteService

__all__ = ["SITE_KIND", "Site", "SiteNotFoundError", "SiteService"]
