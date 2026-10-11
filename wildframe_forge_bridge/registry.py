# SPDX-License-Identifier: GPL-3.0-or-later
"""Command registry for Wildframe Forge Bridge for Blender.

Every command is a plain function ``fn(params) -> dict`` registered with :func:`command`.
Commands always run on Blender's main thread (see ``server.py``), so they may use ``bpy`` freely.
The same names, envelope and schema style are used by the Wildframe Forge Unreal plugin, so an AI client can
drive both applications with one vocabulary:

    {"ok": bool, "code": str, "message": str, "data": {...}, "warnings": [str]}

Raise :class:`CommandError` for an expected failure; any other exception is caught and returned as
``PYCMD_EXCEPTION`` with a trimmed traceback. Nothing a command does can stop the server.
"""

import traceback

MAX_TRACEBACK_CHARS = 6000
_COMMANDS = {}


class CommandError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


def command(name, description, params=None, required=(), mutating=False, destructive=False,
            examples=None, family=None, long_running=False):
    """Register a command. ``params`` maps name -> {"type": ..., "description": ..., "default": ...}."""

    def wrap(fn):
        key = name.strip().upper()
        if key in _COMMANDS:
            raise RuntimeError("Duplicate Wildframe Forge command %s" % key)
        _COMMANDS[key] = {
            "name": key,
            "family": family or key.split(".", 1)[0],
            "description": description,
            "mutating": bool(mutating),
            "destructive": bool(destructive),
            "longRunning": bool(long_running),
            "inputSchema": {
                "type": "object",
                "required": list(required),
                "additionalProperties": False,
                "properties": params or {},
            },
            "examples": examples or [],
            "_fn": fn,
        }
        return fn

    return wrap


def all_commands():
    return _COMMANDS


def public(entry):
    return {k: v for k, v in entry.items() if not k.startswith("_")}


_TYPES = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def _check_type(value, expected):
    names = expected if isinstance(expected, (list, tuple)) else [expected]
    for type_name in names:
        if type_name == "null" and value is None:
            return True
        py = _TYPES.get(type_name)
        if py is None:
            return True
        if type_name in ("integer", "number") and isinstance(value, bool):
            continue
        if isinstance(value, py):
            return True
    return False


def validate(entry, params):
    """Minimal JSON-schema validation (type, required, enum, unknown keys) plus defaults."""
    schema = entry["inputSchema"]
    props = schema.get("properties", {})
    if not isinstance(params, dict):
        raise CommandError("BAD_PARAMS", "params must be an object.")
    params = dict(params)
    # forgiving aliases AIs commonly use: name <-> names, a single string where a list is expected
    if "name" in params and "name" not in props and "names" in props and "names" not in params:
        params["names"] = [params.pop("name")]
    if "names" in params and "name" in props and "names" not in props and "name" not in params:
        names = params.pop("names")
        params["name"] = names[0] if isinstance(names, list) and len(names) == 1 else names
    for key, prop in props.items():
        if prop.get("type") == "array" and isinstance(params.get(key), str):
            params[key] = [params[key]]
    unknown = [k for k in params if k not in props]
    if unknown:
        raise CommandError("UNKNOWN_PARAMS", "Unknown parameter(s): %s. Known: %s."
                           % (", ".join(sorted(unknown)), ", ".join(sorted(props)) or "none"))
    for key in schema.get("required", []):
        if key not in params:
            raise CommandError("MISSING_PARAM", "Missing required parameter '%s'." % key)
    result = {}
    for key, prop in props.items():
        if key in params:
            value = params[key]
            if "type" in prop and value is not None and not _check_type(value, prop["type"]):
                raise CommandError("BAD_PARAM_TYPE", "Parameter '%s' must be %s." % (key, prop["type"]))
            if "enum" in prop and value not in prop["enum"]:
                raise CommandError("BAD_PARAM_VALUE", "Parameter '%s' must be one of %s." % (key, prop["enum"]))
            result[key] = value
        elif "default" in prop:
            default = prop["default"]
            result[key] = list(default) if isinstance(default, list) else (
                dict(default) if isinstance(default, dict) else default)
    return result


def envelope(ok, code="OK", message="", data=None, warnings=None):
    return {
        "ok": bool(ok),
        "code": code or ("OK" if ok else "FAILED"),
        "message": message or "",
        "data": data if isinstance(data, dict) else ({} if data is None else {"value": data}),
        "warnings": [str(w) for w in (warnings or [])],
    }


def run(name, params):
    """Run a command on the current (main) thread and always return an envelope."""
    key = str(name or "").strip().upper()
    entry = _COMMANDS.get(key)
    if entry is None:
        close = sorted(n for n in _COMMANDS if key.split(".")[0] and n.startswith(key.split(".")[0]))[:12]
        return envelope(False, "UNKNOWN_COMMAND", "No Blender command named %s." % key,
                        {"similar": close, "hint": "Use COMMAND.LIST or COMMAND.SEARCH."})
    try:
        clean = validate(entry, params or {})
        result = entry["_fn"](clean)
        if result is None:
            result = {}
        if not isinstance(result, dict):
            result = {"value": result}
        message = result.pop("_message", "") if isinstance(result.get("_message", ""), str) else ""
        warnings = result.pop("_warnings", []) or []
        return envelope(True, "OK_WITH_WARNINGS" if warnings else "OK", message, result, warnings)
    except CommandError as error:
        return envelope(False, error.code, error.message, error.data)
    except Exception as error:  # noqa: BLE001 - a failing command must never break the bridge
        trace = traceback.format_exc()
        return envelope(False, "PYCMD_EXCEPTION", "%s: %s" % (type(error).__name__, error),
                        {"error": {"type": type(error).__name__, "message": str(error),
                                   "traceback": trace[-MAX_TRACEBACK_CHARS:]}})
