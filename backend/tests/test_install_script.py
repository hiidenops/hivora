"""deploy/install.sh, run with fake docker, ss, ip, id and timedatectl first in PATH: they
log their calls and answer as told; nothing touches the machine."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "deploy" / "install.sh"
PASSWORD = "abcde-fghjk-mnpqr-stuvw"

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
  exec) echo "/data/backups/_hivora/panel-x.tar.gz" ;;
  rm) rm -f "$FAKE_STATE/running"; echo hivora ;;
  run) case "$*" in
      *"python -m hivora bootstrap") printf '%s\n' "$FAKE_BOOTSTRAP" ;;
      *" -d "*) touch "$FAKE_STATE/running"; echo 0123abcd ;;
      *) exit 1 ;;
    esac ;;
  *) echo "unexpected: docker $*" >&2; exit 1 ;;
esac
"""
FAKES = {
    "docker": FAKE_DOCKER,
    "ss": '#!/bin/sh\n[ -z "${FAKE_PORT_BUSY:-}" ] || echo "LISTEN 0 4096 0.0.0.0:8443 x"\n',
    "ip": "#!/bin/sh\necho '1.1.1.1 via 192.168.1.1 dev eth0 src 192.168.1.10 uid 0'\n",
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

    def install(self, *args: str, script: Path = SCRIPT,
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:  # fmt: skip
        self.log.unlink(missing_ok=True)
        full = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.root),
                "FAKE_LOG": str(self.log), "FAKE_STATE": str(self.state),
                "FAKE_BOOTSTRAP": self.bootstrap, "HIVORA_OS_RELEASE": str(self.os_release),
                "HIVORA_HEALTH_TIMEOUT": "4", **(env or {})}  # fmt: skip
        cmd = ["/bin/sh", str(script), "--data", str(self.data), "--srv", str(self.srv), *args]
        return subprocess.run(cmd, env=full, capture_output=True, text=True, timeout=60,  # noqa: S603
                              check=False, start_new_session=True)  # fmt: skip

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def changes(self) -> list[str]:
        """The calls that change something (pull, run, rm, exec)."""
        return [c for c in self.calls() if c.split()[1] in ("pull", "run", "rm", "exec")]

    def env(self) -> dict[str, str]:
        lines = (self.data / "install.env").read_text().splitlines()
        return dict(line.split("=", 1) for line in lines if not line.startswith("#"))


@pytest.fixture
def machine(tmp_path: Path) -> Machine:
    return Machine(tmp_path)


def test_a_fresh_install_bootstraps_before_the_server(machine: Machine) -> None:
    done = machine.install("--yes", "--version", "v1.2.3")
    assert done.returncode == 0, done.stderr
    pull, boot, start = machine.changes()
    assert pull == "docker pull ghcr.io/hiidenops/hivora:v1.2.3"
    assert "--rm" in boot and boot.endswith("hivora:v1.2.3 python -m hivora bootstrap")
    assert "docker.sock" not in boot  # the bootstrap needs no Docker
    assert "-p 192.168.1.10:8443:8443" in start and "HIVORA_ACCESS=lan" in start
    assert f"-v {machine.data}:{machine.data}" in start
    assert f"Password: {PASSWORD}" in done.stdout
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
    assert "Password" not in done.stdout and "Existing accounts kept" in done.stdout


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
    for mode in ("vpn", "vpn+lan"):
        done = machine.install("--yes", "--version", "v1.2.3", "--access", mode)
        assert done.returncode == 1 and "admin VPN" in done.stderr
        assert machine.changes() == []
    done = machine.install("--yes", "--version", "v1.2.3", "--access", "public")
    assert done.returncode == 1 and "--i-understand" in done.stderr
    done = machine.install("--yes", "--version", "v1.2.3", "--access", "public", "--i-understand")
    assert done.returncode == 0, done.stderr
    assert (
        "-p 0.0.0.0:8443:8443" in machine.changes()[-1]
        and "HIVORA_ACCESS=public" in machine.changes()[-1]
    )
    assert machine.env()["HIVORA_ACCESS"] == '"public"'


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
    assert "--version v1.2.3" in done.stderr
    assert os.path.exists(machine.data / "install.env")
    assert machine.env()["HIVORA_VERSION"] == '"v1.2.3"'  # untouched until success
