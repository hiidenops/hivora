"""Checks on a hand-written compose file before Hivora applies it.

Docker's socket is root on the host: a compose file could mount `/`, the
socket, or run privileged. The resolved model (`docker compose config`) is
checked, so variables, anchors and short syntaxes cannot hide anything.
"""

from pathlib import Path
from typing import Any

ALLOWED_CAPS = {"NET_ADMIN"}  # as for templates: network tools (WireGuard)
ALLOWED_SYSCTLS = {"net.ipv4.ip_forward", "net.ipv4.conf.all.src_valid_mark"}
HOST_MODES = ("network_mode", "pid", "ipc", "uts", "userns_mode", "cgroup")


def _inside(path: str, roots: list[Path]) -> bool:
    resolved = Path(path).resolve()
    return any(resolved == r or r in resolved.parents for r in roots)


def problems(model: dict[str, Any], slug: str, roots: list[Path]) -> list[str]:
    """What forbids applying this compose file (empty: fine). ``roots``: allowed bind sources."""
    found = []
    if model.get("name") != slug:
        found.append(f"the project name must stay {slug!r}")
    services = model.get("services") or {}
    if not services:
        found.append("no service")
    for name, svc in services.items():
        where = f"service {name}"
        if svc.get("privileged"):
            found.append(f"{where}: privileged is not allowed")
        for key in HOST_MODES:
            value = str(svc.get(key) or "")
            if value == "host" or value.startswith("container:"):
                found.append(f"{where}: {key}: {value} is not allowed")
        if extra := set(svc.get("cap_add") or []) - ALLOWED_CAPS:
            found.append(f"{where}: capabilities {sorted(extra)} are not allowed")
        sysctls = svc.get("sysctls") or {}
        keys = (
            set(sysctls) if isinstance(sysctls, dict) else {str(s).split("=")[0] for s in sysctls}
        )
        if extra := keys - ALLOWED_SYSCTLS:
            found.append(f"{where}: sysctls {sorted(extra)} are not allowed")
        if svc.get("devices"):
            found.append(f"{where}: devices are not allowed")
        for opt in svc.get("security_opt") or []:
            if "unconfined" in str(opt) or "no-new-privileges:false" in str(opt):
                found.append(f"{where}: security_opt {opt} is not allowed")
        for v in svc.get("volumes") or []:
            v = v if isinstance(v, dict) else {"type": "bind", "source": str(v).split(":")[0]}
            if v.get("type") == "bind" and not _inside(str(v.get("source", "")), roots):
                found.append(f"{where}: {v.get('source')} is outside the app's folders")
        labels = svc.get("labels") or {}
        if isinstance(labels, dict) and labels.get("io.hivora.app") != slug:
            found.append(f"{where}: keep the label io.hivora.app: {slug}")
    for name, vol in (model.get("volumes") or {}).items():
        device = str(((vol or {}).get("driver_opts") or {}).get("device") or "")
        if device and not _inside(device, roots):
            found.append(f"volume {name}: device {device} is outside the app's folders")
    return found
