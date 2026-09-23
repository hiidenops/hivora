"""Stand-in for `docker compose` used by compose_runner unit tests.

Behaviour is driven by FAKE_COMPOSE_MODE: ok | fail | secret.
"""

import json
import os
import sys

args = sys.argv[1:]
mode = os.environ.get("FAKE_COMPOSE_MODE", "ok")
command = args[args.index("--file") + 2]

if command == "config":
    print(json.dumps({"name": args[args.index("--project-name") + 1], "argv": args}))
    sys.exit(0)

progress = [
    {"id": "Image demo:1", "status": "Working", "text": "Pulling"},
    {
        "id": "abc",
        "parent_id": "Image demo:1",
        "status": "Working",
        "text": "Downloading",
        "current": 50,
        "total": 100,
        "percent": 50,
    },
    {"id": "Container demo-web-1", "status": "Done", "text": "Started"},
]
if mode == "secret":
    progress.append({"id": "x", "status": "Working", "text": "token=s3cr3t-value"})
for line in progress:
    print(json.dumps(line), file=sys.stderr, flush=True)
print("not json at all", file=sys.stderr)
if mode == "fail":
    print(json.dumps({"error": True, "message": "pull access denied"}), file=sys.stderr)
    sys.exit(1)
