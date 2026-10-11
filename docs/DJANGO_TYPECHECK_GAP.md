# Django typing gap after Phase 10

The initial Django migration uses model declarations such as `id = models.UUIDField(...)`.
Under this project's current Pyright configuration, accessing model-instance fields
is misinterpreted as accessing field descriptor objects, producing hundreds of
false positives. DRF's dynamic request types also require type narrowing.

The CI Pyright gate **currently checks only the framework-independent modules** listed
in `pyproject.toml`. **It does not certify Django API/ORM/worker type safety.**

Before broadening the gate, adopt a model/DRF typing strategy with proper runtime
model attributes and validate it against the actual Django tests. Restore
`include = ["src"]` when that work is complete.

Keep CI's Ruff, `manage.py check`, `makemigrations --check`, API contract checks,
smoke tests, and `pytest` gates enabled; never use a clean Pyright result alone
as evidence that the Django transfer is fully working.
