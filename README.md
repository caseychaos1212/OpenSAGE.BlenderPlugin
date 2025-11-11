OpenW3D Fork of OpenSAGE.BlenderPlugin
============================================================


**OpenW3D Blender Plugin** (formerly **OpenSAGE.BlenderPlugin**): a free, open source Blender plugin for the [Westwood](https://de.wikipedia.org/wiki/Westwood_Studios) 3D
format used in Command & Conquer™: Renegade and other RTS titles from Westwood Studios and EA Pacific. The project is a fork from the OpenSAGE contributors, and we remain grateful for their groundwork.

## Installing and activating

Please see [Installing the plugin](https://github.com/OpenSAGE/OpenSAGE.BlenderPlugin/wiki/Installing-the-Plugin)

## Setting up for development

Please see [Setting up for development](https://github.com/OpenSAGE/OpenSAGE.BlenderPlugin/wiki/Development-Setup)

## Changes in this fork

## v0.8.0 (OpenW3D)

* End-to-end Renegade parity: added the new W3DObjectSettings/material pass data model, selection helpers, naming wizards, LOD/damage helpers, terrain-mode filtering, review-log popup, and dazzle preference override so Blender can author Renegade assets like the 3ds Max tool.
* Exporter/importer rewiring: every export/import path now consumes the new object/material data (multi-pass serialization, stage animation data, terrain-mode options, collision flag threading, dedup/AABTree toggles, etc.), plus the importer backfills the new properties after W3D loads.
* Material pipeline overhaul: Blender materials now hold multiple passes/stages with shader settings, texture animation, stage hints, and per-stage image picks that serialize/round-trip in W3D.
* Terrain + collision fixes: terrain mode no longer ejects Normal meshes, collision warnings were removed, exports operate on evaluated mesh copies, and collision flags map directly to `W3D_MESH_FLAG_COLLISION_TYPE_*`.
* UI & tooling polish: rebuilt the object/material panels to mirror the Max roll-ups, added pass-stack controls with Vertex/Shader/Textures tabs, selection/naming/instance-copy operators, and presets for billboards/dazzles/collision boxes.
* Branding refresh: rebranded the add-on to OpenW3D (crediting OpenSAGE) and bumped the version to 0.8.0; README/metadata reflect the new name.
* Added a `Push Display Texture` operator that mirrors Max’s “Assign Material to Selection” behavior by applying the Display-enabled stage bitmap to the Blender material graph.
* Introduced a scene-level “Use Renegade workflow” toggle so geometry context drives mesh/object type synchronization automatically and forces hierarchy/HLOD/AABTree chunks to match the 3ds Max exporter.


## Note

The plugin is still in beta and the behaviour may change between releases. Also bugs might still occur, which we'll try to fix as soon as possible. This fork is for W3D engine games and SAGE support may be and likely is broken. Do not expect support for SAGE content from the OpenSAGE community from this fork.

## Legal disclaimers

* This project is not affiliated with or endorsed by EA in any way. Command & Conquer is a trademark of Electronic Arts.
* This project is non-commercial. The source code is available for free and always will be.
* If you want to contribute to this repository, your contribution must be either your own original code, or open source code with a
  clear acknowledgement of its origin.
* No assets from the original games are included in this repo.

## Community

We have a growing [OpenW3D community on the W3DHub Discord](https://discord.gg/2GzrhpGP).
