"""`python -m hivora`: the production entrypoint (the Docker image runs this).

HTTPS by default: a self-signed certificate is created in <data>/tls/ on first
start (the browser warns once; replace the two files with your own anytime).
One Uvicorn worker, as the whole design assumes a single process.

`python -m hivora backup-self`: archive the panel (database, master key, launch options)
in <data>/backups/_hivora/ and print the archive's path.
`python -m hivora bootstrap`: the initial admin with a random password (installer, before
the server starts); `python -m hivora reset-admin-password [user]`: a new random one;
`python -m hivora reset-totp [user]`: two-factor authentication off (lost phone).
Both print KEY=value lines.
"""

import ipaddress
import os
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from hivora.core.config import Settings
from hivora.core.errors import NotFoundError
from hivora.db.migrate import SchemaTooNewError
from hivora.system.bootstrap import bootstrap, reset_admin_password, reset_admin_totp
from hivora.system.panel_backup import backup_panel


def self_signed(tls_dir: Path, names: list[str]) -> tuple[Path, Path]:
    """(cert, key) in ``tls_dir``, created once; existing files are left alone."""
    cert, key = tls_dir / "cert.pem", tls_dir / "key.pem"
    if cert.is_file() and key.is_file():
        return cert, key
    tls_dir.mkdir(parents=True, exist_ok=True)
    private = ec.generate_private_key(ec.SECP256R1())
    alt: list[x509.GeneralName] = []
    for name in dict.fromkeys(n for n in names if n):
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            alt.append(x509.DNSName(name))
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Hivora")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(private.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private, hashes.SHA256())
    )  # fmt: skip
    fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(private.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))  # fmt: skip
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return cert, key


def command(settings: Settings, args: list[str]) -> None:
    """A one-off command instead of the server (exit status 1 and a message on failure)."""
    try:
        if args == ["backup-self"]:
            print(backup_panel(settings.data_dir))
            return
        if args == ["bootstrap"]:
            out = bootstrap(settings)
        elif args[0] == "reset-admin-password" and len(args) <= 2:
            out = reset_admin_password(settings, *args[1:])
        elif args[0] == "reset-totp" and len(args) <= 2:
            out = reset_admin_totp(settings, *args[1:])
        else:
            sys.exit(
                "usage: python -m hivora "
                "[backup-self | bootstrap | reset-admin-password [user] | reset-totp [user]]"
            )
    except (SchemaTooNewError, NotFoundError, FileNotFoundError) as error:
        sys.exit(f"error: {error}")
    print("\n".join(f"{key}={value}" for key, value in out.items()))


def main(args: list[str] | None = None) -> None:
    args = sys.argv[1:] if args is None else args
    settings = Settings()
    if args:
        command(settings, args)
        return
    options: dict[str, object] = {}
    if settings.tls:
        names = ["localhost", "127.0.0.1", socket.gethostname(), settings.host_lan_ip or "",
                 settings.host_public_ip or ""]  # fmt: skip
        cert, key = self_signed(settings.data_dir / "tls", names)
        options = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    uvicorn.run(
        "hivora.main:app", factory=True, host="0.0.0.0", port=settings.port,  # noqa: S104
        proxy_headers=True, forwarded_allow_ips="127.0.0.1", log_level="warning",
        **options,  # type: ignore[arg-type]
    )  # fmt: skip


if __name__ == "__main__":
    main()
