# SPDX-License-Identifier: GPL-3.0-or-later
"""Command modules. Importing them registers their commands (see registry.command)."""

import importlib

MODULES = ("core", "objects", "materials", "io", "render", "bridge", "scene", "recipes")


def load():
    from .. import registry
    modules = [importlib.import_module("%s.%s" % (__name__, name)) for name in MODULES]
    registry.all_commands().clear()
    for module in modules:
        importlib.reload(module)  # (re)run the @command decorators exactly once each
    return len(registry.all_commands())
