# Wildframe Forge Bridge Complete: Adobe apps

Your AI assistant can drive After Effects, Premiere Pro, Photoshop, Illustrator and Animate on your PC, and
pass files between them and Unreal Engine and Blender. Everything runs locally on `127.0.0.1`; nothing goes
to a cloud service.

```
Adobe app panel  --WebSocket-->  Wildframe Forge Hub (127.0.0.1:47811)  <--  connector in your AI app
Unreal plugin / Blender add-on  ----------------^  (same hub: mailbox, crash notices, tray icon)
```

Tested with After Effects 2026, Premiere Pro 2026, Photoshop 2026, Illustrator 2026 and Animate 2024 on
Windows.

## Set up (once)

1. In Unreal, open the Wildframe Forge **Setup** page and click **Adobe apps ▸ Install**. It installs:
   - the Wildframe Forge Bridge panel for After Effects, Premiere Pro, Illustrator and Animate (signed CEP panels);
   - the Photoshop and Premiere Pro UXP plugins, through Adobe's own plugin installer (Creative Cloud must be installed);
   - a small settings file so the panels can start the Wildframe Forge Hub.
2. Restart the Adobe apps. Each one now connects by itself when it starts, with or without its panel open: a
   hidden background part of the plugin keeps the connection (Photoshop and Premiere's UXP plugin load with the app).
   The panel is only a window onto it, so you can close it. To see the status, open it from:
   - After Effects, Illustrator, Animate: **Window ▸ Extensions ▸ Wildframe Forge Bridge** (Animate: open or create a document first);
   - Premiere Pro: **Window ▸ Extensions ▸ Wildframe Forge Bridge** (needs an open project) and **Window ▸ UXP Plugins ▸ Wildframe Forge Bridge**;
   - Photoshop: **Plugins ▸ Wildframe Forge Bridge**.

   The panel says **Connected (background)** when the app stays connected on its own, or **Connected (panel)** when
   that app version did not start the background part: then keep the panel open (docked) so the AI can reach the app.
3. In After Effects tick **Edit ▸ Preferences ▸ Scripting & Expressions ▸ Allow Scripts to Write Files and
   Access Network**. Adobe requires you to do this yourself; without it After Effects cannot save frames or render.

The dot in each panel turns green when the AI can use that app. If the hub is not running, your AI app or any of the After Effects, Premiere, Illustrator or Animate panels starts it (the Photoshop and Premiere UXP plugins wait for it).

**Only use Photoshop?** Photoshop's plugin cannot start programs, so it waits until something else starts the hub (Unreal, Blender, your AI app or another Adobe panel). To have the hub ready anyway, tick **Start with Windows** in the Wildframe Forge tray icon's menu. It is off unless you turn it on, and unticking it removes it again.

## What the AI uses

| Tool | What it does |
|---|---|
| `adobe_status` | Which Adobe apps are connected, their versions and command counts |
| `adobe_find_commands` | Search an app's commands by keyword (`render`, `keyframe`, `recipe`...) with their arguments |
| `adobe_get_state` | What is in the app as data: comps, layers, bins, sequences, documents (no screenshots) |
| `adobe_run_command` | Run a command or a `recipe_*` (a whole task in one call) |
| `adobe_run_script` | Raw script, for when no command fits. Off unless you turn on *Allow PowerShell tool (advanced users only)*: a raw script can run any program on your PC |

In After Effects each command is a single undo step, so Ctrl+Z takes back what the AI did. The other apps undo step by step (Photoshop and Illustrator also have `undo` commands the AI can use).

## No connector? Use AI Scripts (ChatGPT, Grok, Gemini, any chat AI)

Chat AIs that can't use a connector (including the free ChatGPT plan) can still drive the Adobe apps:

1. Open **AI Scripts**: the **AI Scripts** button in any Wildframe Forge panel, or **AI Scripts for Adobe apps** in
   the Wildframe Forge tray icon's menu. It opens a page in your browser, served by the hub on your own PC.
2. The page lists the Adobe apps that are open. Untick the ones you don't need, click **Copy primer for AI** and
   paste it into a new chat. The primer only describes the apps you picked, with each app's own commands.
3. Ask for what you want. The AI replies with a job; paste its reply into the page, click **Check** to see the steps,
   then **Run**.
4. Click **Copy result for AI** (or **Copy error for AI** if the job was rejected) and paste it back, so the AI can
   take the next step or fix its job.

One job can use several apps (for example export a PNG from Photoshop, then import it in After Effects). Raw scripts
never run from this page. Unreal has its own AI Scripts page in the Wildframe Forge Bridge tab.

## Try it

Ask your AI, for example:

- "Import my Unreal render into After Effects, add a colour grade, cinematic bars and a title card, then render it."
- "Cut my renders to the beat of this song in Premiere (117 BPM) and export a frame so you can check it."
- "Open this Blender render in Photoshop, add the title FORGE in red with a glow and save it as a PNG; then import it into Unreal as a texture."
- "Make an emblem in Illustrator and animate it in Animate."

## When something does not work

- **An app is missing from `adobe_status`**: restart the app once after installing. If it is still missing (or its
  panel says **Connected (panel)**), open its panel and keep it open (see Set up, step 2). Animate connects only once
  a document is open.
- **A command times out, or Premiere "did not import anything"**: the app is showing a dialog (for example
  *Convert Project* for a project from an older Premiere, or a missing-media prompt). Answer it and ask again.
- **After Effects cannot write files or render**: see Set up, step 3.
- **Premiere UXP plugin updates** load only after Premiere restarts.
- Hub log: `%LOCALAPPDATA%\WildframeForge\Hub\hub.log` (the tray icon's menu can open it).

## How CEP and UXP work together

Adobe is moving its apps from CEP/ExtendScript to UXP; the bridge supports both, side by side, with the same
command names. A call goes to UXP when it has the command, otherwise to CEP. `adobe_find_commands` shows which
runtimes have each command.

| App | CEP / ExtendScript | UXP |
|---|---|---|
| After Effects | 89 commands | not available from Adobe yet |
| Premiere Pro | 67 commands | 30 commands |
| Photoshop | - | 48 commands |
| Illustrator | 35 commands | not available from Adobe yet |
| Animate | 30 commands (JSFL) | not available from Adobe |

Argument names that a command does not know are reported back as a warning, so a misnamed argument is noticed.

## After Effects commands

Arguments: `comp` = name, id or `"active"`; `layer` = index, name or `"selected"`; times in seconds; colors `[r,g,b]` 0-1; `property` = shortcut (`position`, `scale`, `rotation`, `opacity`, `anchorPoint`, `sourceText`, ...) or a path like `Effects/Glow/Glow Radius`.

**info** (8)

- `listCommands` - Every command this plugin supports with its arguments.
- `hostInfo` - After Effects version and open project.
- `getState` - Project overview (items, comps, render queue). Pass comp for full detail of one comp: every layer, transforms, effects, keyframes, expressions, markers.
- `listEffects` - Search installed effects by name/category. Use the matchName with addEffect.
- `getProperty` - Read one property: value, keyframes, expression.
- `listProperties` - List the properties under a layer or group (e.g. an effect's parameter names).
- `getLayerBounds` - Layer's visible rectangle at a time (text/shape size), in layer space.
- `listFonts` - Installed fonts (PostScript names for text style 'font').

**project** (11)

- `newProject` - Close the current project and start a new empty one. If it has unsaved changes pass save:true (and savePath if never saved) or discard:true.
- `openProject` - Open an .aep project. If the current one has unsaved changes pass save:true or discard:true.
- `saveProject` - Save the project (pass path for Save As).
- `importFiles` - Import footage, images, audio or image sequences. Optionally add them to a comp as layers.
- `createFolder` - Create a project folder.
- `deleteItems` - Remove items from the project.
- `setInterpretation` - Footage interpretation: frame rate, alpha, loop, pixel aspect, fields.
- `replaceFootage` - Point a footage item at a new file (every layer using it updates). sequence:true for image sequences.
- `importAsComp` - Import a layered PSD/AI as a comp (each layer becomes a layer).
- `projectSettings` - Bit depth, color/linear blending, time display, audio rate.
- `cleanupProject` - removeUnused | consolidate | reduce (keep only given comps).

**comp** (5)

- `createComp` - Create a composition and open it.
- `setComp` - Change comp settings.
- `openComp` - Open a comp in the viewer (makes it the active comp).
- `duplicateComp` - Duplicate a comp.
- `precompose` - Precompose layers into a new comp.

**layer** (10)

- `addLayer` - Add a layer. type: solid, adjustment, null, text, shape, camera, light, item (footage/comp from the project).
- `setLayer` - Change layer settings and static property values. 'properties' takes any {propertyPath: value}.
- `deleteLayers` - Delete layers.
- `duplicateLayer` - Duplicate a layer.
- `moveLayer` - Reorder a layer.
- `selectLayers` - Select layers (deselects others).
- `addMask` - Add a mask from points (pixels, layer space).
- `replaceLayerSource` - Swap a layer's source for another project item (keeps effects/keyframes).
- `splitLayer` - Split a layer at a time (like Ctrl+Shift+D). Returns both halves.
- `setTrackMatte` - Use another layer as a track matte: alpha | alphaInverted | luma | lumaInverted | none.

**animation** (7)

- `setKeyframes` - Add keyframes. Each key: {time, value, interp?}. interp: linear | hold | easy (ease in+out) | easeIn | easeOut | bezier. 'clear' removes existing keys first.
- `removeKeyframes` - Remove keyframes (all, or those between from/to seconds).
- `setExpression` - Set an expression on a property (empty string removes it). Returns any expression error.
- `addMarkers` - Add markers to the comp (or to a layer if layer is given).
- `clearMarkers` - Remove all markers from the comp or a layer.
- `setKeyframeEase` - Fine-tune keyframes: temporal ease (speed/influence), interpolation in/out, roving, spatial continuity.
- `copyKeyframes` - Copy all keyframes from one property to another (any layer/comp), with a time offset.

**effects** (4)

- `addEffect` - Add an effect (display name or matchName; see listEffects) and set its parameters by name. Returns all parameter names and values.
- `setEffect` - Change an effect's parameters, enable/disable, or rename it.
- `removeEffect` - Remove an effect from a layer.
- `applyPreset` - Apply an animation preset (.ffx) to a layer.

**render** (6)

- `addToRenderQueue` - Queue a comp for rendering. Use template names as seen in AE (e.g. 'Best Settings', output module 'H.264 - Match Render Settings - 15 Mbps' or 'High Quality with Alpha').
- `render` - Render everything queued (blocks After Effects until done - pass a long timeoutSec).
- `clearRenderQueue` - Remove all items from the render queue.
- `saveFrame` - Save one frame of a comp as PNG so the AI can look at it (preview without screenshots).
- `listRenderTemplates` - Render-settings and output-module template names you can use with addToRenderQueue.
- `queueInMediaEncoder` - Send the render queue to Adobe Media Encoder (start:true to start encoding right away). AE stays free.

**advanced** (10)

- `reloadHost` - Reload this command library from disk on the next call (after updating the plugin, no AE restart needed).
- `runScript` - Run raw ExtendScript. The value of the last expression is returned.
- `batch` - Run many commands in ONE call and ONE undo step: steps = [{command, args}]. Saves usage. Stops at the first error unless continueOnError.
- `menuCommand` - Run ANY After Effects menu command by its exact menu name (e.g. 'Convert to Editable Text', 'Sequence Layers...', 'Auto-trace...') or numeric id. Works on the current selection.
- `undo` - Undo the last N steps (each bridge command is one step).
- `redo` - Redo the last N undone steps.
- `purge` - Free memory/cache: all | memory | undo | image | snapshot.
- `addProperty` - Add ANY property/group by matchName under a group path - shape contents, text animators, masks, effects, layer styles. e.g. path 'Contents', matchName 'ADBE Vector Shape - Star'. Returns the new path.
- `removeProperty` - Remove a property group (effect, mask, shape group, animator, ...) by path.
- `setProperties` - Set many static values at once across layers: items = [{layer, property, value}].

**recipes** (13)

- `recipe_beatMarkers` - Put comp markers on the beat of a song (bar numbers on downbeats).
- `recipe_beatCuts` - Cut clips to the beat: lays project items (or existing layers) one after another, each lasting N beats. Great for edits from Unreal renders.
- `recipe_beatPulse` - Make a layer pulse on every beat (scale, opacity, or any 1D/2D property) using a live expression.
- `recipe_audioReactive` - Drive a property with the music: converts an audio layer to keyframes, then links a layer property to the loudness.
- `recipe_titleCard` - Animated title text: fades in, slow push, fades out. Good for song titles and chapter cards.
- `recipe_cinematicBars` - Add black letterbox bars for a cinematic aspect ratio.
- `recipe_cameraShake` - Add a controllable camera/handheld shake to a layer (wiggle on position and rotation).
- `recipe_detectBeats` - Find the hits in a song automatically (no BPM needed): reads loudness peaks from an audio layer, adds comp markers, returns the times and an estimated BPM. Feed times to recipe_beatCuts.
- `recipe_beatFlash` - Flash/strobe on the beat: a white (or colored) flash layer that pops and fades on every hit.
- `recipe_glitchHits` - Glitch on the beat: position jitter, RGB split and flicker for a few frames on every hit (expression driven).
- `recipe_colorGrade` - One-click look on an adjustment layer: cinematic | tealOrange | warm | cold | bleach | noir | vintage | epic.
- `recipe_vignette` - Dark (or colored) edges vignette.
- `recipe_lightLeak` - Animated light leak / flare sweep (screen blend) for transitions and hits.

**time** (3)

- `timeRemap` - Enable time remapping and set keys: [{time (comp s), value (source s)}]. hold:true makes them freeze steps.
- `freezeFrame` - Freeze a layer on one frame from a time onward (or for a duration, then it continues).
- `recipe_speedRamp` - Speed ramp: plays normally, ramps to a slow (or fast) speed for a section, then back. Great for impact moments.

**shapes** (2)

- `addShape` - Draw a vector shape (on an existing shape layer or a new one): rect | ellipse | star | polygon | path, with fill/stroke and optional trim paths.
- `addShapeModifier` - Add a shape modifier to a shape group: trim | repeater | roundCorners | wiggle | zigzag | twist | offset | pucker | merge, with params by display name.

**text** (3)

- `addTextAnimator` - Add a text animator (per-character/word/line animation) with properties and a range selector.
- `recipe_textReveal` - Animate text in: fade | typewriter | slideUp | blurIn | scaleIn | tracking, by characters/words/lines.
- `recipe_lyrics` - Lyric video: one text layer per line, timed and animated. lines = [{time, text, duration?}] or lrc = path to a .lrc file.

**3d** (3)

- `setCamera` - Camera options: zoom, depth of field, focus distance, aperture, blur level, two-node.
- `recipe_cameraMove` - Cinematic camera move on a 3D camera (made if missing): pushIn | pullOut | orbit | truckLeft | truckRight | craneUp | craneDown | dollyZoom. Turns layers 3D if asked.
- `addLight` - Add a 3D light: parallel | spot | point | ambient, with color, intensity, shadows.

**essentialGraphics** (2)

- `addToEssentialGraphics` - Expose a property in the comp's Essential Graphics panel (so Premiere can edit it).
- `exportMogrt` - Export the comp as a Motion Graphics Template (.mogrt) for Premiere. The project must have been saved once; takes ~30 s - pass timeoutSec 120.

## Built-in safety nets

- **Dialog watchdog:** while a command runs, the CEP panel closes the export log windows Premiere opens by itself (AAF/OMF export logs) so calls finish instead of freezing the app. Closed dialogs are reported in the result.
- **Unsaved work:** After Effects `newProject` / `openProject` refuse to throw away unsaved changes unless told `save:true` or `discard:true`.
- **One undo per command** in After Effects (`batch` = one undo for all its steps).
- **Output folders** are created when a save or export points to a folder that does not exist yet.

## Cross-app ideas (tested)

- Illustrator `recipe_emblem` → transparent 4K PNG → Animate `importFile` + `animate` (tested), After Effects `importFiles` / `importAsComp` for .ai.
- After Effects / Premiere frames → Photoshop `recipe_thumbnail` → Illustrator `imageTrace` (tested chain).
- After Effects `exportMogrt` → Premiere `insertMogrt` with editable fields.
- One `.lrc` lyric file → animated lyrics in After Effects (`recipe_lyrics`) and captions in Premiere (`addCaptions`).
- Premiere `exportXML` / `exportAAF` for other tools (Resolve, audio apps).

## Premiere commands

Same argument conventions as After Effects; `sequence` = name, id or `"active"`; `track` = `1`, `"V2"`, `"A1"`; `clip` = index (1 = first) or name.

- **info:** `getState`, `getClipEffects`, `findPresets` (CEP), `listEffects` / `listTransitions` (UXP)
- **project:** `importFiles`, `createBin`, `saveProject`, `openProject` / `newProject` (CEP; Premiere reloads panels, so the bridge reconnects), `moveItem`, `renameItem`, `deleteBin` (CEP)
- **sequence:** `createSequence` (preset .sqpreset or fromItems), `openSequence`, `setPlayhead`, `setInOut`, `addTrack` (CEP)
- **edit:** `placeClip`, `listClips`, `setClip`, `removeClips`, `razor` (CEP)
- **effects:** `addEffect`, `setEffect`, `setKeyframes`, `addTransition`
- **markers:** `addMarkers`, `clearMarkers`
- **export:** `exportSequence` (.epr preset, direct or queued to Media Encoder), `exportFrame` (PNG preview)
- **recipes:** `recipe_beatMarkers`, `recipe_beatCut` (song on A1 + clips cut on the beat, no gaps), `recipe_dissolveAll` (CEP)
- **advanced:** `batch` (many steps, one call), `undo` / `redo`, `runScript` (ExtendScript on CEP, async UXP JavaScript on UXP), `reloadHost`
- **more edit:** `selectClips`, `nest`, `linkClips`, `moveClip`, `reverseClip`, `duplicateSequence`, `sequenceSettings`, `autoReframe` (9:16 / 1:1 / 4:5 that follows the action), `sceneDetect` (cut or mark every shot change)
- **graphics:** `insertMogrt` (built-in or After Effects-made .mogrt, fills its fields), `setMogrt`, `listMogrts`, `addCaptions` (from lines, a .lrc lyric file or .srt)
- **audio:** `setVolume` (dB, with fade/duck keys), `setTrack` (mute/lock/target/name), `recipe_audioFades`
- **project:** `createSubclip`, `relinkMedia`, `attachProxy`, `setInterpretation`, `setItemLabel`, `listQEEffects`
- **interchange:** `exportXML` (Final Cut Pro XML), `exportAAF`, `exportOMF`
- **recipes:** `recipe_colorGrade` (Lumetri looks), `recipe_verticalVersion`

Tip: in Premiere 2026 "Gaussian Blur" is a newer effect; the classic one with "Blurriness" is "Gaussian Blur (Legacy)". When a parameter isn't found, the error lists the real parameter names.

## Photoshop (UXP) commands (47)

Every change runs as one Photoshop history step. `layer` = name, path (`Group/Layer`) or id; colors `[r,g,b]` 0-1 or 0-255.

**info** (4)

- `listCommands` - Every command this plugin supports.
- `hostInfo` - Photoshop version and open documents.
- `getState` - Open documents; pass document (or 'active') for the full layer tree with bounds, opacity, blend modes, text.
- `exportPreview` - Save a PNG of the current document (as a copy) so the AI can look at it.

**document** (13)

- `newDocument` - New document.
- `openFile` - Open an image/PSD.
- `activateDocument` - Bring a document to the front.
- `saveAs` - Save/export the document: psd | png | jpg | tif | webp | gif. asCopy keeps the document as is.
- `save` - Save the document in place.
- `closeDocument` - Close a document. save:true saves first; otherwise changes are discarded.
- `resizeImage` - Resize the image (keeps aspect if only width or height).
- `resizeCanvas` - Resize the canvas.
- `crop` - Crop to {left, top, right, bottom} (px).
- `rotateCanvas` - Rotate the whole canvas (degrees).
- `flatten` - Flatten all layers.
- `mergeVisible` - Merge visible layers.
- `trim` - Trim transparent (or edge-colored) borders.

**layer** (12)

- `createLayer` - New empty pixel layer (optionally filled with a color).
- `setLayer` - Change a layer: name, opacity, fillOpacity, blendMode, visible, locked.
- `transformLayer` - Move / scale / rotate a layer. move: [dx,dy] or to: [x,y] (top-left), scale: percent or [w%,h%], rotate: degrees, fit: 'canvas' to cover/contain.
- `alignLayer` - Align a layer to the canvas: horizontal left|center|right, vertical top|middle|bottom, with margin.
- `duplicateLayer` - Duplicate a layer (optionally into another document).
- `deleteLayers` - Delete layers.
- `arrangeLayer` - Reorder: top | bottom | up | down, or above/below another layer.
- `groupLayers` - Put layers into a new group.
- `mergeLayers` - Merge layers into one.
- `rasterize` - Rasterize a text/shape/smart object layer.
- `selectLayers` - Select layers (others deselected).
- `placeImage` - Place an image/PSD/AI file as a smart object layer, optionally fitted to the canvas.

**text** (2)

- `addText` - Text layer: contents, font (PostScript name), size, color, position (center), align, tracking.
- `setText` - Change a text layer's contents/size/color/font.

**selection** (4)

- `select` - Make a selection: all | none | invert | rect | ellipse | subject (AI) | sky (AI) | layer (from a layer's pixels).
- `fillSelection` - Fill the selection (or whole layer) with a color on a layer.
- `deleteSelection` - Delete the selected pixels on a layer.
- `addMask` - Add a layer mask: from the current selection (reveal or hide), or revealAll / hideAll.

**ai** (1)

- `removeBackground` - Remove the background of a layer: Photoshop's AI Select Subject, then a layer mask (non-destructive). invert:true keeps the background instead.

**filters** (1)

- `applyFilter` - Filter on a pixel layer: gaussianBlur {radius} | motionBlur {angle, distance} | sharpen {amount, radius, threshold} | noise {amount, monochrome} | highPass {radius} | median {radius}.

**adjustments** (1)

- `addAdjustment` - Adjustment layer: brightnessContrast {brightness, contrast} | hueSaturation {hue, saturation, lightness, colorize} | vibrance {vibrance, saturation} | exposure {exposure, offset, gamma} | photoFilter {color, density} | blackWhite | invert | posterize {levels} | threshold {level} | gradientMap {from, to}.

**styles** (1)

- `addLayerStyle` - Layer effects: dropShadow {color, opacity, angle, distance, size} | outerGlow {color, opacity, size} | stroke {color, size, position: outside|inside|center} | colorOverlay {color, opacity}. Several at once: styles = {dropShadow:{...}, stroke:{...}}.

**advanced** (6)

- `batchPlay` - Run raw Photoshop action descriptors (anything Photoshop can record) - descriptors: [{_obj, ...}].
- `runScript` - Run raw UXP JavaScript inside executeAsModal. Variables: ps, app, action, core, constants, uxp, args. Return a value.
- `batch` - Run many commands in ONE call: steps = [{command, args}].
- `undo` - Step backwards in history N times.
- `redo` - Step forward in history N times.
- `reloadHost` - No-op for UXP (Photoshop reloads plugins on restart).

**recipes** (2)

- `recipe_thumbnail` - YouTube thumbnail / cover: background image (cover), dark gradient, big title with stroke + glow (fitted inside the canvas), exported as JPG.
- `recipe_poster` - Movie poster (2:3, default 1080x1620): background, mood gradient, big title in the lower part, tagline and credits line, exported as JPG/PNG.
- `recipe_socialSizes` - Export the current document to many platform sizes (cover-cropped): youtube 1280x720, square 1080x1080, story 1080x1920, banner 2560x1440, album 3000x3000, twitter 1600x900.

## Illustrator commands (35)

Coordinates are artboard pixels with a top-left origin and y going down (converted to Illustrator's system internally). Name items when you create them so later commands can find them.

**info** (4)

- `listCommands` - Every command this plugin supports.
- `hostInfo` - Illustrator version and open documents.
- `getState` - Documents, or (document:'active') artboards, layers and items with bounds/colors/text (top-left coordinates, y down).
- `listFonts` - Installed fonts (use the name with addText).

**document** (7)

- `newDocument` - New document.
- `openFile` - Open an .ai/.pdf/.svg/.eps (or image as new doc).
- `saveAs` - Save as ai | pdf | svg | eps.
- `exportImage` - Export png | jpg | svg (one artboard or all). scale in percent (400 = 4x for crisp video use). transparent PNG by default.
- `closeDocument` - Close a document (save:true saves first, otherwise discards).
- `addArtboard` - Add an artboard at {left, top, width, height} (top-left of the first artboard = 0,0).
- `fitArtboard` - Fit the active artboard to the artwork (or the selection).

**layer** (3)

- `createLayer` - New layer.
- `setLayer` - Layer name / visible / locked / opacity / order (top|bottom).
- `deleteLayer` - Delete a layer and its art.

**draw** (3)

- `addShape` - Draw: rect | roundedRect | ellipse | polygon | star | line | path. Coordinates are artboard px, top-left origin, y down.
- `addText` - Text: point text at a position, or area text in a box. font = name from listFonts.
- `placeImage` - Place an image/PDF/AI file (linked or embedded), positioned and sized.

**items** (10)

- `listItems` - Items on the document or one layer.
- `setItem` - Change an item: fill, stroke, strokeWidth, opacity, name, blendMode, position (center), topLeft, size [w,h], scale %, rotate deg, order (top|bottom|up|down), hidden, locked.
- `duplicateItem` - Duplicate an item, optionally moved by [dx,dy].
- `deleteItems` - Delete items.
- `groupItems` - Group items.
- `selectItems` - Select items (or 'all' / 'none').
- `alignItems` - Align items to the artboard: horizontal left|center|right, vertical top|middle|bottom, margin px.
- `pathfinder` - Combine shapes: unite | minusFront | intersect | exclude | divide (on the given items).
- `outlineText` - Convert text to editable shapes (outlines).
- `imageTrace` - Vectorize a placed/embedded image (Image Trace) and expand it to paths. preset e.g. 'High Fidelity Photo', 'Black and White Logo', '6 Colors', 'Silhouettes', 'Line Art'.

**advanced** (7)

- `menuCommand` - Run ANY Illustrator menu command by its internal name (e.g. 'group', 'ungroup', 'expandStyle', 'Live Pathfinder Add', 'outline', 'selectall', 'deselectall', 'Rotate', 'Make Envelope') on the selection.
- `playAction` - Play a recorded Actions-panel action: name + set.
- `undo` - Undo N steps.
- `redo` - Redo N steps.
- `batch` - Run many commands in ONE call: steps = [{command, args}].
- `runScript` - Run raw ExtendScript; the last expression's value is returned.
- `reloadHost` - Reload this command library from disk on the next call.

**recipes** (1)

- `recipe_emblem` - Viking/band-style emblem: ring + star/polygon + title text (outlined), centered on a new artboard-sized document. Exports a transparent 4K PNG for After Effects/Premiere if output is given.

## Animate commands (30)

Frames are 1-based. Draw with `toSymbol` (or `convertToSymbol`) to get a movie clip that `animate` can tween.

**info** (3)

- `listCommands` - Every command this plugin supports.
- `hostInfo` - Animate version and open documents.
- `getState` - Active document: size, fps, layers (with keyframes), elements on frame 1 (or 'frame'), library items.

**document** (5)

- `newDocument` - New document: type html5 (HTML5 Canvas, default) | as3 | webgl.
- `openFile` - Open an .fla / .xfl.
- `saveAs` - Save the document as .fla.
- `closeDocument` - Close the active document without saving prompts (save:true saves first).
- `setDocument` - Stage size, fps, background color.

**timeline** (6)

- `addLayer` - Add a layer on top: normal | guide | mask | folder.
- `setLayer` - Layer name / visible / locked / outline / color.
- `deleteLayer` - Delete a layer.
- `setLength` - Make a layer (or all layers) last N frames.
- `keyframe` - Insert a keyframe (copies the previous one) or a blank keyframe; optional frame label.
- `gotoFrame` - Move the playhead.

**draw** (5)

- `drawShape` - Draw rect | oval on a layer/frame (stage px). fill/stroke colors [r,g,b] or #hex.
- `addText` - Static text at a position (center). font = font name, size pt, color, align.
- `importFile` - Import an image/sound/video/SVG/PSD. toLibrary:true only adds it to the library; otherwise it goes on the stage (current layer/frame).
- `placeSymbol` - Put a library item on the stage at a position (center).
- `convertToSymbol` - Convert everything on a layer/frame into a symbol: movieclip | graphic | button.

**animate** (4)

- `listElements` - Elements on a layer at a frame.
- `setElement` - Change an element at a frame: x, y, scale / scaleX / scaleY, rotation, width, height, alpha (symbols), name.
- `animate` - Keyframe animation of one element with classic tweens: keys = [{frame, x, y, scale, rotation, alpha}], ease -100 (in) .. 100 (out). The element should be a symbol (use toSymbol when drawing).
- `shapeTween` - Shape tween between two keyframes of raw shapes on a layer (morphing).

**export** (3)

- `exportPNG` - Export the current frame (or all frames as a PNG sequence) using the document's PNG settings.
- `exportVideo` - Export the animation as video. media:true sends it through Media Encoder (H.264 .mp4); otherwise a .mov.
- `publish` - Publish with the document's publish settings (HTML5 Canvas -> html/js).

**advanced** (3)

- `runScript` - Run raw JSFL; the last expression's value is returned.
- `batch` - Run many commands in ONE call: steps = [{command, args}].
- `reloadHost` - Reload this command library from disk on the next call.

**recipes** (1)

- `recipe_titleIntro` - Animated title intro: text pops in (scale + fade with ease), holds, fades out. Optional background color and video export.
