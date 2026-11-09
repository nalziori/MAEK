# Unity demonstration checkout

This branch depends on `codex/inspection-core-20261109`. Open
`unity/MAEKInspection` with Unity 6000.3.12f1 after `git lfs install` and `git lfs pull`.
The checked-in Assets, .meta GUIDs, Packages and ProjectSettings include the
247-pipe `Assets/MAEK/Scenes/MAEKInspectionDemo.unity` scene and its runtime inputs.

Install base requirements and `requirements-demo.txt`. Use
`./scripts/start_inspection_bridge.ps1`, then open the scene and press Play.
For a fresh full editor/Play/collision/evidence run, execute
`./scripts/run_inspection_harness.ps1 -Unity <path-to-Unity.exe>`.
The default Unity executable path is local and may be overridden with -Unity.
Existing reports record the original development run; the raw sessions, videos,
absolute latest-session pointers and evidence seals are generated locally.
Run the harness to produce a current seal for this checkout before verifying --evidence.

Blender files, Unity packages, render images, recordings, numerical case caches,
Library/ and machine settings stay local. Generation scripts and compact configs
are included. CFD optional dependencies are in visualization/cfd/requirements-cfd.txt.
Legacy standalone Blender/CFD scripts have a separate Ruff scope; package CI still
checks maek/, scripts/ and tests/. Run their numerical tests explicitly from the
corresponding visualization subdirectory.

The scene is synthetic. RGB rust candidates are not crack predictions or field
accuracy evidence. Assumed hydraulics and missing plant circuits are shown in the UI.
