# Wildframe Forge Bridge for Blender

The free, open-source Blender add-on of **Wildframe Forge Bridge**. It lets AI assistants (Claude, ChatGPT, Codex,
Grok Build and others, through the Wildframe Forge connector) work in Blender, and moves models, materials and scenes
between Blender and Unreal Engine while both are open.

- About 60 commands and one-call recipes: objects, materials, modifiers, rendering, import/export.
- Send to Unreal / Receive from Unreal, with correct scale, axes and naming.
- AI Scripts panel in the 3D Viewport sidebar: paste a job from any chat AI, check it, run it as one undo step.
- Everything stays on your PC: the add-on listens on 127.0.0.1 only and every request needs a per-session token.

## Install

**With Wildframe Forge Bridge (Unreal plugin or Wildframe Forge Setup):** you don't need to do anything here. Open the
Setup page and click **Fix all** (or **Install** on the Blender row). It downloads the add-on from this page
and installs it into Blender for you.

**By hand:**

1. Download the newest `wildframe_forge_bridge-<version>.zip` from the [dist](dist) folder (open the file, then
   **Download raw file**).
2. In Blender: **Edit > Preferences > Get Extensions**, open the menu at the top right, **Install from Disk...**,
   and pick the zip. Don't unzip it.
3. The **Wildframe Forge** tab appears in the 3D Viewport sidebar (press **N**).

Requires Blender 4.2 or newer (tested with Blender 5.2) on Windows.

## Where to get the rest

The Unreal Engine plugin, the AI connector and the Adobe panels are sold on Fab as **Wildframe Forge Bridge** and
**Wildframe Forge Bridge Complete**. Videos: [youtube.com/@WildframeForge1](https://www.youtube.com/@WildframeForge1).

## Licence

The add-on's code is licensed under the **GNU General Public License v3.0 or later** (see [LICENSE](LICENSE)), as
Blender requires for add-ons that use its Python API. You may use, change and share it under those terms.

The Wildframe Forge name and emblem (`wildframe_forge_bridge/icons/emblem.png`) are Wildframe Forge's own artwork and
are not covered by the GPL; please don't use them for other products.

## Support

wildframeforge@gmail.com
