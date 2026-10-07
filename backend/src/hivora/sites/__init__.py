"""Static sites: the sites an nginx app hosts, each on its own port."""

from hivora.sites.core import SITE_KIND, SiteNotFoundError
from hivora.sites.service import SiteContent

__all__ = ["SITE_KIND", "SiteContent", "SiteNotFoundError"]
