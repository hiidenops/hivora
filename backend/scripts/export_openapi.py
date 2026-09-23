"""Write the OpenAPI schema (used to generate the frontend's typed client).

Usage: uv run python scripts/export_openapi.py ../frontend/lib/api/openapi.json
"""

import json
import sys
from pathlib import Path

from hivora.main import create_app

target = Path(sys.argv[1])
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
print(f"wrote {target}")
