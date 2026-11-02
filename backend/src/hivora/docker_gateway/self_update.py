"""Docker calls of the self-update (M13): Hivora's own container replaced by a release.

The only code that creates, renames or removes Hivora's container (exception of 02/11/2026,
CLAUDE.md). Fixed operations on the container labelled ``io.hivora.self=true``, its
``-previous`` copy and the ``hivora-updater`` helper; the steps live in
``hivora.system.self_update``.
"""

import asyncio
import json
from typing import Any

import aiodocker

SELF_LABEL = "io.hivora.self"
UPDATER_LABEL = "io.hivora.updater"
UPDATER_NAME = "hivora-updater"
SOCKET = "/var/run/docker.sock"


class SelfDocker:
    def __init__(self, docker: aiodocker.Docker | None = None) -> None:
        self._docker = docker or aiodocker.Docker()

    async def close(self) -> None:
        await self._docker.close()

    async def find_self(self) -> dict[str, Any] | None:
        """The inspect of Hivora's container (started by the installer), None without one."""
        found = await self._docker._query_json(
            "containers/json", params={"all": "1", "filters": f'{{"label":["{SELF_LABEL}=true"]}}'}
        )  # fmt: skip
        return await self.inspect(found[0]["Id"]) if found else None

    async def inspect(self, name: str) -> dict[str, Any]:
        return dict(await self._docker._query_json(f"containers/{name}/json"))

    async def exists(self, name: str) -> bool:
        try:
            await self.inspect(name)
            return True
        except aiodocker.DockerError as exc:
            if exc.status == 404:
                return False
            raise

    async def image(self, ref: str) -> dict[str, Any]:
        return dict(await self._docker.images.inspect(ref))

    async def pull(self, ref: str) -> list[str]:
        """Pull ``ref``; its repo digests (``name@sha256:…``)."""
        await self._docker.images.pull(ref)
        return list((await self.image(ref)).get("RepoDigests") or [])

    async def _post(self, path: str, method: str = "POST",
                    params: dict[str, str] | None = None) -> None:  # fmt: skip
        async with self._docker._query(path, method=method, params=params):
            pass

    async def stop(self, name: str, grace: int = 30) -> None:
        await self._post(f"containers/{name}/stop", params={"t": str(grace)})

    async def rename(self, name: str, new: str) -> None:
        await self._post(f"containers/{name}/rename", params={"name": new})

    async def start(self, name: str) -> None:
        await self._post(f"containers/{name}/start")

    async def remove(self, name: str) -> None:
        await self._post(f"containers/{name}", method="DELETE", params={"force": "1"})

    async def create(self, name: str, body: dict[str, Any]) -> None:
        await self._docker.containers.create(body, name=name)

    async def connect(self, network: str, name: str, endpoint: dict[str, Any]) -> None:
        body = json.dumps({"Container": name, "EndpointConfig": endpoint}).encode()
        await self._docker._query_json(f"networks/{network}/connect", method="POST", data=body)

    async def health(self, name: str) -> str:
        """``healthy``, ``starting``, ``unhealthy``, or the state when it is not running."""
        state = (await self.inspect(name)).get("State") or {}
        if not state.get("Running"):
            return str(state.get("Status") or "missing")
        return str((state.get("Health") or {}).get("Status") or "running")

    async def run(self, image: str, cmd: list[str], binds: list[str],
                  env: list[str]) -> tuple[int, str]:  # fmt: skip
        """Run a one-off command in ``image`` (``docker run --rm``): its exit code and output."""
        container = await self._docker.containers.create(
            {"Image": image, "Cmd": cmd, "Env": env, "HostConfig": {"Binds": binds}}
        )
        try:
            await container.start()
            result = await container.wait()
            out = "".join(await container.log(stdout=True, stderr=True))
            return int(result.get("StatusCode", 1)), out
        finally:
            await container.delete(force=True)

    async def launch_updater(self, image: str, cmd: list[str], data_dir: str,
                             env: list[str]) -> None:  # fmt: skip
        """Start ``hivora-updater``: not privileged, the socket and the data folder only."""
        if await self.exists(UPDATER_NAME):  # a previous one that ended badly
            await self.remove(UPDATER_NAME)
        await self._docker.containers.create({
            "Image": image, "Cmd": cmd, "Env": env, "Labels": {UPDATER_LABEL: "true"},
            "HostConfig": {"Binds": [f"{SOCKET}:{SOCKET}", f"{data_dir}:{data_dir}"],
                           "AutoRemove": True},
        }, name=UPDATER_NAME)  # fmt: skip
        await self.start(UPDATER_NAME)

    async def wait_healthy(self, name: str, within: float, every: float = 2) -> str:
        """Its health once ``healthy`` or ``unhealthy`` or stopped, or after ``within`` seconds."""
        loop = asyncio.get_running_loop()
        end = loop.time() + within
        while True:
            status = await self.health(name)
            if status not in ("starting", "running") or loop.time() >= end:
                return status
            await asyncio.sleep(every)
