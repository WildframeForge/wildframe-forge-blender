# Wildframe Forge Bridge

Wildframe Forge Bridge lets any AI assistant (cloud or local) or your own script control the
Unreal Editor and Blender through structured commands. Both programs can run at the same time and pass
models, materials and scenes back and forth.

- **Unreal plugin**: more than 300 typed commands, covering:
  - assets, actors, levels, materials, landscape, PCG, foliage and water;
  - Sequencer, cameras, animation, MetaHuman and Control Rig;
  - rendering, validation and Python.
- **Blender add-on** (free and open source; see *Dependencies*): 60 commands covering
  objects, mesh, modifiers, materials, lights, cameras, collections, import/export, rendering, keyframes and
  viewport capture.
- **Live Unreal ↔ Blender transfer**:
  - Unreal → Blender: send selected actors or assets to Blender with one command.
  - Blender → Unreal: send the selected objects to Unreal from the Blender sidebar.
  - The bridge converts units (m ↔ cm) and handedness for you.
- **MCP connector**: lets AI desktop apps that support the Model Context Protocol (MCP) start, discover
  and drive both programs.

Everything runs locally. Nothing listens outside `127.0.0.1`, and every request needs a per-session
token.

### Two editions

| | Wildframe Forge Bridge | Wildframe Forge Bridge Complete |
|---|---|---|
| Unreal Engine plugin | ✓ | ✓ |
| Blender add-on, live Unreal ↔ Blender transfers | ✓ | ✓ |
| Wildframe Forge Hub (tray icon, delivery mailbox) | ✓ | ✓ |
| Adobe apps: After Effects, Premiere Pro, Photoshop, Illustrator, Animate | – | ✓ |

Both editions are built from the same code; the Complete edition adds the Adobe panels in
`Resources/Adobe` and the `adobe_*` connector tools.

## Requirements

- Windows 10/11, 64-bit.
- Unreal Engine 5.8. The Setup page in Unreal installs everything else; afterwards Blender (and, in the Complete
  edition, the Adobe apps) also work with your AI app while Unreal is closed.
- Optional: Blender 4.2 or newer (tested on 5.2) for the Blender bridge.
- Optional: an AI app. Claude Desktop, Claude Code, Codex (CLI, IDE extension, ChatGPT desktop), Grok Build (xAI's
  terminal app) and any MCP-capable app can connect (Setup has a Connect button for each). In Grok Build, type `/mcp`
  once and enable Wildframe Forge Bridge (wildframe-forge-bridge) if it shows as disabled; it also finds the bridge on its own
  when Claude Code is already connected. To install Grok Build (https://grok.com/build), paste `irm https://x.ai/cli/install.ps1 | iex` into
  PowerShell (Setup's Grok Build row copies it for you), then run `grok` and sign in. Any chat AI (ChatGPT, Grok, Gemini, free plans included) works through the AI
  Scripts pages: in Unreal for Unreal, in Blender's sidebar (N > Wildframe Forge > AI Scripts) for Blender, and the
  hub's page for the Adobe apps (Complete). Handy on a PC that cannot run Blender or Unreal and an AI app together.
- The dependencies below. The package itself contains no programs or installers.

## Dependencies

| Dependency | Needed for | Where to get it |
|---|---|---|
| **Node.js** 18 or newer (LTS recommended, free) | the AI connector and the Wildframe Forge Hub | https://nodejs.org/en/download: download the **Windows Installer (.msi)** and run it |
| **Wildframe Forge add-on for Blender** (free, open source) | the Blender side | https://github.com/WildframeForge/wildframe-forge-blender/blob/main/dist/wildframe_forge_bridge-1.0.0.zip: click the download button |
| Tray icon `WildframeForgeHub.exe` (optional) | the hub's icon by the clock (deliveries menu, Setup, Start with Windows) | https://github.com/WildframeForge/wildframe-forge-blender/blob/main/hub-tray/WildframeForgeHub.exe |
| Blender 4.2 or newer (optional) | the Blender side | https://www.blender.org/download/ |

**Wildframe Forge Bridge (Unreal + Blender)** never downloads anything itself. You install the dependencies from the
pages above; the Setup page has a button for each page and finds what you installed:
- **Node.js**: run the installer, then come back to Unreal. The **Connector files** row turns green by itself within a
  few seconds (installed somewhere unusual? click **Choose node.exe...**). Setup uses a copy of it in
  `%LOCALAPPDATA%\WildframeForge\Runtime\node`, so updating or removing Node.js later does not break anything.
- **Blender add-on**: download the zip (it goes to your Downloads folder), then click **Install** on the add-on row.
  Setup installs it with Blender's own installer. Saved it somewhere else? Click **Install from file...**. You can
  also install it in Blender yourself: **Edit > Preferences > Get Extensions > Install from Disk**.
- **Tray icon** (optional): download it into your Downloads folder; the hub adds it within a minute (only the exact
  file published on that page, checked by its fingerprint). Everything works without it.

**Wildframe Forge Bridge Complete** (adds the Adobe apps): the Setup page downloads Node.js (the official build from
nodejs.org), the tray icon and the Blender add-on for you, and checks each file against its fingerprint. This needs an
internet connection the first time.

## Install (about 2 minutes)

1. Install **Wildframe Forge Bridge** from Fab and enable it in **Edit ▸ Plugins**. Restart the editor.
2. The **Setup** page opens on its own the first time. You can always reopen it from
   **Window ▸ Wildframe Forge ▸ Wildframe Forge Setup** or with the console command `Forge.Setup`.
   Want the panel every time Unreal starts? On the Setup page, choose **Open minimized** (it waits
   on the taskbar, out of your way) or **Open in front**. The same switches are in
   **Edit ▸ Editor Preferences ▸ Plugins ▸ Wildframe Forge Bridge ▸ Startup** and apply to all your projects.
3. Follow the lights. Green means ready. Every other row has a button that fixes it:
   - **Blender**: found automatically on any drive. If it isn't, click **Browse…** once and pick
     `blender.exe`; it is remembered.
   - **Connector files** (Unreal + Blender edition): install Node.js first (see *Dependencies*: **Get Node.js** opens
     its page). The row turns green by itself.
   - **Wildframe Forge add-on in Blender**: click **Install**; Blender's own installer adds and enables it. Unreal +
     Blender edition: click **Get the add-on** and download the zip first. Complete edition: Setup downloads it (internet
     needed the first time). (The AI can also do it: if
     it opens Blender and the add-on is missing, it installs it first.)
   - **AI apps**: click **Connect all AI apps**, or **Connect** on one app.
     - Claude Desktop opens its install window; click **Install** there.
       (Don't use Claude's *Connectors ▸ Add custom connector*; that is for online servers. Wildframe Forge is a
       desktop extension that Setup builds on your PC: `%LOCALAPPDATA%\WildframeForge\Runtime\packages\wildframe-forge-bridge.mcpb`.)
     - Claude Code is configured for you. Restart your Claude Code session afterwards.
     - Codex gets Wildframe Forge Bridge as a Codex plugin. Quit and reopen Codex once; it then appears in a
       chat's plugin list (and its tools work in every chat).
     - For other apps, **Copy setup** gives a ready-made MCP entry to paste.
   - **Test**: start Blender, then click **Run test**. A cube goes Unreal → Blender → Unreal and is then
     removed.
4. Done. If something breaks later (Blender moved, add-on removed, plugin updated), the editor shows a
   notice at startup and the Setup page offers **Repair** buttons and **Fix all**.

**Copy diagnostic report** puts a summary of your setup on the clipboard (no tokens or passwords) for
support.

**Raw Python is off by default.** AI apps can use every Wildframe Forge command without it. Turn on **Allow AI to
run raw Python** on the Setup page only if you want the AI to run its own Python code. Scripts you review
and run from the AI Scripts page are not affected.

## Using Blender or the Adobe apps while Unreal is closed

After the Setup page in Unreal has run once, the Wildframe Forge Hub and your AI connection work on their own:
Blender (and, in the Complete edition, the Adobe apps) start the hub when they need it. Open the hub's Setup page
any time from its tray icon (**Setup...**), the **Setup** button in Blender's Wildframe Forge sidebar, or the
**Setup** button in any Adobe panel.

## How AI tools talk to Unreal

| | |
|---|---|
| Endpoint | `http://127.0.0.1:19847/wildframe/v1`. The port can be changed in Project Settings. |
| Token | `<Project>/Saved/WildframeForgeBridge/bridge-token.txt`. It is created on first start. Treat it as a password. |
| Headers | `Authorization: Bearer <token>`, `X-Wildframe-Request-Id: <unique id>` |
| Discover | `GET /capabilities`, `POST /commands` with `COMMAND.SEARCH` / `COMMAND.DESCRIBE` |
| Run | `POST /commands {"command": "ACTORS.SPAWN_MESH", "params": {...}}`. This returns a job. Poll it with `GET /jobs/status?jobId=`. |

Every command has a JSON schema. Bad parameters are rejected before anything changes. Commands that
change the project are wrapped in an editor transaction, so **Ctrl+Z** works for them. A job's steps share one
transaction: if a step fails, the steps it already did are undone automatically and the level is back the way it was
(the job record shows `rollbackPerformed: true`; set `execution.rollbackOnFailure: false` to keep a partial result).
Lighting, fog, campfire and remove-effects recipes join that transaction too. Steps Unreal cannot undo (saving a map,
rendering, raw Python, sending to Blender) stop the automatic undo for that job; press Ctrl+Z for the rest. The AI can also undo a finished job with `unreal_job {rollback: true}`. Destructive commands
need `confirm: true`.

### Examples

```json
{"command": "ASSETS.IMPORT", "params": {"files": ["C:/models/rock.fbx"], "destination": "/Game/Rocks"}}
{"command": "MATERIALS.CREATE_PBR", "params": {"path": "/Game/Rocks/MI_Rock", "textures": {"baseColor": "C:/tex/rock_d.png"}}}
{"command": "ACTORS.SPAWN_MESH", "params": {"mesh": "/Game/Rocks/rock", "location": [0, 0, 0], "material": "/Game/Rocks/MI_Rock"}}
{"command": "BRIDGE.SEND_TO_BLENDER", "params": {"selectedActors": true}}
{"command": "BRIDGE.BLENDER_COMMAND", "params": {"command": "MODIFIERS.ADD", "params": {"object": "rock", "type": "DECIMATE"}}}
```

## What the AI sees: SCENE.SNAPSHOT and Matrix View

`SCENE.SNAPSHOT` gives the AI the viewport as data, without a screenshot. It is read-only. It returns:

- **Camera:** location, rotation, field of view and viewport size.
- **Editor state:** level, active editor modes, open asset editors, selection, and the Sequencer sequence and frame.
- **Each visible actor, nearest first:** class, transform, bounds, distance from the camera, 2D screen box,
  % of the frame, occlusion (`visible` / `partial` / `hidden`, and what blocks it), materials and the current
  animation and frame.

Options:

| Option | What it does |
|---|---|
| `maxActors` | Most actors returned. Default 100. |
| `grid: true` | Adds a coarse object-ID grid (64×36 ray casts, or `gridColumns` / `gridRows`) that maps screen cells to actor ids. |
| `annotate: true` | Also saves a PNG of the viewport with the boxes and labels drawn from this snapshot. |
| `skipEnvironment`, `ignoreClasses`, `minScreenPercent`, `includeOffscreen` | Narrow or widen the list. |

```json
{"command": "SCENE.SNAPSHOT", "params": {"maxActors": 40, "grid": true}}
```

**Matrix View** shows the same data in the level viewport: a green Matrix look with glowing edges and code
rain, plus boxes and labels on every visible actor.

- **Selected actors** are brighter.
- **Hidden actors** (blocked by something) are dim and dashed, and tagged `[HIDDEN]`.
- A corner panel shows the camera, level, actor counts and Sequencer frame.

Turn it on with any of:

- the **Matrix View** toolbar button
- **Window > Matrix View**
- **Ctrl+Shift+M**
- the console command `Forge.MatrixView`
- `VIEW.MATRIX_VIEW {"enabled": true}`

Nothing in the level changes. The look is a viewport post-process and the labels are an overlay, so turning
it off leaves no actors, materials or settings behind. Settings are under **Project Settings > Plugins >
Wildframe Forge Bridge > Matrix View**: look on/off, code rain, label detail (Minimal / Normal / Full), max labels,
colour, font size and update rate.

Matrix View limits its own cost to about 1 ms per frame. On very large levels it updates the labels less
often, and it turns itself off with a notice if it still can't keep up. The first time it is used, Unreal
compiles its shaders for a few seconds. The labels are not part of Movie Render Queue output. To get them in
a render, record the editor viewport.

For screen recordings, `EDITOR.VIEWPORT_LAYOUT {"immersive": true, "closeTabs": ["contentBrowser", "sequencer"]}`
makes the level viewport fill the editor window and closes the tabs that cover it. `{"immersive": false}` brings
the normal layout back. Asset editors with unsaved changes ask before they close.

Blender has a matching `SCENE.SNAPSHOT` with the same JSON layout. Lengths are in centimetres; positions are
in Blender's own axes, which the `axes` field states.

## Recipes: whole tasks in one call (saves AI usage)

Recipes are ready-made commands (`RECIPE.*`) that do a complete task in one call and answer in a line or
two. The searching and editing happen on your PC, so the AI uses far less of your plan's usage. Asking for
"make a daytime copy of the burning village" becomes one `RECIPE.MAP_VARIANT` call instead of about twenty.
AI apps find them on their own; you never need to type them.

| Unreal | What it does |
|---|---|
| `RECIPE.SCENE_SUMMARY` | Short overview of the open level (instead of listing thousands of actors) |
| `RECIPE.TIME_OF_DAY` | dawn, morning, noon, afternoon, golden hour, dusk, night or overcast |
| `RECIPE.REMOVE_EFFECTS` | Removes fire, smoke or embers and the glow lights around them (props stay) |
| `RECIPE.FOG` | Fog from clear to thick |
| `RECIPE.CAMPFIRE` | Stones, logs, flames and a flickering warm light, next to an actor or at a spot |
| `RECIPE.MAP_VARIANT` | Copies a map and changes its mood (the original is never touched) |
| `RECIPE.LEVEL_HEALTH` | Finds common level problems |
| `RECIPE.CAPTURE_VIEWS` | Screenshots from several angles |

| Blender | What it does |
|---|---|
| `RECIPE.SCENE_SUMMARY` | Short overview of the scene |
| `RECIPE.CLEAN_MESH` | Fixes messy AI/scan meshes (duplicates, loose bits, normals, face budget) |
| `RECIPE.PREP_FOR_UNREAL` | Applies transforms, origin at the base, real-world height, SM_ prefix |
| `RECIPE.STUDIO_LIGHTS` | Three-point, soft or dramatic lighting around objects |
| `RECIPE.PREVIEW_RENDER` | Quick preview image of objects |

Every recipe can be undone (Ctrl+Z), and most have a `dryRun` option that only reports what would change.

## Wildframe Forge Hub and the delivery mailbox

The **Wildframe Forge Hub** is a small background program with an icon by the clock. It starts by itself
when an AI app, Blender, Unreal or an Adobe app connects, links them, and closes itself 10 minutes after
the last app closes (or stays on if you tick **Keep running** in its menu).

The hub, its tray icon and the AI apps' connector run from a copy in `%LOCALAPPDATA%\WildframeForge\Runtime`, not
from the plugin folder, so the Epic Games Launcher can update or remove the plugin while they run. The copy is
refreshed when Unreal starts and whenever the hub starts after a plugin update; the AI apps keep the same
connection and pick up the new version in their next session.

**Delivery mailbox (for PCs that can't run everything at once):** if you send something to an app that is
closed (for example Unreal → Blender while Blender is closed), the package is kept as *waiting*. Close
Unreal, open Blender, and Blender imports it a few seconds after it starts. Nothing is lost if an app or
the hub crashes: packages are files in `%LOCALAPPDATA%\WildframeForge\Exchange`, and each part restarts the other.
A package sent to Unreal is addressed to the project Unreal had open last (or the one you name), and only
that project imports it automatically; other projects list it as waiting for its own project. With several
Unreal editors open at once, "last" means the editor that most recently started or reported in.

**Crash recovery:** if Unreal or Blender crashes, the hub opens the same project or .blend again after
about 15 seconds and shows a notice. It never reopens an app you closed yourself (a normal close tells the
hub), and it skips it when the app crashed within a minute of starting, crashed again within 10 minutes of
being reopened, had no saved file, or ended without writing a crash report (for example when it was ended
from Task Manager). Background processes (Movie Render Queue renders in a new process, `blender -b`,
unattended editor runs) are ignored. Turn it off with **Reopen Unreal and Blender after a crash** in the tray menu.

| Package state | What happens |
|---|---|
| waiting | Imported automatically when the receiving app opens (turn off **Import deliveries automatically** in the tray menu to import by hand). Kept even when the hub closes. |
| imported | Kept until the hub closes, in case you need to send it again, then deleted. |
| failed | Kept so you can **Retry** it from the tray menu; the reason is shown there. |

Packages nobody collected for 7 days are removed, and the folder is capped at 20 GB. The tray menu shows
the connected apps and the deliveries, opens the exchange folder, and can delete packages. If Unreal or
Blender crashes, the tray tells you and offers to open the project again. The AI can see and
manage the mailbox with the `hub_status` and `hub_deliveries` tools.

## Adobe apps (Complete edition)

On the Setup page, **Adobe apps ▸ Install** adds a Wildframe Forge Bridge panel to After Effects, Premiere
Pro, Illustrator and Animate (CEP) and installs the Photoshop and Premiere UXP plugins with Adobe's own
installer. After that the bridge starts by itself in the background whenever one of these apps opens, and
the AI can open the apps itself (`adobe_open_app`), so you don't need to keep the panel open. The panel
(**Window ▸ Extensions ▸ Wildframe Forge Bridge**; Photoshop: **Plugins ▸ Wildframe Forge Bridge**) shows the
connection status and log: "Connected (background)" is the normal state. In After Effects also tick **Edit ▸ Preferences ▸ Scripting & Expressions ▸ Allow
Scripts to Write Files and Access Network**.

The AI uses `adobe_status`, `adobe_find_commands`, `adobe_get_state` and `adobe_run_command` (After
Effects 89 commands, Premiere 67 + UXP 30, Photoshop 47, Illustrator 35, Animate 30), plus `recipe_*`
commands for whole tasks. Details: [Adobe.md](Adobe.md) (in the plugin: `Resources/Adobe/README-Adobe.md`).

## Several AI apps at the same time

Claude Desktop, Claude Code, Codex, Grok Build and other AI apps (or several chats) can use the same Unreal
editor, Blender and Adobe apps at once. Their commands take turns in a fair queue per app; an AI that would
have to wait too long gets a clear "busy, nothing was run, try again" answer. A retried command never runs
twice, undo and rollback only take back that AI's own work, and an app is not closed while another AI is
working in it unless you ask for that. For a multi-step edit in an Adobe app, an AI can reserve the app for a
few minutes (`adobe_reserve`) so another AI's commands can't change the open document in between.

## Unreal ↔ Blender

Each program writes a small record to `%LOCALAPPDATA%\WildframeForge\Instances` while it runs. Through these
records Unreal finds Blender and Blender finds Unreal, with no setup.

Files travel through `%LOCALAPPDATA%\WildframeForge\Exchange` as packages. Each package is a folder with a
`package.json` and FBX/glTF files.

| From | Command | Result |
|---|---|---|
| Unreal | `BRIDGE.SEND_TO_BLENDER` | Exports the assets or actors and imports them into the running Blender at matching positions. |
| Blender | `BRIDGE.SEND_TO_UNREAL`, or the **Send to Unreal** button | Exports each selected object and imports it into `/Game/FromBlender`, and can place it in the level. |
| Either | `BRIDGE.RECEIVE` | Imports the newest package addressed to this program. |
| Either | (receiving app closed) | The package waits in the delivery mailbox and is imported when that app opens. |
| Either | `BRIDGE.STATUS` | Lists the running Unreal and Blender sessions and the recent packages. |

Names: Blender's duplicate suffixes are removed on the way to Unreal (`Rock.001` arrives as `Rock`, and
`M_Stone.002` as `M_Stone`) unless another object or material already uses the clean name. Pass
`keep_duplicate_suffix: true` to `BRIDGE.SEND_TO_UNREAL` to keep them. A name sent again after this change
re-uses the asset that an earlier transfer created under the old name.

Coordinates: Blender uses metres and is right-handed. Unreal uses centimetres and is left-handed.
`unreal = (x·100, −y·100, z·100)`.

### What transfers

Every row below was sent both ways between Unreal 5.8 and Blender 5.2 and checked by measurement.

| Content | Blender → Unreal | Unreal → Blender | Notes |
|---|---|---|---|
| Static meshes | ✓ | ✓ | Positions, rotations and scale are kept. Sending again updates the same asset and actor. |
| Parent/child hierarchies | ✓ actors are attached | ✓ objects are parented | Each object becomes its own asset. |
| Blueprint actors with several meshes | n/a | ✓ | One object per mesh component, grouped under an empty. |
| Instanced meshes (ISM/HISM, foliage, PCG) | n/a | ✓ linked duplicates | Up to `maxInstances` (5000 by default). |
| Custom collision (`UCX_`, `UBX_`, `USP_`, `UCP_`) | ✓ | — | Name collision children `UCX_<Mesh>_00` and so on. |
| LODs (`Name_LOD0`, `Name_LOD1` …) | ✓ one mesh with LODs | LOD0 only | |
| Vertex colours, multiple UV maps | ✓ | ✓ | |
| Text, curves, surfaces, metaballs | ✓ converted to mesh | n/a | |
| Unicode and unusual names | ✓ made Unreal-safe | ✓ | |
| Materials (PBR) | ✓ | ✓ | Base colour, roughness, metallic, normal, AO, emission and opacity, including texture tiling, alpha cutout, glass and packed ORM/MRA textures. Normal-map green is flipped (OpenGL ↔ DirectX). |
| Procedural materials | ✓ baked to textures with Cycles | ✓ baked with Unreal's glTF baker | `bake_procedural` / `bakeMaterials`; `bake_size` sets the resolution. |
| Skeletal meshes and rigs | ✓ | ✓ | A rig that came from Unreal goes back onto its original Skeleton, with every bone intact. |
| Animations | ✓ | ✓ | Same frame count and fps. Within 0.01 cm on the UE Mannequin. Root motion is kept. |
| Shape keys / morph targets | ✓ | ✓ | |
| Lights (sun, point, spot, area/rect) | ✓ | ✓ | Brightness converted with 683 lm/W, so a round trip is exact. |
| Cameras | ✓ | ✓ | Focal length, sensor, focus distance, f-stop, orthographic. |
| Terrain ↔ Landscape | ✓ **Send as Landscape** | ✓ | Heights only, within 1 cm. Blender terrain is sampled from above onto a grid Unreal accepts (63-quad components). Landscapes come back as a grid mesh (decimated above `landscape_max_size`). |
| glTF/GLB instead of FBX | ✓ | ✓ | `format: "glb"`. |

### Known limitations

These were investigated and are not supported. The reasons are given so you know what to expect.

- **Bones that no mesh uses (for example the Mannequin's `weapon_r` or IK bones), in animations sent from Blender.**
  Unreal's FBX importer keeps only bones that appear in the skeleton's preview mesh, so keys on such bones are
  dropped. Animations sent from Unreal to Blender keep every bone.
- **Landscape paint layers, landscape materials, splines and grass.** Only heights travel. Blender texture paint is
  not an Unreal weight layer. Assign a landscape material in Unreal after sending.
- **Overhangs, caves and holes in terrain.** A Landscape is a single height field. Points with no surface are filled
  from the nearest edge, and you get a warning.
- **Opacity that comes from a procedural graph inside an Unreal material.** The baker writes base colour, roughness,
  metallic, normal and emission. Opacity driven by a texture or a constant does transfer.
- **Physical light units beyond intensity.** IES profiles, light functions, Lumen-specific settings and Blender
  light nodes have no counterpart in the other program.
- **Geometry Nodes, modifiers and Unreal construction scripts** travel as their evaluated result (the final mesh),
  not as editable graphs.
- **Nanite meshes from Unreal** are exported with their fallback/source mesh. Use `nanite: true` when sending to
  Unreal to switch Nanite on.

## Safety

- **Network**: the bridge listens on loopback only.
- **Token**: requests are rejected without the token. Tokens are compared in constant time.
- **Browsers**: requests from web browsers (any `Origin` header) are refused, so a web page cannot drive
  your editor.
- **Request size**: request bodies are capped at 32 MB.
- **Python**:
  - Raw Python is marked destructive and can be disabled in settings.
  - In Blender it is **off** by default (add-on preferences).
- **Connector shell tools**: the connector's PowerShell and file-write tools are **off** by default and hidden
  from the AI. *Allow PowerShell tool* turns them on: only for developers, since the AI can then run any command.
- **File reading**: the AI can read files only inside your Unreal projects, the plugin, Wildframe Forge's own
  folders and Blender's add-on folders (add more in *Extra folders the AI may read*). Password stores, SSH and
  cloud keys, `.env` files and browser data are always refused.
- **Writing files**: commands that export or render (asset export, renders, heightmaps, screenshots) save
  where the AI asks, like any export you do by hand. The AI cannot run programs or scripts on your PC unless you
  turn on *Allow AI to run raw Python* or the connector's *Allow PowerShell tool*.
- **Console commands**: `EDITOR.CONSOLE_COMMAND` blocks `quit`, `exit`, `crash`, debug commands, and commands
  that run code or change settings (`py`, `exec`, `set`, `obj`, `ke`).
- **Deletes**: asset deletes check referencers and need `confirm: true`. Deleting an asset that is still
  referenced also needs `force: true`.
- **Settings stay yours**: the AI cannot change the bridge's security settings (raw Python, authentication)
  or the Python plugin settings through the generic reflection commands. Only you can, on the Setup page.

## Settings

**Project Settings ▸ Plugins ▸ Wildframe Forge Bridge** has these settings:

- port;
- auto-start;
- authentication;
- Python policy;
- limits;
- job persistence.

## Troubleshooting

- **"No Blender session with Wildframe Forge Bridge is running"**: start the bridge in Blender's Wildframe Forge tab.
- **A command is missing**: commands that depend on optional plugins (PCG, MetaHuman, Control Rig, Water)
  appear only when those plugins are enabled.
- **An Adobe app does not show up in `adobe_status`**: open its panel once (**Window ▸ Extensions ▸
  Wildframe Forge Bridge**; Photoshop: **Plugins ▸ Wildframe Forge Bridge**). Animate shows the panel only
  after a document is open.
- **An Adobe command times out or "did not import anything"**: a dialog is open in that app (for example
  *Convert Project* when Premiere opens a project from an older version, or a missing-media prompt).
  Answer it, then ask again. Scripts cannot answer Adobe dialogs.
- **After Effects cannot render or write files**: tick **Edit ▸ Preferences ▸ Scripting & Expressions ▸
  Allow Scripts to Write Files and Access Network** (Adobe requires you to do this yourself).
- **Hub**: the tray icon's menu shows the connected apps and waiting deliveries; its log is
  `%LOCALAPPDATA%\WildframeForge\Hub\hub.log`.
- **Logs**:
  - Unreal: `<Project>/Saved/WildframeForgeBridge/Logs/Bridge.jsonl`;
  - jobs: `Saved/WildframeForgeBridge/Jobs/`.

## Support

Questions, bugs or ideas: email **wildframeforge@gmail.com**. For a problem, open the Setup page, click
**Copy diagnostic report** and paste it into the email (it contains no personal files or your user name).

## Removing the plugin

Uninstall it in the Epic Games Launcher (or delete the plugin folder). Then delete `%LOCALAPPDATA%\WildframeForge`
(the runtime copy, logs and mailbox), remove the Blender add-on in Blender's Preferences, and on the Setup
page click **Remove** next to each AI app first if you want them disconnected.

## Licence

- The Unreal plugin and the connector are covered by the Fab Standard License.
- The Blender add-on is not part of this package. It is free and open source (GPL-3.0-or-later, as Blender requires
  for add-ons) and is published at https://github.com/WildframeForge/wildframe-forge-blender (see *Dependencies*).
- See `THIRD_PARTY.md` for third-party notices.
