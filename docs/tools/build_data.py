"""Build the public docs catalog without importing or running the backend.

Run from any directory: python docs/tools/build_data.py [--check]
Only docs/assets/data is written. No Django, database, or environment is loaded.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
MODELS = ROOT / "src/taskiller/django_domain/models.py"
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
ADMIN_MODELS = {
    "StaffEnrollment",
    "StaffChallenge",
    "StaffSession",
    "StaffRecoveryCode",
    "AdminAuditRecord",
    "AdminCommandReceipt",
}
TYPES = {
    "UUIDField": "UUID",
    "CharField": "text",
    "TextField": "long text",
    "IntegerField": "integer",
    "SmallIntegerField": "small integer",
    "BooleanField": "boolean",
    "DateTimeField": "timestamp with timezone",
    "DateField": "date",
    "JSONField": "JSON",
    "PsycopgCompatibleJSONField": "JSON",
    "BinaryField": "binary bytes",
    "ForeignKey": "UUID reference",
    "OneToOneField": "unique UUID reference",
}


def literal(node, default=None):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return default


def load_content(name):
    return json.loads((DOCS / "content" / f"{name}.json").read_text(encoding="utf-8"))


def extract_entities(editorial):
    tree = ast.parse(MODELS.read_text(encoding="utf-8"))
    entities = []
    errors = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name in ADMIN_MODELS:
            continue
        meta = next(
            (item for item in node.body if isinstance(item, ast.ClassDef) and item.name == "Meta"),
            None,
        )
        if meta is None:
            continue
        table = next(
            (
                literal(item.value)
                for item in meta.body
                if isinstance(item, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "db_table" for t in item.targets)
            ),
            None,
        )
        if not table:
            continue
        if table not in editorial:
            errors.append(f"Missing entity explanation: {table}")
        text = editorial.get(table, {})
        fields = []
        composite = []
        for item in node.body:
            if not isinstance(item, ast.Assign) or not isinstance(item.value, ast.Call):
                continue
            target = item.targets[0]
            if not isinstance(target, ast.Name):
                continue
            call = item.value
            kind = ast.unparse(call.func).split(".")[-1]
            options = {kw.arg: literal(kw.value) for kw in call.keywords if kw.arg}
            if kind == "CompositePrimaryKey":
                composite = [literal(arg) for arg in call.args]
                continue
            if kind not in TYPES:
                continue
            name = target.id
            related = kind in {"ForeignKey", "OneToOneField"}
            column = options.get("db_column") or (f"{name}_id" if related else name)
            help_text = text.get("fields", {}).get(name) or text.get("fields", {}).get(column)
            if not help_text:
                errors.append(f"Missing field explanation: {table}.{name}")
            field = {
                "name": name,
                "column": column,
                "kind": kind,
                "type": TYPES[kind],
                "nullable": bool(options.get("null", False)),
                "primaryKey": bool(options.get("primary_key", False)),
                "maxLength": options.get("max_length"),
                "description": help_text or "",
                "source": f"src/taskiller/django_domain/models.py#L{item.lineno}",
            }
            if related:
                related_model = ast.unparse(call.args[0]).strip("\"'")
                field["relatedModel"] = node.name if related_model == "self" else related_model
                field["relation"] = "one-to-one" if kind == "OneToOneField" else "many-to-one"
                field["onDelete"] = "DO_NOTHING; application code removes dependencies explicitly"
            fields.append(field)
        constraints, indexes = [], []
        for item in meta.body:
            value = getattr(item, "value", None)
            target = (
                item.targets[0]
                if isinstance(item, ast.Assign)
                else item.target
                if isinstance(item, ast.AnnAssign)
                else None
            )
            if not isinstance(target, ast.Name) or target.id not in {"constraints", "indexes"}:
                continue
            for expression in getattr(value, "elts", []):
                if not isinstance(expression, ast.Call):
                    continue
                keywords = {kw.arg: kw.value for kw in expression.keywords if kw.arg}
                record = {
                    "name": literal(keywords.get("name"), ""),
                    "definition": ast.unparse(expression),
                }
                (constraints if target.id == "constraints" else indexes).append(record)
        entities.append(
            {
                **{key: value for key, value in text.items() if key != "fields"},
                "id": table,
                "model": node.name,
                "fields": fields,
                "compositeKey": composite,
                "constraints": constraints,
                "indexes": indexes,
                "source": [
                    f"src/taskiller/django_domain/models.py#L{node.lineno}",
                    *text.get("source", []),
                ],
            }
        )
    model_tables = {item["model"]: item["id"] for item in entities}
    relations = []
    for entity in entities:
        for field in entity["fields"]:
            if "relatedModel" in field:
                field["relatedTable"] = model_tables[field["relatedModel"]]
                relations.append(
                    {
                        "from": entity["id"],
                        "to": field["relatedTable"],
                        "field": field["column"],
                        "kind": field["relation"],
                        "nullable": field["nullable"],
                    }
                )
    return entities, relations, errors


def notes_index():
    current = {
        "ARCHITECTURE",
        "SECURITY",
        "PRODUCTION",
        "RUNBOOK",
        "OPERATIONS",
        "OBSERVABILITY",
        "DJANGO_PHASE10",
        "DJANGO_TYPECHECK_GAP",
        "ADMIN_CONSOLE",
    }
    omitted = {"README.md", "PRODUCT.md", "DESIGN.md"}
    records = []
    for path in sorted(DOCS.rglob("*.md")):
        relative = path.relative_to(DOCS).as_posix()
        if path.name in omitted or relative.startswith("superpowers/"):
            continue
        text = path.read_text(encoding="utf-8")
        heading = next(
            (line.lstrip("# ") for line in text.splitlines() if line.startswith("# ")),
            path.stem.replace("_", " ").title(),
        )
        category = (
            "Current operations"
            if path.stem in current
            else "Audit & remediation"
            if relative.startswith("audits/")
            else "Historical domain & migration notes"
        )
        records.append({"path": relative, "title": heading, "category": category})
    return records


def build():
    contract = json.loads((ROOT / "openapi/current.json").read_text(encoding="utf-8"))
    # This is the product field guide. Console workflows have a separate reference.
    contract["paths"] = {
        path: item
        for path, item in contract["paths"].items()
        if not path.startswith("/api/v1/admin/")
    }
    contract["components"]["schemas"] = {
        name: schema
        for name, schema in contract["components"]["schemas"].items()
        if not name.startswith("Admin")
    }
    contract["components"].get("securitySchemes", {}).pop("staffCookie", None)
    descriptions = load_content("endpoints")
    entity_text = load_content("entities")
    guides = load_content("guides")
    field_help = load_content("api-fields")

    def check_properties(schema):
        if not isinstance(schema, dict):
            return
        for name, definition in schema.get("properties", {}).items():
            if name not in field_help and not definition.get("description"):
                raise SystemExit(f"Missing API property explanation: {name}")
        for value in schema.values():
            if isinstance(value, dict):
                check_properties(value)
            elif isinstance(value, list):
                for item in value:
                    check_properties(item)

    check_properties(contract["components"]["schemas"])
    entities, relations, errors = extract_entities(entity_text)
    framework = load_content("framework-entities")
    entities.extend(framework)
    for entity in framework:
        for field in entity["fields"]:
            if field.get("relatedTable"):
                relations.append(
                    {
                        "from": entity["id"],
                        "to": field["relatedTable"],
                        "field": field["column"],
                        "kind": field["relation"],
                        "nullable": field["nullable"],
                    }
                )
    operations = []
    tables = {item["id"] for item in entities}
    for path, path_item in contract["paths"].items():
        for method, operation in path_item.items():
            if method not in METHODS:
                continue
            operation_id = operation["operationId"]
            text = descriptions.get(operation_id)
            if not text:
                errors.append(f"Missing endpoint explanation: {operation_id}")
                continue
            for table in [
                *text.get("reads", []),
                *(item["table"] for item in text.get("writes", [])),
            ]:
                if table not in tables:
                    errors.append(f"Unknown table {table} in {operation_id}")
            operations.append(
                {
                    **text,
                    "id": operation_id,
                    "method": method.upper(),
                    "path": path,
                    "contract": operation,
                }
            )
    operation_ids = {item["id"] for item in operations}
    for journey in guides["journey"]:
        if journey["operationId"] not in operation_ids:
            errors.append(f"Unknown walkthrough operation: {journey['operationId']}")
    if errors:
        raise SystemExit("Documentation coverage failed:\n" + "\n".join(errors))
    # Fingerprint the generated product material, not unrelated console source or
    # platform-dependent checkout bytes. The freshness check still compares the
    # entire catalog, including source links and every projected field.
    fingerprint_payload = {
        "contract": contract,
        "entities": entities,
        "relations": relations,
        "operations": operations,
        "guides": guides,
        "fieldHelp": field_help,
    }
    digest = hashlib.sha256(
        json.dumps(
            fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    return {
        "meta": {
            "name": "Taskiller product backend field guide",
            "scope": "Product API and product data only; console operations are excluded.",
            "adminReference": "ADMIN_CONSOLE.md",
            "version": contract["info"]["version"],
            "fingerprint": digest.hexdigest()[:16],
            "apiOperations": len(operations),
            "entities": len(entities),
            "domainEntities": len(entities) - len(framework),
            "frameworkEntities": len(framework),
            "fields": sum(len(e["fields"]) for e in entities),
            "schemas": len(contract["components"]["schemas"]),
        },
        "operations": operations,
        "entities": entities,
        "relations": relations,
        "schemas": contract["components"]["schemas"],
        "fieldHelp": field_help,
        "guides": guides,
        "problems": contract.get("x-taskiller-problem-codes", []),
        "notes": notes_index(),
    }, contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated data is stale")
    args = parser.parse_args()
    catalog, contract = build()
    outputs = {
        DOCS / "assets/data/catalog.js": "window.TASKILLER_DATA = "
        + json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        DOCS / "assets/data/openapi.json": json.dumps(contract, ensure_ascii=False, indent=2)
        + "\n",
    }
    for path, text in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                before = path.read_text(encoding="utf-8") if path.exists() else ""
                first = next(
                    (i for i, (a, b) in enumerate(zip(before, text, strict=False)) if a != b),
                    min(len(before), len(text)),
                )
                raise SystemExit(
                    f"Stale documentation data: {path.relative_to(ROOT)} at character {first}; "
                    f"stored={before[max(0, first - 35) : first + 90]!r}; "
                    f"generated={text[max(0, first - 35) : first + 90]!r}"
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    meta = catalog["meta"]
    print(
        f"Docs coverage OK: {meta['apiOperations']} operations, {meta['entities']} entities, "
        f"{meta['fields']} database fields, {meta['schemas']} API schemas; "
        f"{len(catalog['relations'])} foreign-key relationships."
    )


if __name__ == "__main__":
    main()
