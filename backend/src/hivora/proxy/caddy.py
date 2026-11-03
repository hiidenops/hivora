"""Caddy's side of the proxy: the sites file, its certificates and its log. Pure.

Caddy gets and renews each domain's certificate itself (automatic HTTPS): Hivora only
writes which domain goes to which container, then reads what Caddy stored and logged.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509

from hivora.core.errors import ValidationError

DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
LOCAL = (".local", ".lan", ".home.arpa", ".internal", ".localhost", ".test")


class DomainError(ValidationError):
    code = "proxy_bad_domain"


@dataclass(frozen=True, slots=True)
class Site:
    domain: str
    upstream: str  # container:port
    https: bool = False  # the app itself answers in HTTPS (a self-signed certificate)


@dataclass(frozen=True, slots=True)
class Certificate:
    expires_at: datetime
    issuer: str


def check_domain(domain: str) -> str:
    domain = domain.strip().lower().rstrip(".")
    if not DOMAIN.fullmatch(domain) or domain.endswith(LOCAL):
        raise DomainError("a domain of the Internet is needed (e.g. cloud.example.org)",
                          field="domain")  # fmt: skip
    return domain


def sites_file(sites: list[Site]) -> str:
    lines = ["# Written by Hivora: edits here are replaced on the next change."]
    for s in sites:
        lines += ["", f"{s.domain} {{"]
        if s.https:
            lines += [f"    reverse_proxy https://{s.upstream} {{",
                      "        transport http {", "            tls_insecure_skip_verify",
                      "        }", "    }"]  # fmt: skip
        else:
            lines.append(f"    reverse_proxy {s.upstream}")
        lines.append("}")
    return "\n".join(lines) + "\n"


def certificate(data: Path, domain: str) -> Certificate | None:
    """The certificate Caddy stored for ``domain`` (any issuer), the latest to expire."""
    found = []
    for path in data.glob(f"caddy/certificates/*/{domain}/{domain}.crt"):
        try:
            cert = x509.load_pem_x509_certificate(path.read_bytes())
        except (OSError, ValueError):
            continue
        cn = cert.issuer.get_attributes_for_oid(x509.NameOID.ORGANIZATION_NAME) or \
            cert.issuer.get_attributes_for_oid(x509.NameOID.COMMON_NAME)  # fmt: skip
        found.append(Certificate(cert.not_valid_after_utc, str(cn[0].value) if cn else ""))
    return max(found, key=lambda c: c.expires_at, default=None)


def last_errors(log: list[str]) -> dict[str, str]:
    """Domain -> Caddy's last error getting its certificate (cleared once obtained)."""
    out: dict[str, str] = {}
    for line in log:
        try:
            entry = json.loads(line[line.index("{") :])
        except ValueError:
            continue
        domain = entry.get("identifier")
        if not isinstance(domain, str):
            continue
        if entry.get("level") == "error":
            out[domain] = str(entry.get("error") or entry.get("msg") or "")[:400]
        elif entry.get("msg") == "certificate obtained successfully":
            out.pop(domain, None)
    return out


def status(cert: Certificate | None, error: str | None, now: datetime) -> str:
    if cert and cert.expires_at > now:
        return "valid"
    return "error" if error else "pending"


if __name__ == "__main__":
    assert check_domain(" Cloud.Example.ORG. ") == "cloud.example.org"
    for bad in ("mc.local", "nas.home.arpa", "localhost", "a b.fr", "x;y.fr", "exemple"):
        try:
            check_domain(bad)
            raise AssertionError(bad)
        except DomainError:
            pass
    text = sites_file([Site("a.fr", "a-server-1:80"), Site("b.fr", "b-server-1:8443", True)])
    assert "a.fr {\n    reverse_proxy a-server-1:80\n}" in text
    assert "reverse_proxy https://b-server-1:8443 {" in text and "tls_insecure_skip_verify" in text
    log = ['{"level":"error","logger":"tls.obtain","msg":"could not get certificate from issuer",'
           '"identifier":"a.fr","error":"HTTP 400 urn:ietf:params:acme:error:connection"}',
           '{"level":"error","identifier":"b.fr","error":"timeout"}',
           '{"level":"info","identifier":"b.fr","msg":"certificate obtained successfully"}',
           "not json"]  # fmt: skip
    assert last_errors(log) == {"a.fr": "HTTP 400 urn:ietf:params:acme:error:connection"}
    now = datetime(2026, 11, 3, tzinfo=UTC)
    assert status(None, None, now) == "pending" and status(None, "x", now) == "error"
    assert (
        status(Certificate(datetime(2027, 1, 1, tzinfo=UTC), "Let's Encrypt"), "x", now) == "valid"
    )
