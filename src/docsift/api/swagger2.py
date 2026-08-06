"""Convert this API's OpenAPI 3.1 document into Swagger 2.0.

Power Platform custom connectors accept Swagger 2.0; FastAPI emits OpenAPI 3.1,
so the generated document cannot be imported directly. This converter handles
the constructs this API's own routes and models produce today; the test suite
pins that current shape, so a change to a route or schema that shifts it out
of what's handled here should break a test.

It does not detect every OpenAPI construct that Swagger 2.0 cannot represent.
It explicitly raises `UnsupportedConstructError` for the ones known to be both
illegal in Swagger 2.0 and plausible for this API to someday emit: a request
body media type outside multipart/form-data and application/json, a `cookie`
parameter, `oneOf` anywhere in a parameter or schema, and a literal 3.1-style
type list (e.g. `type: ["string", "null"]`) that `_flatten_nullable` did not
already reduce via the `anyOf: [X, null]` idiom. Anything else -- an extra
response media type, a non-scalar `anyOf` (e.g. object|array), and so on --
passes through unexamined; it may produce a document a connector wizard
rejects rather than raising here. `allOf` is left alone deliberately: Swagger
2.0 supports it in schemas, so there is nothing to convert.

One conversion is lossy without raising: `_flatten_nullable` collapses an
`anyOf` of all-scalar types (Pydantic emits this for
`ValidationError.loc: str | int`) down to a single `type: string`, because
Swagger 2.0 has no union type. That is a deliberate approximation for a
diagnostic-only field, not a general-purpose union encoding.
"""

from typing import Any
from urllib.parse import urlparse

from docsift.core.exceptions import DocSiftError

_SUPPORTED_REQUEST_MEDIA = {"multipart/form-data", "application/json"}


class UnsupportedConstructError(DocSiftError):
    """The OpenAPI document uses something this converter does not handle."""


def _convert_refs(node: Any) -> Any:
    if isinstance(node, dict):
        converted = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                converted[key] = value.replace("#/components/schemas/", "#/definitions/")
            else:
                converted[key] = _convert_refs(value)
        return converted
    if isinstance(node, list):
        return [_convert_refs(item) for item in node]
    return node


def _flatten_nullable(node: Any) -> Any:
    """Rewrite `anyOf: [X, null]` as X with `x-nullable`.

    Pydantic emits that shape for every optional field; Swagger 2.0 has no
    `anyOf`, and a connector wizard rejects a document containing one.
    """
    if isinstance(node, list):
        return [_flatten_nullable(item) for item in node]
    if not isinstance(node, dict):
        return node

    node = {key: _flatten_nullable(value) for key, value in node.items()}
    if "oneOf" in node:
        # Illegal in Swagger 2.0 (which has no discriminated-union keyword),
        # and unlike anyOf-with-null there is no single safe collapse -- the
        # branches are meant to be mutually exclusive alternatives, not one
        # optional type.
        raise UnsupportedConstructError(f"oneOf is not representable in Swagger 2.0: {node}")
    if isinstance(node.get("type"), list):
        # The OpenAPI 3.1-native nullable idiom, e.g. type: ["string", "null"].
        # Only the anyOf: [X, null] shape (Pydantic's own idiom) is flattened
        # above; a literal list here means something this converter has not
        # been taught to reduce.
        raise UnsupportedConstructError(
            f"type as a list is not representable in Swagger 2.0: {node['type']!r}"
        )
    options = node.get("anyOf")
    if isinstance(options, list):
        non_null = [option for option in options if option.get("type") != "null"]
        has_null = len(non_null) != len(options)
        if len(non_null) == 1:
            merged = dict(non_null[0])
            for key, value in node.items():
                if key != "anyOf":
                    merged.setdefault(key, value)
            if has_null:
                merged["x-nullable"] = True
            return merged
        scalar_types = {option.get("type") for option in non_null}
        if scalar_types and scalar_types <= {"string", "integer", "number", "boolean"}:
            # Swagger 2.0 has no union type. FastAPI uses string|integer only
            # for ValidationError.loc; serialize that diagnostic path as a
            # string so the document remains usable by connector tooling.
            node = {key: value for key, value in node.items() if key != "anyOf"}
            node["type"] = "string"
            return node
    node.pop("examples", None)
    node.pop("const", None)
    node.pop("contentMediaType", None)
    return node


def _split_server(url: str) -> tuple[str, str, list[str]]:
    parsed = urlparse(url)
    if not parsed.netloc:
        raise UnsupportedConstructError(f"server url is not absolute: {url}")
    base_path = parsed.path.rstrip("/") or "/"
    return parsed.netloc, base_path, [parsed.scheme or "http"]


def _resolve_local_schema(schema: dict, schemas: dict) -> dict:
    reference = schema.get("$ref")
    prefix = "#/components/schemas/"
    if reference is None:
        return schema
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise UnsupportedConstructError(f"unsupported request schema reference: {reference}")
    name = reference.removeprefix(prefix)
    try:
        return schemas[name]
    except KeyError:
        raise UnsupportedConstructError(f"missing request schema reference: {name}") from None


def _request_body_parameters(operation: dict, schemas: dict) -> tuple[list[dict], list[str]]:
    body = operation.get("requestBody")
    if body is None:
        return [], []
    content = body.get("content", {})
    unsupported = set(content) - _SUPPORTED_REQUEST_MEDIA
    if unsupported:
        raise UnsupportedConstructError(f"unsupported request media type(s): {sorted(unsupported)}")
    required = bool(body.get("required"))

    if "multipart/form-data" in content:
        raw_schema = _resolve_local_schema(
            content["multipart/form-data"].get("schema", {}), schemas
        )
        schema = _flatten_nullable(raw_schema)
        properties = schema.get("properties", {})
        raw_properties = raw_schema.get("properties", {})
        required_names = set(schema.get("required", []))
        parameters = []
        for name, spec in properties.items():
            raw_spec = raw_properties.get(name, {})
            parameter = {
                "name": name,
                "in": "formData",
                "required": name in required_names,
            }
            if spec.get("format") == "binary" or raw_spec.get("contentMediaType") == (
                "application/octet-stream"
            ):
                parameter["type"] = "file"
            else:
                parameter["type"] = spec.get("type", "string")
                if "default" in spec:
                    parameter["default"] = spec["default"]
            if spec.get("description"):
                parameter["description"] = spec["description"]
            parameters.append(parameter)
        return parameters, ["multipart/form-data"]

    schema = _convert_refs(_flatten_nullable(content["application/json"]["schema"]))
    return [{"name": "body", "in": "body", "required": required, "schema": schema}], [
        "application/json"
    ]


def _convert_responses(operation: dict) -> tuple[dict, list[str]]:
    responses: dict[str, Any] = {}
    produces: list[str] = []
    for status, response in operation.get("responses", {}).items():
        converted: dict[str, Any] = {"description": response.get("description", "")}
        content = response.get("content", {})
        # `produces` describes what a successful call returns. Pulling media
        # types from error responses too would mislabel an endpoint whose
        # success body isn't JSON -- e.g. getDocumentMarkdown's 200 has no
        # `content` (it uses response_class=Response) while its 422 does, so
        # aggregating across all statuses would advertise application/json
        # for an endpoint that returns text/markdown.
        if str(status).startswith("2"):
            for media in content:
                if media not in produces:
                    produces.append(media)
        for media_object in content.values():
            if "schema" in media_object:
                converted["schema"] = _convert_refs(_flatten_nullable(media_object["schema"]))
            break
        responses[str(status)] = converted
    return responses, produces


def to_swagger2(openapi: dict) -> dict:
    """Convert an OpenAPI 3.x document produced by this app into Swagger 2.0."""
    servers = openapi.get("servers") or [{"url": "http://127.0.0.1:8000"}]
    host, base_path, schemes = _split_server(servers[0]["url"])

    swagger: dict[str, Any] = {
        "swagger": "2.0",
        "info": {
            "title": openapi["info"]["title"],
            "version": openapi["info"]["version"],
            "description": openapi["info"].get("description") or openapi["info"].get("summary", ""),
        },
        "host": host,
        "basePath": base_path,
        "schemes": schemes,
        "paths": {},
    }

    schemas = openapi.get("components", {}).get("schemas", {})
    for path, operations in openapi.get("paths", {}).items():
        converted_path: dict[str, Any] = {}
        for method, operation in operations.items():
            for parameter in operation.get("parameters", []):
                if parameter.get("in") == "cookie":
                    raise UnsupportedConstructError(
                        f"cookie parameters are not representable in Swagger 2.0: "
                        f"{parameter.get('name')}"
                    )
            parameters = [
                _flatten_nullable(_convert_refs(parameter))
                for parameter in operation.get("parameters", [])
            ]
            for parameter in parameters:
                schema = parameter.pop("schema", None)
                if isinstance(schema, dict):
                    for key in (
                        "type",
                        "format",
                        "default",
                        "maximum",
                        "minimum",
                        "maxLength",
                        "minLength",
                        "enum",
                    ):
                        if key in schema:
                            parameter[key] = schema[key]
                    parameter.setdefault("type", "string")
            body_parameters, consumes = _request_body_parameters(operation, schemas)
            parameters.extend(body_parameters)
            responses, produces = _convert_responses(operation)

            converted: dict[str, Any] = {
                "operationId": operation["operationId"],
                "summary": operation.get("summary", ""),
                "description": operation.get("description", ""),
                "responses": responses,
            }
            if parameters:
                converted["parameters"] = parameters
            if consumes:
                converted["consumes"] = consumes
            if produces:
                converted["produces"] = produces
            if "security" in operation:
                converted["security"] = operation["security"]
            converted_path[method] = converted
        swagger["paths"][path] = converted_path

    if schemas:
        swagger["definitions"] = _convert_refs(_flatten_nullable(schemas))

    schemes_in = openapi.get("components", {}).get("securitySchemes")
    if schemes_in:
        swagger["securityDefinitions"] = schemes_in
    if openapi.get("security"):
        swagger["security"] = openapi["security"]

    return swagger
