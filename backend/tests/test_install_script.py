"""deploy/install.sh, run with fake docker, ss, ip, id and timedatectl first in PATH: they
log their calls and answer as told; nothing touches the machine."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "deploy" / "install.sh"
PASSWORD = "abcde-fghjk-mnpqr-stuvw"
RULE = "─" * 46  # under a screen's title


def flat(out: str) -> str:
    """The output with its alignment (spaces, line breaks) folded: the words, in order."""
    return " ".join(out.split())

FAKE_DOCKER = r"""#!/bin/sh
echo "docker $*" >> "$FAKE_LOG"
if [ "$1 $2" = "version --format" ]; then echo "${FAKE_DOCKER_VERSION:-27.3.1}"; exit 0; fi
case "$1" in
  version) if [ -n "${FAKE_PODMAN:-}" ]; then echo "Client: Podman Engine"
    else echo "Server: Docker Engine"; fi ;;
  info) if [ -n "${FAKE_ROOTLESS:-}" ]; then echo "[name=seccomp name=rootless]"
    else echo "[name=seccomp]"; fi ;;
  container) [ -f "$FAKE_STATE/running" ]; exit ;;
  inspect) case "$*" in
      *Running*) if [ -f "$FAKE_STATE/running" ]; then echo true; else echo false; fi ;;
      *Health*) echo healthy ;;
    esac ;;
  port) echo "0.0.0.0:${FAKE_HIVORA_PORT:-8443}" ;;
  pull|image) ;;
  network) case "$2" in
      inspect) [ -f "$FAKE_STATE/network" ] || exit 1; cat "$FAKE_STATE/network" ;;
      create) printf '%s ' "$(echo "$*" | sed 's/.*--subnet \([^ ]*\).*/\1/')" \
                > "$FAKE_STATE/network" ;;
    esac ;;
  ps) case "$*" in *"publish=${FAKE_ADMIN_VPN_PORT:-51820}/udp"*)
      [ -z "${FAKE_ADMIN_VPN_RUNNING:-}" ] || echo 5678efab ;; esac ;;
  exec) case "$*" in
      *backup-self) echo "/data/backups/_hivora/panel-x.tar.gz" ;;
      *rescue-admin) touch "$FAKE_STATE/rescue"; echo ADMIN_VPN=rescue_requested ;;
      *admin-vpn) echo "ADMIN_CONF=$FAKE_DATA/admin.conf"
        echo "[QR $(head -n 1 "$FAKE_DATA/admin.conf")]" ;;
    esac ;;
  restart) [ ! -f "$FAKE_STATE/rescue" ] \
      || sed -i 's/^PrivateKey = .*/PrivateKey = new/' "$FAKE_DATA/admin.conf" ;;
  rm) rm -f "$FAKE_STATE/running"; echo hivora ;;
  run) case "$*" in
      *"python -m hivora bootstrap") printf '%s\n' "$FAKE_BOOTSTRAP" ;;
      *" -d "*) touch "$FAKE_STATE/running"
        # As the server: admin.conf made once, its Endpoint following install.env (D17).
        conf="$FAKE_DATA/admin.conf"
        case "$*" in *HIVORA_ACCESS=vpn*) [ -n "${FAKE_NO_ADMIN_CONF:-}" ] || {
          old="$(sed -n 's/^Endpoint = \(.*\):.*/\1/p' "$conf" 2>/dev/null)"
          host="$(echo "$*" | sed -n 's/.*HIVORA_ADMIN_VPN_HOST=\([^ ]*\).*/\1/p')"
          port="$(echo "$*" | sed -n 's/.*HIVORA_ADMIN_VPN_PORT=\([^ ]*\).*/\1/p')"
          key="$(sed -n 's/^PrivateKey = //p' "$conf" 2>/dev/null)"
          printf 'PrivateKey = %s\nEndpoint = %s:%s\n' "${key:-first}" \
            "${host:-${old:-203.0.113.7}}" "$port" > "$conf"; } ;;
        esac
        echo 0123abcd ;;
      *) exit 1 ;;
    esac ;;
  *) echo "unexpected: docker $*" >&2; exit 1 ;;
esac
"""
FAKE_SS = r"""#!/bin/sh
case "$1" in
  -ltnH) [ -z "${FAKE_PORT_BUSY:-}" ] || echo "LISTEN 0 4096 0.0.0.0:8443 x" ;;
  -lunH) [ -z "${FAKE_UDP_BUSY:-}" ] || echo "UNCONN 0 0 0.0.0.0:51820 x" ;;
esac
"""
FAKE_IP = r"""#!/bin/sh
if [ "$3" = get ]; then
  echo "1.1.1.1 via 192.168.1.1 dev eth0 src ${FAKE_LAN:-192.168.1.10} uid 0"
else
  echo "default via 192.168.1.1 dev eth0"; printf "%b" "${FAKE_ROUTES:-}"
fi
"""
FAKES = {
    "docker": FAKE_DOCKER,
    "ss": FAKE_SS,
    "ip": FAKE_IP,
    "curl": '#!/bin/sh\n[ -n "${FAKE_PUBLIC_IP:-}" ] || exit 7\necho "$FAKE_PUBLIC_IP"\n',
    "getent": '#!/bin/sh\n[ -n "${FAKE_RESOLVES:-}" ] || exit 2\necho "$FAKE_RESOLVES"\n',
    "id": '#!/bin/sh\nif [ "$1" = "-u" ]; then echo 0; else exec /usr/bin/id "$@"; fi\n',
    "timedatectl": "#!/bin/sh\necho Europe/Paris\n",
}


class Machine:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin, self.state = root / "bin", root / "state"
        self.data, self.srv = root / "data", root / "srv"
        for d in (self.bin, self.state):
            d.mkdir()
        for name, body in FAKES.items():
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.os_release = root / "os-release"
        self.distro("debian", "12")
        self.log = root / "calls.log"
        self.bootstrap = f"ADMIN=created\nADMIN_USER=admin\nADMIN_PASSWORD={PASSWORD}"

    def distro(self, distro: str, version: str) -> None:
        self.os_release.write_text(f'ID={distro}\nVERSION_ID="{version}"\n')

    def install(self, *args: str, script: Path = SCRIPT, env: dict[str, str] | None = None,
                answers: str | None = None) -> subprocess.CompletedProcess[str]:  # fmt: skip
        """``answers``: what the user types, one line per question (the terminal)."""
        self.log.unlink(missing_ok=True)
        if answers is not None:
            (self.root / "tty").write_text(answers)
            env = {"HIVORA_TTY": str(self.root / "tty"), **(env or {})}
        full = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.root),
                "FAKE_LOG": str(self.log), "FAKE_STATE": str(self.state),
                "FAKE_DATA": str(self.data), "HIVORA_VPN_TIMEOUT": "4",
                "FAKE_BOOTSTRAP": self.bootstrap, "HIVORA_OS_RELEASE": str(self.os_release),
                "HIVORA_HEALTH_TIMEOUT": "4", **(env or {})}  # fmt: skip
        cmd = ["/bin/sh", str(script), "--data", str(self.data), "--srv", str(self.srv), *args]
        return subprocess.run(cmd, env=full, capture_output=True, text=True, timeout=60,  # noqa: S603
                              check=False, start_new_session=True)  # fmt: skip

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def changes(self) -> list[str]:
        """The calls that change something (pull, run, rm, exec, restart, network create)."""
        return [c for c in self.calls() if c.split()[1] in ("pull", "run", "rm", "restart")
                or (c.startswith(("docker network create", "docker exec"))
                    and "admin-vpn" not in c)]  # fmt: skip

    def env(self) -> dict[str, str]:
        lines = (self.data / "install.env").read_text().splitlines()
        return dict(line.split("=", 1) for line in lines if not line.startswith("#"))


@pytest.fixture
def machine(tmp_path: Path) -> Machine:
    return Machine(tmp_path)


def test_a_fresh_install_bootstraps_before_the_server(machine: Machine) -> None:
    done = machine.install("--yes", "--version", "v1.2.3")
    assert done.returncode == 0, done.stderr
    pull, boot, network, start = machine.changes()
    assert pull == "docker pull ghcr.io/hiidenops/hivora:v1.2.3"
    assert "--rm" in boot and boot.endswith("hivora:v1.2.3 python -m hivora bootstrap")
    assert "docker.sock" not in boot  # the bootstrap needs no Docker
    assert network == ("docker network create --driver bridge --subnet 10.254.254.0/24 "
                       "--ip-range 10.254.254.0/25 --label io.hivora.zone-network=1 "
                       "hivora-zone-administration")  # fmt: skip
    # vpn+lan by default: the LAN port and the admin network at the panel's fixed address
    assert "-p 192.168.1.10:8443:8443" in start and "HIVORA_ACCESS=vpn+lan" in start
    assert "--network hivora-zone-administration --ip 10.254.254.254" in start
    assert "HIVORA_ADMIN_VPN_PORT=51820" in start and "ADMIN_VPN_HOST" not in start
    assert f"-v {machine.data}:{machine.data}" in start
    assert f"HIVORA IS READY {RULE} URL: https://192.168.1.10:8443" in flat(done.stdout)
    assert f"Password: {PASSWORD}" in flat(done.stdout)
    assert machine.env()["HIVORA_VERSION"] == '"v1.2.3"'
    assert machine.env()["HIVORA_TIMEZONE"] == '"Europe/Paris"'
    assert (machine.data / "install.env").stat().st_mode & 0o777 == 0o600


def test_a_rerun_keeps_the_options_and_backs_up_first(machine: Machine) -> None:
    assert machine.install("--yes", "--version", "v1.2.3", "--port", "9443").returncode == 0
    machine.bootstrap = "ADMIN=kept"
    done = machine.install("--yes", env={"FAKE_PORT_BUSY": "1", "FAKE_HIVORA_PORT": "9443"})
    assert done.returncode == 0, done.stderr
    changes = machine.changes()
    assert changes[0] == "docker pull ghcr.io/hiidenops/hivora:v1.2.3"  # version from install.env
    backup, remove, boot, start = changes[1:]
    assert backup == "docker exec hivora python -m hivora backup-self"
    assert remove == "docker rm -f hivora" and "bootstrap" in boot
    assert "-p 192.168.1.10:9443:8443" in start  # the port chosen the first time
    assert PASSWORD not in done.stdout and "unchanged (forgotten:" in done.stdout
    assert "Access: Local network + VPN (unchanged; to change it: --reconfigure)" in done.stdout


def test_an_update_installs_the_new_version_with_the_same_options(machine: Machine) -> None:
    assert machine.install("--yes", "--version", "v1.2.3", "--port", "9443").returncode == 0
    machine.bootstrap = "ADMIN=kept"
    done = machine.install("--yes", "--version", "v1.3.0")
    assert done.returncode == 0, done.stderr
    assert machine.changes()[0] == "docker pull ghcr.io/hiidenops/hivora:v1.3.0"
    assert machine.env()["HIVORA_VERSION"] == '"v1.3.0"'
    assert machine.env()["HIVORA_PORT"] == '"9443"'


def test_a_released_script_installs_its_own_version(machine: Machine, tmp_path: Path) -> None:
    released = tmp_path / "install.sh"
    released.write_text(
        SCRIPT.read_text().replace('SCRIPT_VERSION=""', 'SCRIPT_VERSION="v2.0.0"', 1)
    )
    assert machine.install("--yes", script=released).returncode == 0
    assert machine.changes()[0] == "docker pull ghcr.io/hiidenops/hivora:v2.0.0"
    done = machine.install("--yes")  # the repository's script, no version anywhere but install.env
    assert done.returncode == 0 and machine.changes()[0].endswith(":v2.0.0")


def test_a_busy_port_is_refused_before_anything_changes(machine: Machine) -> None:
    done = machine.install("--yes", "--version", "v1.2.3", env={"FAKE_PORT_BUSY": "1"})
    assert done.returncode == 1 and "port 8443 is already in use" in done.stderr
    assert machine.changes() == []


def test_unsupported_systems(machine: Machine) -> None:
    machine.distro("fedora", "40")
    done = machine.install("--version", "v1.2.3")  # no --yes, no terminal: not confirmed
    assert done.returncode == 1 and "not officially supported" in done.stderr
    assert machine.changes() == []
    machine.distro("debian", "11")
    done = machine.install("--yes", "--version", "v1.2.3")  # --yes: a warning, then on
    assert done.returncode == 0 and "not officially supported" in done.stderr
    machine.distro("ubuntu", "22.04")
    assert "not officially" not in machine.install("--yes", "--version", "v1.2.3").stderr
    for env, message in (({"FAKE_ROOTLESS": "1"}, "rootless"), ({"FAKE_PODMAN": "1"}, "Podman"),
                         ({"FAKE_DOCKER_VERSION": "23.0.6"}, "Docker Engine 24")):  # fmt: skip
        (machine.state / "running").unlink(missing_ok=True)
        done = machine.install("--yes", "--version", "v1.2.3", env=env)
        assert done.returncode == 1 and message in done.stderr
        assert machine.changes() == []


def test_a_dry_run_changes_nothing(machine: Machine) -> None:
    done = machine.install("--yes", "--dry-run", "--version", "v1.2.3")
    assert done.returncode == 0, done.stderr
    assert machine.changes() == []
    assert "+ docker pull ghcr.io/hiidenops/hivora:v1.2.3" in done.stderr
    assert "python -m hivora bootstrap" in done.stderr and "Dry run" in done.stdout
    assert not machine.data.exists()


def test_a_malicious_install_env_is_never_executed(machine: Machine) -> None:
    machine.data.mkdir()
    pwned = machine.root / "pwned"
    for line in (f'HIVORA_PORT="$(touch {pwned})"', f'HIVORA_IMAGE="x;touch {pwned}"',
                 f'HIVORA_LAN_IP="`touch {pwned}`"',
                 f'HIVORA_PUID="1000; touch {pwned}"'):  # fmt: skip
        (machine.data / "install.env").write_text(f"touch {pwned}\n{line}\n")
        done = machine.install("--yes", "--version", "v1.2.3")
        assert done.returncode == 1 and "invalid" in done.stderr, line
        assert not pwned.exists() and machine.changes() == []


def test_a_truncated_download_runs_nothing(machine: Machine, tmp_path: Path) -> None:
    text = SCRIPT.read_text()
    for cut in (len(text) // 3, len(text) // 2, text.rindex('main "$@"')):
        partial = tmp_path / "partial.sh"
        partial.write_text(text[:cut])
        machine.install("--yes", "--version", "v1.2.3", script=partial)
        assert machine.calls() == [] and not machine.data.exists(), cut


def test_access_modes(machine: Machine) -> None:
    done = machine.install("--yes", "--version", "v1.2.3", "--access", "lan")
    assert done.returncode == 0, done.stderr
    start = machine.changes()[-1]
    assert "-p 192.168.1.10:8443:8443" in start and "HIVORA_ACCESS=lan" in start
    assert "--network" not in start and "admin VPN" not in done.stdout
    done = machine.install("--yes", "--version", "v1.2.3", "--access", "public")
    assert done.returncode == 1 and "--i-understand" in done.stderr
    done = machine.install("--yes", "--version", "v1.2.3", "--access", "public", "--i-understand")
    assert done.returncode == 0, done.stderr
    assert (
        "-p 0.0.0.0:8443:8443" in machine.changes()[-1]
        and "HIVORA_ACCESS=public" in machine.changes()[-1]
    )
    assert machine.env()["HIVORA_ACCESS"] == '"public"'
    done = machine.install("--yes", "--access", "unknown")
    assert done.returncode == 1 and "invalid --access" in done.stderr


def test_a_repository_script_needs_a_version(machine: Machine) -> None:
    done = machine.install("--yes")
    assert done.returncode == 1 and "--version" in done.stderr
    assert machine.changes() == []


def test_a_failed_bootstrap_says_how_to_go_back(machine: Machine) -> None:
    assert machine.install("--yes", "--version", "v1.2.3").returncode == 0
    assert (machine.state / "running").exists()
    machine.bootstrap = ""
    (machine.bin / "docker").write_text(FAKE_DOCKER.replace(
        "printf '%s\\n' \"$FAKE_BOOTSTRAP\" ;;", "exit 1 ;;"))  # fmt: skip
    done = machine.install("--yes", "--version", "v1.3.0")
    assert done.returncode == 1 and "could not be prepared" in done.stderr
    assert "tar -xzf /data/backups/_hivora/panel-x.tar.gz" in done.stderr
    # the killed panel's write-ahead log removed first: else it corrupts the restored base
    wal = f"rm -f {machine.data}/hivora.db-wal {machine.data}/hivora.db-shm; tar -xzf"
    assert wal in done.stderr
    assert "--version v1.2.3" in done.stderr
    assert os.path.exists(machine.data / "install.env")
    assert machine.env()["HIVORA_VERSION"] == '"v1.2.3"'  # untouched until success


def test_admin_vpn_only_publishes_no_panel_port(machine: Machine) -> None:
    done = machine.install("--yes", "--version", "v1.2.3", "--access", "vpn",
                           "--vpn-host", "vpn.example.org", "--vpn-port", "51830")  # fmt: skip
    assert done.returncode == 0, done.stderr
    start = machine.changes()[-1]
    assert " -p " not in start and "HIVORA_ACCESS=vpn " in start
    assert "--network hivora-zone-administration --ip 10.254.254.254" in start
    assert "HIVORA_ADMIN_VPN_PORT=51830" in start
    assert "HIVORA_ADMIN_VPN_HOST=vpn.example.org" in start
    assert "URL: https://10.254.254.254:8443" in flat(done.stdout)  # the only way in
    assert "[QR PrivateKey = first]" in done.stdout and "2. Open UDP port 51830" in done.stdout
    assert done.stdout.index("HIVORA IS READY") < done.stdout.index("[QR")  # the QR code last
    env = machine.env()
    assert env["HIVORA_VPN_HOST"] == '"vpn.example.org"' and env["HIVORA_VPN_PORT"] == '"51830"'
    machine.bootstrap = "ADMIN=kept"
    again = machine.install("--yes", env={"FAKE_UDP_BUSY": "1", "FAKE_ADMIN_VPN_RUNNING": "1",
                                          "FAKE_ADMIN_VPN_PORT": "51830"})  # fmt: skip
    assert again.returncode == 0, again.stderr  # the port is the admin VPN's own
    assert not any(c.startswith("docker network create") for c in machine.changes())
    assert "HIVORA_ADMIN_VPN_PORT=51830" in machine.changes()[-1]  # kept from install.env
    assert "[QR PrivateKey = first]" in again.stdout  # VPN only: always the way in


def test_an_existing_install_keeps_its_mode(machine: Machine) -> None:
    assert machine.install("--yes", "--version", "v1.2.3", "--access", "lan").returncode == 0
    machine.bootstrap = "ADMIN=kept"
    done = machine.install("--yes", env={"FAKE_PORT_BUSY": "1"})
    assert done.returncode == 0, done.stderr
    assert "HIVORA_ACCESS=lan" in machine.changes()[-1]
    (machine.data / "install.env").unlink()  # installed before install.env existed
    done = machine.install("--yes", "--version", "v1.2.4", env={"FAKE_PORT_BUSY": "1"})
    assert done.returncode == 0 and "HIVORA_ACCESS=lan" in machine.changes()[-1]


@pytest.mark.parametrize(("env", "message"), [
    ({"FAKE_UDP_BUSY": "1"}, "UDP port 51820 is already in use"),
    ({"FAKE_LAN": "10.254.254.20"}, "overlaps 10.254.254.0/24"),
    ({"FAKE_ROUTES": "10.254.253.0/24 dev wg0 scope link\\n"}, "overlaps 10.254.253.0/24"),
])  # fmt: skip
def test_admin_vpn_checks_before_anything_changes(machine: Machine, env: dict[str, str],
                                                  message: str) -> None:  # fmt: skip
    done = machine.install("--yes", "--version", "v1.2.3", env=env)
    assert done.returncode == 1 and message in done.stderr, done.stderr
    assert machine.changes() == []


def test_an_admin_network_with_other_addresses_is_refused(machine: Machine) -> None:
    (machine.state / "network").write_text("172.23.0.0/16 ")  # made by Docker, not here
    done = machine.install("--yes", "--version", "v1.2.3")
    assert done.returncode == 1 and "another address range (172.23.0.0/16" in done.stderr
    assert machine.changes() == []
    (machine.state / "network").write_text("10.254.254.0/24 ")  # as this script makes it
    route = {"FAKE_ROUTES": "10.254.254.0/24 dev br-1 proto kernel scope link\\n"}  # its own
    done = machine.install("--yes", "--version", "v1.2.3", env=route)
    assert done.returncode == 0, done.stderr
    assert not any(c.startswith("docker network create") for c in machine.changes())


def test_vpn_and_lan_never_waits_for_the_vpn(machine: Machine) -> None:
    done = machine.install("--yes", "--version", "v1.2.3", env={"FAKE_NO_ADMIN_CONF": "1"})
    assert done.returncode == 0, done.stderr
    assert "being set up" in done.stdout and "[QR" not in done.stdout
    assert "Setting up the admin VPN" not in done.stdout  # no wait, no QR code (D14)
    assert "python -m hivora admin-vpn" in done.stdout


def test_an_admin_vpn_not_ready_in_time_is_a_warning(machine: Machine) -> None:
    done = machine.install("--yes", "--version", "v1.2.3", "--access", "vpn",
                           env={"FAKE_NO_ADMIN_CONF": "1"})  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert "admin VPN is not ready yet" in done.stderr and "admin-vpn" in done.stderr
    assert machine.env()["HIVORA_ACCESS"] == '"vpn"'  # installed all the same


def test_rescue_admin(machine: Machine) -> None:
    done = machine.install("--yes", "--rescue-admin")
    assert done.returncode == 1 and "not running" in done.stderr and machine.changes() == []
    assert machine.install("--yes", "--version", "v1.2.3").returncode == 0
    dry = machine.install("--yes", "--rescue-admin", "--dry-run")
    assert dry.returncode == 0 and machine.changes() == []
    assert "+ docker exec hivora python -m hivora rescue-admin" in dry.stderr
    done = machine.install("--yes", "--rescue-admin")
    assert done.returncode == 0, done.stderr
    assert machine.changes() == [
        "docker exec hivora python -m hivora rescue-admin",
        "docker restart hivora",
    ]  # nothing reinstalled
    assert "[QR PrivateKey = new]" in done.stdout


def test_a_dry_run_shows_the_admin_network(machine: Machine) -> None:
    done = machine.install("--yes", "--dry-run", "--version", "v1.2.3")
    assert done.returncode == 0 and machine.changes() == []
    assert "+ docker network create --driver bridge --subnet 10.254.254.0/24" in done.stderr


def test_the_addressing_is_the_servers(machine: Machine) -> None:
    from hivora.vpn import admin

    text = SCRIPT.read_text()
    for name in ("ADMIN_ZONE_SUBNET", "ADMIN_ZONE_RANGE", "PANEL_IP", "ADMIN_VPN_SUBNET"):
        assert f'\n{name}="{getattr(admin, name)}"\n' in text, name
    assert f'ADMIN_NETWORK="hivora-zone-{admin.ADMIN_ZONE}"' in text


# --- M12-5c: language, access menu, public address, VPS, final screen, --reconfigure ------
DETECTED = {"FAKE_PUBLIC_IP": "82.64.12.34"}


def fresh(machine: Machine, name: str) -> Machine:
    """Another machine, next to this one."""
    (machine.root / name).mkdir()
    return Machine(machine.root / name)


def messages(table: str) -> dict[str, str]:
    """``key) m 'format' ;;`` lines of msg_en or msg_fr."""
    import re

    body = SCRIPT.read_text().split(f"{table}() {{\n", 1)[1].split("\n}\n", 1)[0]
    found = re.findall(r"^    ([a-z0-9_]+)\) m (['\"])(.*)\2 ;;$", body, re.M)
    assert len(found) == body.count(" ;;"), f"{table}: a message not on one line"
    return {key: text for key, _, text in found}


def test_every_message_exists_in_both_languages() -> None:
    import re

    en, fr = messages("msg_en"), messages("msg_fr")
    assert en.keys() == fr.keys() and len(en) > 100
    for key in en:
        assert en[key].count("%s") == fr[key].count("%s"), key
        assert "%" not in en[key].replace("%s", "").replace("%-", ""), key
    code = re.sub(r"(^|\s)#.*$", "", SCRIPT.read_text(), flags=re.M)  # not the comments
    used = set(re.findall(r"\b(?:die|say|warn|line|t|ask|reply) ([a-z][a-z0-9_]+)\b", code))
    assert used <= en.keys() and len(used) > 100, used - en.keys()
    assert en.keys() - used == {"addr_current", "addr_detected"}  # chosen by a variable


def test_a_french_install_on_a_vm(machine: Machine) -> None:
    # Français; mode by default (local network + VPN); detected address right; continue.
    done = machine.install("--version", "v1.2.3", answers="1\n\n\n\n",
                           env={**DETECTED, "FAKE_NO_ADMIN_CONF": "1"})  # fmt: skip
    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert "Langue / Language" in out and "Comment accéderez-vous au panel ?" in out
    assert "Cette machine : 192.168.1.10 (réseau privé)" in out and "Votre choix [2]" in out
    assert "Adresse publique détectée pour le VPN :\n    82.64.12.34" in out
    assert "Hivora v1.2.3 va être installé :" in out
    assert f"HIVORA EST PRÊT {RULE} URL : https://192.168.1.10:8443" in flat(out)
    assert f"Mot de passe : {PASSWORD}" in flat(out)
    vpn_line = "VPN d\u2019administration : en préparation"  # French apostrophe
    assert out.index("HIVORA EST PRÊT") < out.index(vpn_line)
    assert "[QR" not in out and "python -m hivora admin-vpn" in out  # no QR code in vpn+lan
    assert "HIVORA_ADMIN_VPN_HOST=82.64.12.34" in machine.changes()[-1]
    env = machine.env()
    assert env["HIVORA_LANG"] == '"fr"' and env["HIVORA_ACCESS"] == '"vpn+lan"'
    assert env["HIVORA_VPN_HOST"] == '"82.64.12.34"'


def test_an_english_vpn_only_install_with_a_domain_name(machine: Machine) -> None:
    # English; only through the VPN (typed "vpn"); the detected address is not the one:
    # a domain name that resolves to it; continue.
    resolves = {**DETECTED, "FAKE_RESOLVES": "82.64.12.34 home.example.org"}
    answers = "2\n3\nvpn\nn\nhome.example.org\n\n"
    done = machine.install("--version", "v1.2.3", answers=answers, env=resolves)
    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert "How will you reach the panel?" in out and "Type vpn to confirm" in out
    assert "IP address or domain name for the VPN" in out and "does not resolve" not in out
    assert "URL: https://10.254.254.254:8443" in flat(out)
    assert "VPN access, step by step:" in out and "[QR PrivateKey = first]" in out
    assert out.index("HIVORA IS READY") < out.index("step by step") < out.index("[QR")
    start = machine.changes()[-1]
    assert "HIVORA_ACCESS=vpn " in start and " -p " not in start
    assert "HIVORA_ADMIN_VPN_HOST=home.example.org" in start
    assert machine.env()["HIVORA_LANG"] == '"en"'


def test_wrong_answers_are_asked_again(machine: Machine) -> None:
    # language 9 then 2; menu "x" then 1 (local network only); continue.
    done = machine.install("--version", "v1.2.3", answers="9\n2\nx\n1\n\n")
    assert done.returncode == 0, done.stderr
    assert "Invalid choice: type 1, 2, 3 or 4." in done.stdout
    assert "HIVORA_ACCESS=lan" in machine.changes()[-1]
    assert "Remote access later: run the installer again with --reconfigure" in done.stdout
    assert "Public address" not in done.stdout  # no VPN: no address asked
    # A wrong confirmation word goes back to the menu: "public" mistyped, then lan.
    machine2 = fresh(machine, "second")
    done = machine2.install("--version", "v1.2.3", answers="2\n4\npubliq\n1\n\n")
    assert done.returncode == 0 and "HIVORA_ACCESS=lan" in machine2.changes()[-1]


def test_the_public_address_typed_by_hand(machine: Machine) -> None:
    # Not detected: an invalid entry, then an IP. Then a second install: a name that does not
    # resolve, not kept, then the detected IP typed.
    done = machine.install("--version", "v1.2.3", answers="2\n2\nbad host!\n203.0.113.9\n\n")
    assert done.returncode == 0, done.stderr
    assert "Public address not detected" in done.stdout
    assert '"bad host!" is neither a valid IP address nor a valid domain name.' in done.stdout
    assert "HIVORA_ADMIN_VPN_HOST=203.0.113.9" in machine.changes()[-1]
    other = fresh(machine, "second")
    done = other.install("--version", "v1.2.3", env=DETECTED,
                         answers="2\n2\nn\nnowhere.example\nn\n82.64.12.34\n\n")  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert "nowhere.example does not resolve (or not to 82.64.12.34)" in done.stdout
    assert "HIVORA_ADMIN_VPN_HOST=82.64.12.34" in other.changes()[-1]


def test_a_machine_with_a_public_ip_only(machine: Machine) -> None:
    vps = {"FAKE_LAN": "203.0.113.7", **DETECTED}
    # The menu: 1 and 2 unavailable, 3 by default.
    done = machine.install("--version", "v1.2.3", answers="2\n1\n\nvpn\n\n\n", env=vps)
    assert done.returncode == 0, done.stderr
    assert "203.0.113.7 (PUBLIC address" in done.stdout and "Your choice [3]" in done.stdout
    assert "This choice is not available on this machine." in done.stdout
    assert "HIVORA_ACCESS=vpn " in machine.changes()[-1]
    # Without questions: a local network mode is refused, explained; --bind allows it.
    other = fresh(machine, "second")
    for mode in ("lan", "vpn+lan"):
        done = other.install("--yes", "--version", "v1.2.3", "--access", mode, env=vps)
        assert done.returncode == 1 and other.changes() == []
        assert "only has a public address (203.0.113.7): no local network" in done.stderr
        assert "without mandatory two-factor authentication" in done.stderr
    done = other.install("--yes", "--version", "v1.2.3", "--access", "lan",
                         "--bind", "203.0.113.7", env=vps)  # fmt: skip
    assert done.returncode == 0 and "-p 203.0.113.7:8443:8443" in other.changes()[-1]
    third = fresh(machine, "third")
    done = third.install("--yes", "--version", "v1.2.3", env=vps)  # default there: VPN only
    assert done.returncode == 0 and "HIVORA_ACCESS=vpn " in third.changes()[-1]


def test_no_question_without_a_terminal_or_with_yes(machine: Machine) -> None:
    done = machine.install("--yes", "--version", "v1.2.3", answers="1\n4\npublic\n")
    assert done.returncode == 0, done.stderr
    assert "Langue" not in done.stdout and "How will you reach" not in done.stdout
    assert "HIVORA IS READY" in done.stdout  # English without --lang
    assert "HIVORA_ACCESS=vpn+lan" in machine.changes()[-1]
    other = fresh(machine, "second")
    done = other.install("--yes", "--lang", "fr", "--version", "v1.2.3")
    assert done.returncode == 0 and "HIVORA EST PRÊT" in done.stdout
    assert other.env()["HIVORA_LANG"] == '"fr"'
    assert machine.install("--yes", "--lang", "de").returncode == 1


def test_a_rerun_asks_nothing_and_keeps_the_language(machine: Machine) -> None:
    assert machine.install("--version", "v1.2.3", answers="1\n1\n\n").returncode == 0
    machine.bootstrap = "ADMIN=kept"
    done = machine.install("--yes", env={"FAKE_PORT_BUSY": "1"}, answers="2\n")
    assert done.returncode == 0, done.stderr
    unchanged = "Accès : Réseau local uniquement (inchangé ; pour le changer : --reconfigure)"
    assert unchanged in done.stdout
    assert "Mot de passe : inchangé (oublié :" in flat(done.stdout)
    # In a terminal, without --yes: only "Continue?" (one answer), never the menu again.
    done = machine.install(env={"FAKE_PORT_BUSY": "1"}, answers="\n")
    assert done.returncode == 0, done.stderr
    assert "Comment accéderez" not in done.stdout and "Langue" not in done.stdout
    assert "Continuer ? [O/n]" in done.stdout


def test_reconfigure(machine: Machine) -> None:
    done = machine.install("--reconfigure", answers="\n")
    assert done.returncode == 1 and "nothing installed here yet" in done.stderr
    assert machine.install("--yes", "--version", "v1.2.3", "--lang", "en").returncode == 0
    done = machine.install("--reconfigure", "--yes")  # questions, but --yes: refused
    assert done.returncode == 1 and "--reconfigure asks questions" in done.stderr
    machine.bootstrap = "ADMIN=kept"
    # vpn+lan -> VPN only: the current mode preselected, the switch confirmed; the existing
    # VPN's address proposed and kept.
    done = machine.install("--reconfigure", answers="3\nvpn\n\n\n",
                           env={"FAKE_PORT_BUSY": "1", "FAKE_UDP_BUSY": "1",
                                "FAKE_ADMIN_VPN_RUNNING": "1"})  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert "Your choice [2]" in done.stdout and "Langue" not in done.stdout
    assert 'Switching to "Only through the VPN"' in done.stderr
    assert "Current public address for the VPN:\n    203.0.113.7" in done.stdout
    assert "IP address or domain" not in done.stdout and "address changes" not in done.stderr
    assert "docker exec hivora python -m hivora backup-self" in machine.changes()
    assert machine.env()["HIVORA_ACCESS"] == '"vpn"'
    # VPN only -> local network only: the Admin VPN app stays, unprotected.
    done = machine.install("--reconfigure", answers="1\n\n", env={"FAKE_UDP_BUSY": "1"})
    assert done.returncode == 0, done.stderr
    assert 'the "Admin VPN" app stays installed but is no longer' in done.stderr
    assert machine.env()["HIVORA_ACCESS"] == '"lan"'


# --- M12-5d: a new address or port for an existing admin VPN (D17) -------------------------
OWN_UDP = {"FAKE_UDP_BUSY": "1", "FAKE_ADMIN_VPN_RUNNING": "1"}  # 51820: the admin VPN's own


def test_a_new_vpn_address_on_a_rerun(machine: Machine) -> None:
    assert machine.install("--yes", "--version", "v1.2.3").returncode == 0  # vpn+lan
    machine.bootstrap = "ADMIN=kept"
    done = machine.install("--yes", "--vpn-host", "home.example.org",
                           env={**OWN_UDP, "FAKE_PORT_BUSY": "1"})  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert ("The admin VPN address changes: 203.0.113.7:51820 → home.example.org:51820"
            in done.stderr) and "fix \"Endpoint\" in the WireGuard app" in done.stderr  # fmt: skip
    assert "The VPN restarts: it drops for a few seconds" in done.stderr  # a new revision
    assert "public address home.example.org (was: 203.0.113.7:51820)" in done.stdout
    assert "HIVORA_ADMIN_VPN_HOST=home.example.org" in machine.changes()[-1]
    assert "new address, admin.conf is being updated" in done.stdout
    assert "Setting up the admin VPN" not in done.stdout  # vpn+lan: never waited for (D14)
    assert machine.env()["HIVORA_VPN_HOST"] == '"home.example.org"'
    again = machine.install("--yes", env={**OWN_UDP, "FAKE_PORT_BUSY": "1"})  # same: quiet
    assert again.returncode == 0 and "address changes" not in again.stderr


def test_a_new_vpn_port_on_a_rerun(machine: Machine) -> None:
    assert machine.install("--yes", "--version", "v1.2.3").returncode == 0
    machine.bootstrap = "ADMIN=kept"
    busy = {**OWN_UDP, "FAKE_PORT_BUSY": "1"}  # 51830 taken too (the fake ss: every port)
    done = machine.install("--yes", "--vpn-port", "51830", env=busy)
    assert done.returncode == 1 and "UDP port 51830 is already in use" in done.stderr
    assert machine.changes() == []  # the admin VPN holds 51820, not 51830: refused
    done = machine.install("--yes", "--vpn-port", "51830", env={"FAKE_PORT_BUSY": "1"})
    assert done.returncode == 0, done.stderr
    assert "203.0.113.7:51820 → 203.0.113.7:51830" in done.stderr
    assert "The VPN restarts: it drops for a few seconds" in done.stderr
    assert "HIVORA_ADMIN_VPN_PORT=51830" in machine.changes()[-1]


def test_reconfigure_changes_the_vpn_address(machine: Machine) -> None:
    assert machine.install("--yes", "--version", "v1.2.3", "--lang", "fr").returncode == 0
    machine.bootstrap = "ADMIN=kept"
    # The current mode (Enter), the current address refused, a new one typed, continue.
    done = machine.install("--reconfigure", answers="\nn\n82.64.12.34\n\n",
                           env={**OWN_UDP, "FAKE_PORT_BUSY": "1"})  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert "Adresse publique actuelle du VPN :\n    203.0.113.7" in done.stdout
    assert "change : 203.0.113.7:51820 → 82.64.12.34:51820" in done.stderr
    assert "HIVORA_ADMIN_VPN_HOST=82.64.12.34" in machine.changes()[-1]


def test_vpn_only_waits_for_the_moved_admin_conf(machine: Machine) -> None:
    assert machine.install("--yes", "--version", "v1.2.3", "--access", "vpn").returncode == 0
    machine.bootstrap = "ADMIN=kept"
    done = machine.install("--yes", "--vpn-host", "home.example.org", env=OWN_UDP)
    assert done.returncode == 0, done.stderr
    assert (machine.data / "admin.conf").read_text().endswith("home.example.org:51820\n")
    assert "[QR PrivateKey = first]" in done.stdout and "vpn_late" not in done.stderr
    # admin.conf not rewritten (the server could not move it): no stale QR code, a warning.
    done = machine.install("--yes", "--vpn-host", "other.example.org",
                           env={**OWN_UDP, "FAKE_NO_ADMIN_CONF": "1"})  # fmt: skip
    assert done.returncode == 0 and "admin VPN is not ready yet" in done.stderr
    assert "[QR" not in done.stdout
