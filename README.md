# Wildframe Forge Bridge for Blender

The free, open-source Blender add-on of **Wildframe Forge Bridge**. It lets AI assistants (Claude, ChatGPT, Codex,
Grok Build and others, through the Wildframe Forge connector) work in Blender, and moves models, materials and scenes
between Blender and Unreal Engine while both are open.

- About 60 commands and one-call recipes: objects, materials, modifiers, rendering, import/export.
- Send to Unreal / Receive from Unreal, with correct scale, axes and naming.
- AI Scripts panel in the 3D Viewport sidebar: paste a job from any chat AI, check it, run it as one undo step.
- Everything stays on your PC: the add-on listens on 127.0.0.1 only and every request needs a per-session token.

## Install

**With Wildframe Forge Bridge (Unreal + Blender):** download the zip (link below) into your Downloads folder, then
open the plugin's Setup page in Unreal and click **Install** on the add-on row. It installs it into Blender for you.

**With Wildframe Forge Bridge Complete:** nothing to do here. The Setup page in Unreal downloads the add-on from this
page and installs it (**Fix all**, or **Install** on the add-on row).

**Download:** [wildframe_forge_bridge-1.0.0.zip](dist/wildframe_forge_bridge-1.0.0.zip) (click the download button on
that page).

**By hand:**

1. Download the newest `wildframe_forge_bridge-<version>.zip` from the [dist](dist) folder (open the file, then
   **Download raw file**).
2. In Blender: **Edit > Preferences > Get Extensions**, open the menu at the top right, **Install from Disk...**,
   and pick the zip. Don't unzip it.
3. The **Wildframe Forge** tab appears in the 3D Viewport sidebar (press **N**).

Requires Blender 4.2 or newer (tested with Blender 5.2) on Windows.

## Where to get the rest

The Unreal Engine plugin, the AI connector and the Adobe panels are sold on Fab as **Wildframe Forge Bridge** and
**Wildframe Forge Bridge Complete**. Documentation: [docs/README.md](docs/README.md) (Adobe apps: [docs/Adobe.md](docs/Adobe.md)).
Videos: [youtube.com/@WildframeForge1](https://www.youtube.com/@WildframeForge1).

The [hub-tray](hub-tray) folder holds the Wildframe Forge Hub's optional tray icon program,
[WildframeForgeHub.exe](hub-tray/WildframeForgeHub.exe) (Unreal + Blender edition: download it into your Downloads
folder and the hub adds it; Complete: Setup downloads it). It is not part of the add-on and not covered by the GPL;
its source is next to it.

## Licence

The add-on's code (`wildframe_forge_bridge`) is licensed under the **GNU General Public License v3.0 or later** (see [LICENSE](LICENSE)), as
Blender requires for add-ons that use its Python API. You may use, change and share it under those terms.

The Wildframe Forge name and emblem (`wildframe_forge_bridge/icons/emblem.png`) are Wildframe Forge's own artwork and
are not covered by the GPL; please don't use them for other products.

## Support

wildframeforge@gmail.com
