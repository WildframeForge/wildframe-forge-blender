# SPDX-License-Identifier: GPL-3.0-or-later
"""AI Scripts for Blender: use ChatGPT, Grok or any chat AI without a connector.

Same idea and wording as the AI Scripts page in Unreal: copy a primer into any chat AI, paste the job it
writes, check it, run it, and copy the result (or the error report) back. Everything runs inside Blender,
so it also works on a PC that cannot run Blender and an AI app at the same time.

Job format (WILDFRAME_BLENDER_JOB_V1):
    {"schema": "WILDFRAME_BLENDER_JOB_V1", "name": "...",
     "operations": [{"id": "cube", "command": "OBJECTS.CREATE_PRIMITIVE", "params": {...}, "dependsOn": [...]}]}
Operations run in order and the job stops at the first failure. "${op_id.field}" in a string param inserts a
value from an earlier operation's result data. A ```python block becomes one PYTHON.EXECUTE operation (only
when "Allow raw Python" is on in the add-on preferences).

The logic here has no UI; ui.py draws the panel.
"""

import difflib
import json
import re

from . import prefs, registry

SCHEMA = "WILDFRAME_BLENDER_JOB_V1"
RESULT_SCHEMA = "WILDFRAME_BLENDER_RESULT_V1"
MAX_OPS = 40
RESULT_BUDGET = 12000
PRIMER_SOFT_LIMIT = 60000

HEADER = """# Wildframe Forge Bridge - AI primer (Blender)

You are helping me control Blender through the **Wildframe Forge Bridge** add-on on my PC.
You cannot reach my PC. Instead you write a job; I paste it into the AI Scripts panel in Blender (3D Viewport > N > Wildframe Forge), check it, run it, and paste the result back to you.

## How to reply
- When I ask for something to be done in Blender, reply with exactly ONE fenced ```json code block containing a WILDFRAME_BLENDER_JOB_V1 job.
- Put a short explanation before the block (what it does, what it changes). No other code blocks.
- If you need information first (object names, materials, the scene), send a small read-only job and wait for my result.

## Job format
```json
{
  "schema": "WILDFRAME_BLENDER_JOB_V1",
  "name": "Short task name",
  "operations": [
    { "id": "crate", "command": "OBJECTS.CREATE_PRIMITIVE", "params": { "primitive": "CUBE", "name": "Crate", "location": [0, 0, 1] } },
    { "id": "look", "command": "OBJECTS.GET", "dependsOn": ["crate"], "params": { "name": "${crate.name}" } }
  ]
}
```
- `id`: unique within the job (snake_case). `command`: exact name from the catalog below. `params`: a JSON object with only the parameters listed for that command (unknown names are rejected).
- `dependsOn`: ids of earlier operations that must succeed first. Operations run in order and the job stops at the first failure.
- A string param of the form `"${op_id.field}"` inserts a value from an earlier operation's result data (e.g. `"${crate.name}"`).
- Units are Blender units (metres) and degrees. Paths may use `~/Desktop/...`.
- The whole job is one undo step: I can press Ctrl+Z once to take it all back.

## Rules
1. Check the RECIPE.* commands first: each does a whole task in one operation. Then use the other commands.
2. Never invent command or parameter names. If unsure, send a job with COMMAND.DESCRIBE {"command": "THE.COMMAND"} first.
3. Keep jobs small (about 1-15 operations). Split long work into several jobs; I run them one after another and send you each result.
4. Commands marked DESTRUCTIVE need "confirm": true, and only for changes I asked for.
5. Do not delete objects, apply modifiers, or open/replace files unless I asked.
{python_rule}

## Reading results
After a run I click "Copy result for AI" and paste a ```json block with "schema": "WILDFRAME_BLENDER_RESULT_V1": the job `state`, and per operation `ok`, `code`, `message`, `warnings` and the (shortened) `data`. If an operation failed, fix only what failed and send a new, smaller job.
If the panel rejects a job before running it, I paste a report starting "Wildframe Forge could not run the job": it lists the errors, the parameters the failing commands take, and your job. Nothing ran, so send the corrected job.
Operations that already succeeded in a failed job are NOT undone (see `changesKept`): don't repeat them.

## Command catalog
Flags: `read` = read-only, `mut` = changes the scene, `DESTRUCTIVE` = needs "confirm": true. In params, `*` = required.
"""

PYTHON_ON = ("6. Raw Python is allowed here: if no command fits, reply with ONE ```python block instead (bpy is imported; print() "
             "output and a variable named `result` are returned to you).")
PYTHON_OFF = "6. Raw Python is switched off in my Blender. Use only the commands below."


def _python_allowed():
    try:
        return bool(prefs.get().allow_python)
    except Exception:  # noqa: BLE001
        return False


def _param_text(entry):
    schema = entry.get("inputSchema", {})
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    parts = []
    for name, prop in props.items():
        t = prop.get("type", "any")
        t = "|".join(t) if isinstance(t, (list, tuple)) else t
        if "enum" in prop:
            t = "|".join(str(v) for v in prop["enum"][:12])
        extra = (" = %s" % json.dumps(prop["default"])) if "default" in prop and prop["default"] not in (None, "", [], {}) else ""
        parts.append("%s%s: %s%s" % (name, "*" if name in required else "", t, extra))
    return ", ".join(parts)


def build_primer():
    """Markdown primer for any chat AI, built from the commands this add-on has."""
    python_ok = _python_allowed()
    commands = registry.all_commands()
    families = {}
    for name in sorted(commands):
        entry = commands[name]
        if name == "PYTHON.EXECUTE" and not python_ok:
            continue
        families.setdefault(entry["family"], []).append(entry)
    order = sorted(families, key=lambda f: (f != "RECIPE", f))

    def catalog(compact):
        lines = []
        for fam in order:
            lines.append("\n### %s" % fam)
            for e in families[fam]:
                flag = "DESTRUCTIVE" if e.get("destructive") else ("mut" if e.get("mutating") else "read")
                desc = e.get("description", "")
                if compact:
                    desc = desc.split(". ")[0]
                params = _param_text(e)
                lines.append("- `%s` (%s) %s%s" % (e["name"], flag, desc, (" Params: " + params) if params else ""))
        return "\n".join(lines)

    head = HEADER.replace("{python_rule}", PYTHON_ON if python_ok else PYTHON_OFF)
    body = catalog(False)
    if len(head) + len(body) > PRIMER_SOFT_LIMIT:
        body = catalog(True)
    return head + body + "\n"


# ---------------------------------------------------------------- parsing and checking
def parse_job(text):
    """Return (job, error). Accepts plain JSON, an AI reply with a ```json block, or a ```python block."""
    s = (text or "").strip()
    if not s:
        return None, "The job is empty. Paste the job your AI wrote (Paste job from clipboard)."
    py = re.search(r"```python\s*\n([\s\S]*?)```", s)
    if py and "```json" not in s:
        return {"schema": SCHEMA, "name": "Python from AI", "operations": [
            {"id": "python", "command": "PYTHON.EXECUTE", "params": {"code": py.group(1), "confirm": True}}]}, None
    candidates = [s] + [m.group(1).strip() for m in re.finditer(r"```(?:json)?\s*\n([\s\S]*?)```", s)]
    a, b = s.find("{"), s.rfind("}")
    if 0 <= a < b:
        candidates.append(s[a:b + 1])
    last = ""
    for c in candidates:
        try:
            job = json.loads(c)
            if isinstance(job, dict):
                return job, None
        except ValueError as error:
            last = str(error)
    return None, "This is not valid JSON (%s). Ask your AI to send the job again as one ```json block." % last


def check_job(job):
    """Return (plan, errors, warnings). Nothing runs."""
    errors, warnings, plan = [], [], []
    if not isinstance(job, dict):
        return plan, ['The job must be a JSON object with "schema" and "operations".'], warnings
    schema = job.get("schema")
    if schema and schema != SCHEMA:
        if "UNREAL" in str(schema).upper():
            errors.append("This is an Unreal job. Run it on the AI Scripts page in Unreal, not in Blender.")
        elif "ADOBE" in str(schema).upper():
            errors.append("This is an Adobe job. Run it on the AI Scripts page for Adobe apps (tray icon menu).")
        else:
            errors.append('"schema" must be "%s".' % SCHEMA)
    ops = job.get("operations")
    if not isinstance(ops, list) or not ops:
        errors.append('"operations" must be a non-empty list.')
        return plan, errors, warnings
    if len(ops) > MAX_OPS:
        errors.append("Too many operations (%d); split the job into jobs of at most %d." % (len(ops), MAX_OPS))
    commands = registry.all_commands()
    seen = set()
    for i, op in enumerate(ops):
        where = "Operation %d%s" % (i + 1, (' ("%s")' % op.get("id")) if isinstance(op, dict) and op.get("id") else "")
        if not isinstance(op, dict):
            errors.append("%s is not an object." % where)
            continue
        oid = str(op.get("id") or "op%d" % (i + 1))
        if oid in seen:
            errors.append('%s: id "%s" is used twice.' % (where, oid))
        for dep in op.get("dependsOn") or []:
            if str(dep) not in seen:
                errors.append('%s: dependsOn "%s" is not an earlier operation.' % (where, dep))
        seen.add(oid)
        name = str(op.get("command") or "").strip().upper()
        entry = commands.get(name)
        if not entry:
            near = difflib.get_close_matches(name, list(commands), n=3, cutoff=0.6)
            errors.append('%s: Blender has no command "%s".%s' % (where, op.get("command"), (" Similar: %s." % ", ".join(near)) if near else ""))
            continue
        if name == "PYTHON.EXECUTE" and not _python_allowed():
            errors.append("%s: raw Python is switched off. Turn on 'Allow raw Python' in the add-on preferences, or use commands." % where)
            continue
        params = op.get("params") if op.get("params") is not None else {}
        if not isinstance(params, dict):
            errors.append('%s: "params" must be an object.' % where)
            continue
        if not _has_refs(params):
            try:
                registry.validate(entry, params)
            except registry.CommandError as error:
                errors.append("%s: %s %s" % (where, entry["name"], error.message))
                continue
        plan.append({"id": oid, "command": entry["name"], "params": params,
                     "mutating": entry.get("mutating"), "destructive": entry.get("destructive")})
    return plan, errors, warnings


def _has_refs(value):
    if isinstance(value, str):
        return "${" in value
    if isinstance(value, list):
        return any(_has_refs(v) for v in value)
    if isinstance(value, dict):
        return any(_has_refs(v) for v in value.values())
    return False


# ---------------------------------------------------------------- paths
_KNOWN = {"desktop": "Desktop", "documents": "Personal", "pictures": "My Pictures", "videos": "My Video",
          "music": "My Music", "downloads": "{374DE290-123F-4565-9164-39C4925E467B}"}


def _known_folder(name):
    """Where Windows keeps Desktop, Documents... (often moved into OneDrive)."""
    import os
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            return os.path.expandvars(winreg.QueryValueEx(key, _KNOWN[name])[0])
    except Exception:  # noqa: BLE001 - not Windows, or not set
        return None


def expand_paths(value):
    """"~/Desktop/x.fbx" -> the real desktop; "%USERPROFILE%" expanded. A bare "~" (text) is left alone."""
    import os
    if isinstance(value, str):
        v = os.path.expandvars(value) if "%" in value else value
        m = re.match(r"^~[\\/]+([^\\/]*)(.*)$", v)
        if not m:
            return v
        base = (_known_folder(m.group(1).lower()) if m.group(1).lower() in _KNOWN else None) or os.path.join(os.path.expanduser("~"), m.group(1))
        return os.path.normpath(base + m.group(2)) if m.group(2) else base
    if isinstance(value, list):
        return [expand_paths(v) for v in value]
    if isinstance(value, dict):
        return {k: (v if k == "code" else expand_paths(v)) for k, v in value.items()}
    return value


# ---------------------------------------------------------------- running
def _lookup(results, ref):
    parts = ref.split(".")
    oid = parts.pop(0)
    if oid not in results:
        raise ValueError('"${%s}" refers to "%s", which has not run' % (ref, oid))
    value = results[oid]
    if parts and parts[0] == "data":
        parts.pop(0)
    for p in parts:
        if isinstance(value, list) and p.isdigit() and int(p) < len(value):
            value = value[int(p)]
        elif isinstance(value, dict) and p in value:
            value = value[p]
        else:
            raise ValueError('"${%s}": the result of "%s" has no "%s"' % (ref, oid, p))
    return value


def _substitute(value, results):
    if isinstance(value, str):
        whole = re.fullmatch(r"\$\{([A-Za-z0-9_.-]+)\}", value)
        if whole:
            return _lookup(results, whole.group(1))
        return re.sub(r"\$\{([A-Za-z0-9_.-]+)\}",
                      lambda m: (lambda v: json.dumps(v) if isinstance(v, (dict, list)) else str(v))(_lookup(results, m.group(1))), value)
    if isinstance(value, list):
        return [_substitute(v, results) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, results) for k, v in value.items()}
    return value


def run_plan(name, plan):
    """Run a checked plan on the main thread. Returns the result report (WILDFRAME_BLENDER_RESULT_V1)."""
    import bpy
    try:
        bpy.ops.ed.undo_push(message="Wildframe Forge AI job: %s" % (name or "job"))
    except Exception:  # noqa: BLE001 - no undo stack in background mode
        pass
    results, ops, failed = {}, [], None
    for p in plan:
        entry = {"id": p["id"], "command": p["command"]}
        if failed:
            entry.update(ok=False, skipped=True)
            ops.append(entry)
            continue
        try:
            params = expand_paths(_substitute(p["params"], results))
        except ValueError as error:
            entry.update(ok=False, code="BAD_REFERENCE", message=str(error))
            ops.append(entry)
            failed = entry
            continue
        r = registry.run(p["command"], params)
        data = r.get("data") or {}
        finish = data.pop("_background", None) if isinstance(data, dict) else None
        if r.get("ok") and callable(finish):
            try:
                more = finish()
                if isinstance(more, dict):
                    data.update(more)
            except Exception as error:  # noqa: BLE001
                r = registry.envelope(False, "BACKGROUND_FAILED", str(error), data)
        entry.update(ok=bool(r.get("ok")), code=r.get("code"), message=r.get("message", ""))
        if r.get("warnings"):
            entry["warnings"] = r["warnings"]
        entry["data"] = data
        if entry["ok"]:
            results[p["id"]] = data
        else:
            failed = entry
        ops.append(entry)
    report = {"schema": RESULT_SCHEMA, "name": name or "Blender job", "state": "failed" if failed else "succeeded", "operations": ops}
    if failed:
        kept = [o["id"] for o in ops if o.get("ok")]
        if kept:
            report["changesKept"] = kept
            report["resumeHint"] = ('Operations %s succeeded and were NOT undone. Fix "%s" and send a job with only the remaining steps.'
                                    % (", ".join(kept), failed["id"]))
        else:
            report["resumeHint"] = 'Fix "%s" and send the job again.' % failed["id"]
    return _fit(report)


# ---------------------------------------------------------------- reports
def _trim(value, items, chars):
    if isinstance(value, str):
        return value if len(value) <= chars else value[:chars] + "... (%d more characters)" % (len(value) - chars)
    if isinstance(value, (list, tuple)):
        out = [_trim(v, items, chars) for v in list(value)[:items]]
        if len(value) > items:
            out.append("... %d more" % (len(value) - items))
        return out
    if isinstance(value, dict):
        return {k: _trim(v, items, chars) for k, v in value.items()}
    return value


def _shorten(value, limit):
    text = json.dumps(value, default=str)
    if len(text) <= limit:
        return value
    for items in (30, 15, 8, 4, 2, 1):
        for chars in (400, 150, 60):
            t = _trim(value, items, chars)
            if len(json.dumps(t, default=str)) <= limit:
                return t
    return {"truncated": True, "preview": text[:limit] + "..."}


def _fit(report):
    with_data = [o for o in report["operations"] if "data" in o]
    originals = [o["data"] for o in with_data]
    per = max(1500, min(8000, (RESULT_BUDGET - 1500) // max(1, len(with_data))))
    while True:
        for o, orig in zip(with_data, originals):
            o["data"] = _shorten(orig, per)
        if len(json.dumps(report, default=str)) <= RESULT_BUDGET or per <= 100:
            return report
        per //= 2


def result_for_ai(report):
    return "Wildframe Forge result:\n```json\n" + json.dumps(report, indent=1, default=str) + "\n```\n"


def error_report(text, errors, warnings=None):
    lines = ["Wildframe Forge could not run the job. Nothing ran.", "", "Errors:"]
    lines += ["- " + e for e in errors]
    if warnings:
        lines += ["", "Warnings:"] + ["- " + w for w in warnings]
    job, _ = parse_job(text)
    commands = registry.all_commands()
    named = {}
    if isinstance(job, dict) and isinstance(job.get("operations"), list):
        for op in job["operations"]:
            if not isinstance(op, dict):
                continue
            name = str(op.get("command") or "").strip().upper()
            candidates = [name] if name in commands else difflib.get_close_matches(name, list(commands), n=3, cutoff=0.6)
            for c in candidates:
                named[c] = _param_text(commands[c]) or "(no parameters)"
    if named:
        lines += ["", "Parameters of the commands involved (* = required):"] + ["- %s: %s" % (k, v) for k, v in named.items()]
    lines += ["", "The job:", "```json", (text or "").strip()[:8000], "```"]
    return "\n".join(lines)
