# Wildframe Forge Hub tray icon

`WildframeForgeHub.exe` is the small tray icon program of the Wildframe Forge Hub (open Setup, the AI Scripts page,
deliveries, start with Windows, quit). It is optional: the hub works without it.

- **Wildframe Forge Bridge (Unreal + Blender):** download [WildframeForgeHub.exe](WildframeForgeHub.exe) (click the
  download button on that page) into your Downloads folder. The hub adds it within a minute, after checking it against
  the SHA-256 fingerprint pinned in the plugin (`Resources/Connector/downloads.json`).
- **Wildframe Forge Bridge Complete:** the Setup page downloads it from here and checks the same fingerprint.

- Source: [WildframeForgeHub.cs](WildframeForgeHub.cs), built with the C# compiler that ships with Windows
  (`csc /target:winexe`).
- It needs the .NET Framework 4.8 that comes with Windows 10 and 11.

Copyright Wildframe Forge 2026. All Rights Reserved. Free to download and use with Wildframe Forge Bridge.
This folder is not part of the Blender add-on and is not covered by the add-on's GPL licence.
