# SPDX-License-Identifier: GPL-3.0-or-later
"""Sidebar panel (3D Viewport > N > Wildframe Forge) and operators."""

import bpy

from . import instances, prefs, registry, server

# The Wildframe Forge emblem in the panel headers (Blender add-ons can show their own icons, not colours).
_ICONS = {"coll": None}


def emblem_icon():
    """icon_value of the emblem, or 0 (no icon) when it cannot be loaded."""
    try:
        coll = _ICONS["coll"]
        if coll is None:
            import os
            import bpy.utils.previews
            coll = bpy.utils.previews.new()
            _ICONS["coll"] = coll  # kept even if loading fails, so it is not recreated on every redraw
            path = os.path.join(os.path.dirname(__file__), "icons", "emblem.png")
            if os.path.isfile(path):
                coll.load("emblem", path, "IMAGE")
        return coll["emblem"].icon_id if "emblem" in coll else 0
    except Exception:  # noqa: BLE001 - an icon is never worth an error
        return 0


def free_icons():
    try:
        if _ICONS["coll"] is not None:
            import bpy.utils.previews
            bpy.utils.previews.remove(_ICONS["coll"])
    except Exception:  # noqa: BLE001
        pass
    _ICONS["coll"] = None


def _report_result(op, result, success_text):
    if result.get("ok"):
        op.report({"INFO"}, result.get("message") or success_text)
        return {"FINISHED"}
    op.report({"ERROR"}, "%s: %s" % (result.get("code"), result.get("message")))
    return {"CANCELLED"}


class WILDFRAME_OT_start(bpy.types.Operator):
    bl_idname = "wildframe.start_bridge"
    bl_label = "Start Bridge"
    bl_description = "Start the local Wildframe Forge bridge so AI tools and Unreal can talk to Blender"

    def execute(self, context):
        try:
            port = server.start(prefs.get().port)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "Wildframe Forge Bridge listening on 127.0.0.1:%d" % port)
        return {"FINISHED"}


class WILDFRAME_OT_stop(bpy.types.Operator):
    bl_idname = "wildframe.stop_bridge"
    bl_label = "Stop Bridge"

    def execute(self, context):
        server.stop()
        return {"FINISHED"}


class WILDFRAME_OT_send_to_unreal(bpy.types.Operator):
    bl_idname = "wildframe.send_to_unreal"
    bl_label = "Send Selection to Unreal"
    bl_description = "Export the selected objects and import them into the open Unreal project"

    combine: bpy.props.BoolProperty(name="One asset", default=False)
    place_in_level: bpy.props.BoolProperty(name="Also place in level", default=False)
    as_landscape: bpy.props.BoolProperty(name="As Landscape", default=False,
                                         description="Send the selected terrain meshes as Unreal Landscapes")

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        p = prefs.get()
        result = registry.run("BRIDGE.SEND_TO_UNREAL", {
            "destination": p.default_destination, "format": p.default_format,
            "combine": self.combine, "place_in_level": self.place_in_level, "as_landscape": self.as_landscape})
        if not result.get("ok"):
            return _report_result(self, result, "")
        finish = result["data"].pop("_background", None)
        if callable(finish):
            import threading

            def work():
                try:
                    finish()
                    msg = ("INFO", "Sent to Unreal: %s" % ", ".join(i["name"] for i in result["data"]["items"]))
                except Exception as error:  # noqa: BLE001
                    msg = ("ERROR", "Unreal import failed: %s" % error)
                bpy.app.timers.register(lambda: _toast(*msg), first_interval=0.0)

            threading.Thread(target=work, daemon=True).start()
            self.report({"INFO"}, "Exported %d asset(s); importing in Unreal..." % len(result["data"]["items"]))
        return {"FINISHED"}


def _toast(level, text):
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    print("Wildframe Forge Bridge:", text)
    try:
        bpy.context.window_manager.popup_menu(lambda self, ctx: self.layout.label(text=text),
                                              title="Wildframe Forge Bridge", icon="INFO" if level == "INFO" else "ERROR")
    except Exception:  # noqa: BLE001
        pass
    return None


class WILDFRAME_OT_receive(bpy.types.Operator):
    bl_idname = "wildframe.receive_from_unreal"
    bl_label = "Import Latest from Unreal"
    bl_description = "Import the newest exchange package sent to Blender"

    def execute(self, context):
        return _report_result(self, registry.run("BRIDGE.RECEIVE", {}), "Imported from Unreal")


def setup_link(timeout=0.5):
    """The Setup page link from the Wildframe Forge Hub (it carries a key only local programs can get), or ""."""
    import json
    import urllib.request
    from . import exchange
    req = urllib.request.Request("http://127.0.0.1:%d/setup/link" % exchange.HUB_PORT, headers={"x-wfab-client": "app"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            url = json.loads(resp.read().decode("utf-8") or "{}").get("url") or ""
    except Exception:  # noqa: BLE001
        return ""
    return url if url.startswith("http://127.0.0.1:") and "/setup?key=" in url else ""


class WILDFRAME_OT_open_setup(bpy.types.Operator):
    bl_idname = "wildframe.open_setup"
    bl_label = "Setup..."
    bl_description = ("Open Wildframe Forge Setup in your browser: find Blender, install or update this add-on, "
                      "connect your AI apps (Claude, Codex, Grok...). Starts the Wildframe Forge Hub if needed")

    def execute(self, context):
        from . import exchange
        if not exchange.ensure_hub():
            self.report({"ERROR"}, "The Wildframe Forge Hub is not set up on this PC yet. Install Wildframe Forge Bridge, "
                                   "or open Unreal with the plugin once, then try again.")
            return {"CANCELLED"}
        state = {"tries": 0}

        def poll():
            url = setup_link()
            if url:
                import webbrowser
                webbrowser.open(url)
                return None
            state["tries"] += 1
            if state["tries"] > 40:  # about 10 s: the hub may be starting for the first time
                _toast("ERROR", "The Wildframe Forge Hub did not answer. Try again in a moment.")
                return None
            return 0.25

        bpy.app.timers.register(poll, first_interval=0.0)
        self.report({"INFO"}, "Opening Wildframe Forge Setup in your browser...")
        return {"FINISHED"}


class WILDFRAME_PT_panel(bpy.types.Panel):
    bl_label = "Wildframe Forge Bridge"
    bl_idname = "WILDFRAME_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Wildframe Forge"

    def draw_header(self, context):
        icon = emblem_icon()
        if icon:
            self.layout.label(text="", icon_value=icon)

    def draw(self, context):
        layout = self.layout
        running = server.is_running()
        box = layout.box()
        box.label(text=("AI bridge: port %d" % server._state["port"]) if running else "AI bridge: stopped",
                  icon="LINKED" if running else "UNLINKED")
        row = box.row(align=True)
        row.operator("wildframe.stop_bridge" if running else "wildframe.start_bridge")
        row.operator("wildframe.open_setup", text="Setup", icon="PREFERENCES")
        unreals = instances.list_instances("unreal")
        col = layout.column(align=True)
        col.label(text="Unreal: %s" % (("%d editor(s) open" % len(unreals)) if unreals else "not running"),
                  icon="CHECKMARK" if unreals else "ERROR")
        for rec in unreals[:3]:
            col.label(text="  " + (rec.get("document") or rec.get("endpoint") or "")[-48:])
        layout.separator()
        layout.operator("wildframe.send_to_unreal", icon="EXPORT")
        layout.operator("wildframe.send_to_unreal", text="Send as Landscape", icon="MESH_GRID").as_landscape = True
        layout.operator("wildframe.receive_from_unreal", icon="IMPORT")
        layout.label(text="Destination: %s" % prefs.get().default_destination)


# ---------------------------------------------------------------- AI Scripts
# For chat AIs that cannot connect (ChatGPT, Grok...) and for PCs that cannot run Blender and an AI app
# together: copy the primer, paste the AI's job, check, run, copy the result back. Same flow as Unreal's page.
JOB_TEXT = "Wildframe AI Job"
_AI = {"kind": "", "lines": [], "result": "", "error": ""}  # what the panel shows; not saved with the .blend


def _job_text():
    text = bpy.data.texts.get(JOB_TEXT)
    return text.as_string() if text else ""


def _wrap(text, width=58):
    import textwrap
    return textwrap.wrap(str(text), width) or [""]


def _set_view(kind, lines, result="", error=""):
    _AI.update(kind=kind, lines=lines, result=result, error=error)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


class WILDFRAME_OT_ai_copy_primer(bpy.types.Operator):
    bl_idname = "wildframe.ai_copy_primer"
    bl_label = "Copy primer for AI"
    bl_description = "Copy instructions and the full command list for ChatGPT, Grok or any chat AI. Paste it into a new chat first"

    def execute(self, context):
        from . import aiscripts
        text = aiscripts.build_primer()
        context.window_manager.clipboard = text
        self.report({"INFO"}, "Primer copied (%d characters): paste it into a new chat, then ask for what you want." % len(text))
        return {"FINISHED"}


class WILDFRAME_OT_ai_paste_job(bpy.types.Operator):
    bl_idname = "wildframe.ai_paste_job"
    bl_label = "Paste job from clipboard"
    bl_description = "Put the AI's reply (or just its json block) into the Text Editor block '%s', then check it" % JOB_TEXT

    def execute(self, context):
        clip = context.window_manager.clipboard or ""
        if not clip.strip():
            self.report({"WARNING"}, "The clipboard is empty: copy your AI's reply first.")
            return {"CANCELLED"}
        text = bpy.data.texts.get(JOB_TEXT) or bpy.data.texts.new(JOB_TEXT)
        text.clear()
        text.write(clip)
        _check(self)  # show the check right away (a rejected job is reported, not raised)
        return {"FINISHED"}


def _check(op):
    """Check the job in the text block and show the plan or the problems. Returns True when it can run."""
    from . import aiscripts
    source = _job_text()
    job, error = aiscripts.parse_job(source)
    plan, errors, warnings = aiscripts.check_job(job) if job else ([], [error], [])
    if errors:
        _set_view("rejected", ["The job was not run."] + errors + warnings, error=aiscripts.error_report(source, errors, warnings))
        op.report({"WARNING"}, "The job has problems: click 'Copy error for AI' and paste it to your AI.")
        return False
    lines = ["Looks good%s: %d operation(s). Nothing ran yet." % ((": " + job["name"]) if job.get("name") else "", len(plan))]
    lines += ["%s  %s%s" % (p["id"], p["command"], "  (DESTRUCTIVE)" if p["destructive"] else "") for p in plan]
    _set_view("plan", lines + warnings)
    op.report({"INFO"}, "Job checked: %d operation(s). Click Run to start." % len(plan))
    return True


class WILDFRAME_OT_ai_check(bpy.types.Operator):
    bl_idname = "wildframe.ai_check"
    bl_label = "Check"
    bl_description = "Show what the job will do without running anything"

    def execute(self, context):
        return {"FINISHED"} if _check(self) else {"CANCELLED"}


class WILDFRAME_OT_ai_run(bpy.types.Operator):
    bl_idname = "wildframe.ai_run"
    bl_label = "Run"
    bl_description = "Check and run the job. The whole job is one undo step (Ctrl+Z takes it back)"

    def execute(self, context):
        from . import aiscripts
        source = _job_text()
        job, error = aiscripts.parse_job(source)
        plan, errors, warnings = aiscripts.check_job(job) if job else ([], [error], [])
        if errors:
            _set_view("rejected", ["The job was not run."] + errors + warnings, error=aiscripts.error_report(source, errors, warnings))
            self.report({"WARNING"}, "The job has problems: click 'Copy error for AI' and paste it to your AI.")
            return {"CANCELLED"}
        report = aiscripts.run_plan(job.get("name"), plan)
        ok = report["state"] == "succeeded"
        lines = ["Done: %s" % report["name"] if ok else "Stopped: an operation failed. " + report.get("resumeHint", "")]
        for o in report["operations"]:
            mark = "skipped" if o.get("skipped") else ("ok" if o.get("ok") else "FAILED")
            lines.append("%s  %s  %s" % (mark, o["id"], o["command"]))
            if not o.get("ok") and not o.get("skipped"):
                lines.append("    %s: %s" % (o.get("code"), o.get("message")))
        _set_view("result", lines, result=aiscripts.result_for_ai(report))
        self.report({"INFO"} if ok else {"WARNING"}, "Job %s. Click 'Copy result for AI' and paste it to your AI." % report["state"])
        return {"FINISHED"}


class WILDFRAME_OT_ai_copy_result(bpy.types.Operator):
    bl_idname = "wildframe.ai_copy_result"
    bl_label = "Copy result for AI"

    @classmethod
    def poll(cls, context):
        return bool(_AI["result"])

    def execute(self, context):
        context.window_manager.clipboard = _AI["result"]
        self.report({"INFO"}, "Result copied: paste it to your AI.")
        return {"FINISHED"}


class WILDFRAME_OT_ai_copy_error(bpy.types.Operator):
    bl_idname = "wildframe.ai_copy_error"
    bl_label = "Copy error for AI"

    @classmethod
    def poll(cls, context):
        return bool(_AI["error"])

    def execute(self, context):
        context.window_manager.clipboard = _AI["error"]
        self.report({"INFO"}, "Error report copied: paste it to your AI so it can fix the job.")
        return {"FINISHED"}


class WILDFRAME_OT_ai_clear(bpy.types.Operator):
    bl_idname = "wildframe.ai_clear"
    bl_label = "Clear"

    def execute(self, context):
        text = bpy.data.texts.get(JOB_TEXT)
        if text:
            text.clear()
        _set_view("", [])
        return {"FINISHED"}


class WILDFRAME_PT_ai_scripts(bpy.types.Panel):
    bl_label = "AI Scripts (any chat AI)"
    bl_idname = "WILDFRAME_PT_ai_scripts"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Wildframe Forge"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="1. Paste the primer into ChatGPT, Grok...", icon="INFO")
        col.operator("wildframe.ai_copy_primer", icon="COPYDOWN")
        layout.separator()
        col = layout.column(align=True)
        col.label(text="2. Copy the AI's reply, then:")
        col.operator("wildframe.ai_paste_job", icon="PASTEDOWN")
        has_job = bool(_job_text().strip())
        row = col.row(align=True)
        row.enabled = has_job
        row.operator("wildframe.ai_check", icon="VIEWZOOM")
        row.operator("wildframe.ai_run", icon="PLAY")
        row.operator("wildframe.ai_clear", text="", icon="X")
        if has_job:
            col.label(text="Review it in Text Editor: " + JOB_TEXT, icon="TEXT")
        if _AI["lines"]:
            box = layout.box()
            icon = {"rejected": "ERROR", "plan": "CHECKMARK", "result": "CHECKMARK"}.get(_AI["kind"], "INFO")
            if _AI["kind"] == "result" and _AI["lines"][0].startswith("Stopped"):
                icon = "ERROR"
            for i, line in enumerate(_AI["lines"][:24]):
                for j, part in enumerate(_wrap(line)):
                    box.label(text=part, icon=(icon if i == 0 and j == 0 else "NONE"))
            if len(_AI["lines"]) > 24:
                box.label(text="... %d more lines (in the copied report)" % (len(_AI["lines"]) - 24))
        layout.separator()
        col = layout.column(align=True)
        col.label(text="3. Send the outcome back to your AI:")
        row = col.row(align=True)
        row.operator("wildframe.ai_copy_result", icon="COPYDOWN")
        red = row.row(align=True)
        red.alert = bool(_AI["error"])  # red when there is an error report to send
        red.operator("wildframe.ai_copy_error", icon="ERROR")


CLASSES = (WILDFRAME_OT_start, WILDFRAME_OT_stop, WILDFRAME_OT_open_setup, WILDFRAME_OT_send_to_unreal, WILDFRAME_OT_receive, WILDFRAME_PT_panel,
           WILDFRAME_OT_ai_copy_primer, WILDFRAME_OT_ai_paste_job, WILDFRAME_OT_ai_check, WILDFRAME_OT_ai_run,
           WILDFRAME_OT_ai_copy_result, WILDFRAME_OT_ai_copy_error, WILDFRAME_OT_ai_clear, WILDFRAME_PT_ai_scripts)
