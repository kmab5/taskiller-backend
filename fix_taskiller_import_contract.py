"""One-time Taskiller patch: register the portable import operation in canonical OpenAPI.

Run from the taskiller-backend repository root:
    python /path/to/fix_taskiller_import_contract.py
"""
from __future__ import annotations

import json
from pathlib import Path

root = Path.cwd()
canonical_path = root / "openapi" / "current.json"
checker_path = root / "scripts" / "django_phase8_cutover_check.py"
if not canonical_path.is_file() or not checker_path.is_file():
    raise SystemExit("Run this script from the taskiller-backend repository root.")

canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
endpoint = "/api/v1/portable-work/import"
operation = {
    "operationId": "importPortableWork",
    "tags": ["Work"],
    "summary": "Import Portable Work",
    "security": [{"bearerAuth": []}],
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": {"type": "object"}}},
    },
    "responses": {
        "201": {
            "description": "Created",
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    },
}
existing = canonical["paths"].get(endpoint, {}).get("post")
if existing is None:
    canonical["paths"][endpoint] = {"post": operation}
    canonical["paths"] = dict(sorted(canonical["paths"].items()))
    canonical_path.write_text(json.dumps(canonical, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Added POST {endpoint} to {canonical_path}")
elif existing.get("operationId") == "importPortableWork" and existing.get("security") == operation["security"]:
    print("Portable import contract already exists; left unchanged.")
else:
    raise SystemExit(f"Existing contract for {endpoint} differs; inspect manually before updating.")

checker = checker_path.read_text(encoding="utf-8")
old = 'errors.append(f"unexpected Django API operations: {unexpected!r}")'
new = '''errors.append(
            f"unexpected Django API operations: {unexpected!r}\\n"
            "New Django endpoints must be intentionally documented in "
            "openapi/current.json (matching path, method, operationId, tags "
            "and security). Do not disable this check."
        )'''
if old in checker:
    checker_path.write_text(checker.replace(old, new), encoding="utf-8")
    print("Improved contract-drift diagnostic.")
elif "New Django endpoints must be intentionally documented" in checker:
    print("Contract-drift diagnostic already improved.")
else:
    print("Checker diagnostic differs from expected; left unchanged.")

print("Now run: PYTHONPATH=src uv run python scripts/django_phase8_cutover_check.py")
print("Then run: PYTHONPATH=src uv run python scripts/django_phase4_contract.py")
print("Finally run: uv run pytest")
