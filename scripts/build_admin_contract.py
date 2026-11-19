"""Generate the additive console contract without importing Django or loading secrets.

Run with Python only; --check is intended for GitHub CI. Product definitions are retained.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "src/taskiller/django_api/admin_api"
PREFIX = "/api/v1/admin/"
METHODS = {"get", "post", "patch", "put", "delete"}


def literal(node, default=None):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return default


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def schema_name(name):
    name = name.split(".")[-1]
    name = name.removesuffix("Serializer")
    return name if name.startswith("Admin") else "Admin" + name


def serializer_schemas():
    """Read declared serializer fields using AST; never instantiate backend code."""
    classes, pages, constants = {}, {}, {}
    for path in sorted(ADMIN.glob("*serializers.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef):
                classes[node.name] = node
            elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if isinstance(node.value, (ast.Tuple, ast.List, ast.Set)):
                    values = []
                    for item in node.value.elts:
                        if isinstance(item, ast.Starred) and isinstance(item.value, ast.Name):
                            values.extend(constants[item.value.id])
                        else:
                            values.append(literal(item))
                    constants[name] = values
                else:
                    constants[name] = literal(node.value)
                if (
                    isinstance(node.value, ast.Call)
                    and ast.unparse(node.value.func) == "page_serializer"
                ):
                    pages[name] = ast.unparse(node.value.args[1])

    def field(call):
        kind = ast.unparse(call.func).split(".")[-1]
        kw = {item.arg: item.value for item in call.keywords}
        options = {key: literal(value) for key, value in kw.items()}
        if kind in classes or kind in pages:
            result = ref(schema_name(kind))
        elif kind in {"IntegerField", "FloatField", "DecimalField", "BooleanField"}:
            result = {
                "type": {"IntegerField": "integer", "BooleanField": "boolean"}.get(kind, "number")
            }
        elif kind in {"ListField", "ListSerializer"}:
            result = {"type": "array", "items": field(kw["child"]) if "child" in kw else {}}
        elif kind in {"DictField", "JSONField"}:
            result = {"type": "object", "additionalProperties": True}
        else:
            result = {"type": "string"}
            fmt = {
                "UUIDField": "uuid",
                "DateTimeField": "date-time",
                "DateField": "date",
                "EmailField": "email",
                "URLField": "uri",
            }.get(kind)
            if fmt:
                result["format"] = fmt
        choices = options.get("choices")
        if choices is None and isinstance(kw.get("choices"), ast.Name):
            choices = constants.get(kw["choices"].id)
        if choices is not None:
            result["enum"] = list(choices)
        if kind == "RegexField" and call.args:
            result["pattern"] = literal(call.args[0])
        if options.get("many"):
            result = {"type": "array", "items": result}
        for source, target in {
            "min_length": "minItems" if result.get("type") == "array" else "minLength",
            "max_length": "maxItems" if result.get("type") == "array" else "maxLength",
            "min_value": "minimum",
            "max_value": "maximum",
        }.items():
            if options.get(source) is not None:
                result[target] = options[source]
        if options.get("write_only"):
            result["writeOnly"] = True
        if options.get("read_only"):
            result["readOnly"] = True
        if options.get("help_text"):
            result["description"] = options["help_text"]
        if "default" in options and options["default"] is not None:
            result["default"] = options["default"]
        if options.get("allow_null"):
            result = {"anyOf": [result, {"type": "null"}]}
        return result

    def properties(name):
        node = classes[name]
        props, required = {}, []
        for base in node.bases:
            parent = ast.unparse(base).split(".")[-1]
            if parent in classes:
                inherited, mandatory = properties(parent)
                props.update(inherited)
                required.extend(mandatory)
        for item in node.body:
            if not isinstance(item, ast.Assign) or not isinstance(item.value, ast.Call):
                continue
            if not isinstance(item.targets[0], ast.Name):
                continue
            key = item.targets[0].id
            opts = {kw.arg: literal(kw.value) for kw in item.value.keywords}
            props[key] = field(item.value)
            if opts.get("required", True) and "default" not in opts and key not in required:
                required.append(key)
        return props, required

    result = {}
    for name in classes:
        props, required = properties(name)
        if props:
            result[schema_name(name)] = {
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            }
    for name, item in pages.items():
        result[schema_name(name)] = {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": ref(schema_name(item))},
                "nextCursor": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "required": ["items", "nextCursor"],
            "additionalProperties": False,
        }
    return result


def build(contract):
    result = copy.deepcopy(contract)
    schemas = serializer_schemas()
    roles = ["Owner", "Administrator", "Support", "Analyst"]
    capabilities = []
    for node in ast.parse((ADMIN / "permissions.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CAPABILITIES" for target in node.targets
        ):
            capabilities = sorted(literal(node.value.args[0]))
    for schema in schemas.values():
        for name, prop in schema.get("properties", {}).items():
            if name in {"roles", "capabilities"} and prop.get("type") == "array":
                prop["items"] = {
                    "type": "string",
                    "enum": roles if name == "roles" else capabilities,
                }
    schemas["AdminRole"]["properties"]["name"]["enum"] = roles
    for name in ("AdminStaffMeResponse", "AdminEnrollmentResponse"):
        schemas[name]["properties"]["csrfToken"] = {
            "type": "string",
            "description": "Masked token after CSRF rotation.",
        }
    corrections = (
        ("update-item", "UpdateWorkItemRequest"),
        ("update-type", "UpdateWorkTypeRequest"),
        ("update-plan", "UpdateFocusPlanRequest"),
        ("session-event", "CreateSessionEventRequest"),
    )
    for name in ("AdminWorkCorrection", "AdminBulkTarget"):
        schemas[name]["properties"]["correction"] = {
            "anyOf": [ref(payload) for _, payload in corrections]
        }
    schemas["AdminWorkCorrection"]["oneOf"] = [
        {"properties": {"operation": {"const": operation}, "correction": ref(payload)}}
        for operation, payload in corrections
    ]
    schemas["AdminBulkResult"] = {
        "type": "object",
        "required": ["targetId"],
        "additionalProperties": False,
        "properties": {
            "targetId": {"type": "string", "format": "uuid"},
            "eligible": {"type": "boolean"},
            "code": {"type": "string"},
            "status": {"type": "integer"},
            "outcome": {"type": "string", "enum": ["success", "failed"]},
            "result": ref("AdminCommandResponse"),
        },
    }
    schemas["AdminBulkResponse"]["properties"]["results"]["items"] = ref("AdminBulkResult")
    paths = {}
    # Endpoint metadata comes from committed decorators and URL declarations, statically.
    views, parents = {}, {}
    for path in sorted(ADMIN.glob("*views.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(node, ast.ClassDef):
                continue
            parents[node.name] = [ast.unparse(base).split(".")[-1] for base in node.bases]
            operations = {}
            for method in node.body:
                if not isinstance(method, ast.FunctionDef) or method.name not in METHODS:
                    continue
                for decorator in method.decorator_list:
                    if (
                        not isinstance(decorator, ast.Call)
                        or ast.unparse(decorator.func) != "extend_schema"
                    ):
                        continue
                    options = {kw.arg: kw.value for kw in decorator.keywords}
                    operation_id = literal(options.get("operation_id"))
                    operation = {
                        "operationId": operation_id,
                        "tags": literal(options.get("tags"), ["Admin"]),
                        "summary": literal(options.get("summary"), node.name),
                        "security": [{"staffCookie": []}],
                        "parameters": [],
                        "responses": {},
                    }
                    for parameter in getattr(options.get("parameters"), "elts", []):
                        definition = schemas[schema_name(ast.unparse(parameter))]
                        for name, prop in definition["properties"].items():
                            operation["parameters"].append(
                                {
                                    "name": name,
                                    "in": "query",
                                    "required": name in definition["required"],
                                    "schema": prop,
                                }
                            )
                    for key in ("request", "responses"):
                        value = options.get(key)
                        if value is None:
                            continue
                        if key == "request":
                            operation["requestBody"] = {
                                "required": True,
                                "content": {
                                    "application/json": {
                                        "schema": ref(
                                            schema_name(ast.unparse(value).removesuffix("()"))
                                        )
                                    }
                                },
                            }
                        else:
                            entries = (
                                zip(value.keys, value.values, strict=True)
                                if isinstance(value, ast.Dict)
                                else [(ast.Constant(value=200), value)]
                            )
                            for status, response in entries:
                                if isinstance(response, ast.Constant) and response.value is None:
                                    body = {}
                                else:
                                    response_name = ast.unparse(
                                        response.func
                                        if isinstance(response, ast.Call)
                                        else response
                                    )
                                    response_schema = ref(schema_name(response_name))
                                    if isinstance(response, ast.Call) and any(
                                        kw.arg == "many" and literal(kw.value)
                                        for kw in response.keywords
                                    ):
                                        response_schema = {
                                            "type": "array",
                                            "items": response_schema,
                                        }
                                    body = {
                                        "content": {"application/json": {"schema": response_schema}}
                                    }
                                operation["responses"][str(literal(status))] = {
                                    "description": "Console response",
                                    **body,
                                }
                    operations[method.name] = operation
            views[node.name] = operations

    def inherited_operations(name):
        operations = {}
        for parent in parents.get(name, []):
            operations.update(inherited_operations(parent))
        operations.update(views.get(name, {}))
        if name == "StaffRolesView":
            operations.pop("post", None)
        return operations

    for url_file in sorted(ADMIN.glob("*.py")):
        tree = ast.parse(url_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or ast.unparse(node.func) != "path"
                or len(node.args) < 2
            ):
                continue
            route = literal(node.args[0])
            view = node.args[1]
            if route is None or not isinstance(view, ast.Call):
                continue
            view_name = ast.unparse(view.func).removesuffix(".as_view").split(".")[-1]
            full_path = PREFIX + re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", route)
            operations = copy.deepcopy(inherited_operations(view_name))
            for method, operation in operations.items():
                if not operation["operationId"]:
                    # Spectacular infers /api/v1 as the common API path prefix.
                    tokens = (
                        re.sub(r"{\w+}", "", full_path.removeprefix("/api/v1"))
                        .strip("/")
                        .split("/")
                    )
                    action = {
                        "get": "retrieve",
                        "post": "create",
                        "patch": "partial_update",
                        "put": "update",
                        "delete": "destroy",
                    }[method]
                    if method == "get" and any(
                        response.get("content", {})
                        .get("application/json", {})
                        .get("schema", {})
                        .get("type")
                        == "array"
                        for response in operation["responses"].values()
                    ):
                        action = "list"
                    operation["operationId"] = "_".join(
                        [token.replace("-", "_") for token in tokens if token] + [action]
                    )
                if route.startswith("auth/") and route not in {"auth/logout", "auth/step-up"}:
                    operation["security"] = []
                for parameter in re.findall(r"{(\w+)}", full_path):
                    operation["parameters"].append(
                        {
                            "name": parameter,
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    )
                for parameter in operation["parameters"]:
                    if route.startswith("privacy/requests") and parameter["name"] == "type":
                        parameter["required"] = True
                is_command = (
                    method != "get"
                    and not route.startswith("auth/")
                    and route not in {"users/search", "bulk/preview"}
                )
                needs_etag = route.endswith(
                    (
                        "/suspend",
                        "/reactivate",
                        "/roles",
                        "/revoke-access",
                        "/correct",
                        "/privacy/deletion",
                    )
                )
                if is_command:
                    operation["parameters"].append(
                        {
                            "name": "Idempotency-Key",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": (
                                "Actor/operation/target/payload-bound retry key; "
                                "authorization rechecked on replay."
                            ),
                        }
                    )
                    if "200" in operation["responses"] and route not in {"bulk/execute"}:
                        operation["responses"]["202"] = copy.deepcopy(operation["responses"]["200"])
                        operation["responses"]["202"]["description"] = (
                            "Queued; not confirmation of delivery or completion."
                        )
                if needs_etag:
                    operation["parameters"].append(
                        {
                            "name": "If-Match",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": (
                                "Exact quoted resource ETag; missing or stale values return 412."
                            ),
                        }
                    )
                operation["description"] = (
                    "Dedicated staff console; product JWTs and Django Admin sessions are not "
                    "accepted. All responses use Cache-Control: private, no-store. "
                    "See docs/ADMIN_CONSOLE.md."
                )
                if method != "get":
                    operation["parameters"].append(
                        {
                            "name": "Origin",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string", "format": "uri"},
                            "description": (
                                "Exact allowlisted public console origin, preserved by relay."
                            ),
                        }
                    )
                    operation["parameters"].append(
                        {
                            "name": "X-CSRFToken",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": (
                                "Masked token from auth/csrf; approved exact Origin and "
                                "dedicated CSRF cookie required."
                            ),
                        }
                    )
                for status in (400, 401, 403, 404, 409, 412, 422, 429):
                    operation["responses"][str(status)] = {
                        "description": "Structured Problem Details",
                        "content": {"application/problem+json": {"schema": ref("Problem")}},
                    }
                for response in operation["responses"].values():
                    response["headers"] = {
                        "Cache-Control": {
                            "schema": {"type": "string", "const": "private, no-store"}
                        }
                    }
                    if needs_etag or view_name in {"UserDetailView", "WorkDetailView"}:
                        response["headers"]["ETag"] = {
                            "schema": {"type": "string"},
                            "description": "Current quoted resource version.",
                        }
            if operations:
                paths.setdefault(full_path, {}).update(operations)
    ids = {}
    for path, operations in sorted(paths.items()):
        for method, operation in sorted(operations.items()):
            name = operation["operationId"]
            ids[name] = ids.get(name, 0) + 1
            if ids[name] > 1:
                operation["operationId"] += f"_{ids[name]}"
    if not paths:
        raise ValueError("No declared console routes found; refusing to erase the contract")
    result["paths"] = {
        key: value for key, value in result["paths"].items() if not key.startswith(PREFIX)
    }
    result["paths"].update(paths)
    result["components"]["schemas"] = {
        key: value
        for key, value in result["components"]["schemas"].items()
        if not key.startswith("Admin")
    }
    result["components"]["schemas"].update(schemas)
    result["components"].setdefault("securitySchemes", {})["staffCookie"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": "taskiller_staff",
        "description": (
            "Opaque HttpOnly staff session; host-only, Path=/admin, SameSite=Lax, "
            "Secure in production. Use the same-origin console relay."
        ),
    }
    for node in ast.parse(
        (ROOT / "src/taskiller/core/problems.py").read_text(encoding="utf-8")
    ).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PROBLEM_CODES" for target in node.targets
        ):
            result["x-taskiller-problem-codes"] = sorted(literal(node.value.args[0]))
    return result


def update_problem_codes():
    """Add literal runtime error codes to the source catalog without importing it."""
    path = ROOT / "src/taskiller/core/problems.py"
    source = path.read_text(encoding="utf-8")
    assignment = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "PROBLEM_CODES" for target in node.targets
        )
    )
    codes = set(literal(assignment.value.args[0]))
    for module in sorted((ROOT / "src/taskiller").rglob("*.py")):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            function = ast.unparse(node.func).split(".")[-1]
            if function not in {"TaskillerAPIError", "ApiError"} and not (
                function == "_error" and module.is_relative_to(ADMIN)
            ):
                continue
            code = literal(node.args[1]) if len(node.args) > 1 else None
            for keyword in node.keywords:
                if keyword.arg == "code":
                    code = literal(keyword.value)
            if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]+", code):
                codes.add(code)
    replacement = "PROBLEM_CODES = frozenset(\n    {\n"
    replacement += "".join(f'        "{code}",\n' for code in sorted(codes))
    replacement += "    }\n)\n"
    lines = source.splitlines(keepends=True)
    lines[assignment.lineno - 1 : assignment.end_lineno] = [replacement]
    path.write_text("".join(lines), encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--update-problem-codes", action="store_true")
    args = parser.parse_args()
    if args.update_problem_codes:
        if args.check:
            parser.error("--update-problem-codes cannot be combined with --check")
        update_problem_codes()
    path = ROOT / "openapi/current.json"
    before = path.read_text(encoding="utf-8")
    after = json.dumps(build(json.loads(before)), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if before != after:
            raise SystemExit("Admin contract is stale; regenerate scripts/build_admin_contract.py")
    else:
        path.write_text(after, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
