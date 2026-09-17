OpenW3D Fork of OpenSAGE.BlenderPlugin
============================================================


**OpenW3D Blender Plugin** (fork of **OpenSAGE.BlenderPlugin**): a free, open source Blender plugin for the [Westwood](https://de.wikipedia.org/wiki/Westwood_Studios) 3D
format used in Command & Conquer™: Renegade and other RTS titles from Westwood Studios and EA Pacific. The project is a fork from the OpenSAGE contributors, and we remain grateful for their groundwork.

## Installing and activating

Please see [Installing the plugin](https://github.com/OpenSAGE/OpenSAGE.BlenderPlugin/wiki/Installing-the-Plugin)

Supported Blender versions are 2.93 up to 5.2. On Blender 4.2 and newer the released `io_mesh_w3d.zip`
can be dropped into Blender to install it as an extension, older versions install it as a legacy add-on
via *Edit > Preferences > Add-ons > Install*.

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
* Added a `Push Display Texture` operator that mirrors Max’s “Assign Material to Selection” behavior by applying the Display-enabled stage bitmap to the Blender material graph. (not fully working)
* Introduced a scene-level “Use Renegade workflow” toggle so geometry context drives mesh/object type synchronization automatically and forces hierarchy/HLOD/AABTree chunks to match the 3ds Max exporter.

## Instructions

Enable the new workflow per scene: open the Scene properties sidebar, expand the W3D Workflow panel, and check Use Renegade workflow. That tells the exporter to treat Blender like the Max Renegade tool—every export (including “Mesh”) will emit hierarchy/HLOD chunks, keep mesh object types in sync with their W3D geometry context, and always build fresh AABTrees, so you no longer have to flip object types or export modes manually.

NOTE: When importing weapon animations import the base mesh first, then import the animation with "Keep Rigid meshes static".

### Object export settings

Open **Object Properties > W3D Object** (the orange square tab) for W3D export
settings. The Mesh Data tab now has an **Open W3D Object Settings** shortcut.

Choose **HLOD Role** for normal LOD geometry or an Aggregate, Proxy, or Light
Reference attachment. Attachments show their identifier and omit geometry
controls that do not affect their export. For LOD geometry, **Export Type**
selects a mesh, billboard, collision box, dazzle, or helper. The panel shows
only the controls consumed by that type's exporter.

Sort level, shadow, and two-sided controls use the object's effective export
values. Saved legacy mesh values remain supported when no object override is
set; setting zero or turning a flag off explicitly overrides the legacy value.
Mesh classification and data such as collision-box flags are shared by linked
mesh objects; geometry flags and export inclusion remain per object.

### Geometry flags

All ten geometry controls are available in **Object Properties > W3D Object >
Geometry Flags**. The restored controls follow the Max exporter's behavior:

| Control | Export behavior |
| --- | --- |
| **Vertex Alpha** | Converts the active color attribute's RGB average to vertex alpha on passes whose blend factors or alpha test use it. The chosen attribute supplies alpha instead of diffuse RGB. Supports both Point and Face Corner color attributes. |
| **Z Normal** | Writes `(0, 0, 1)` for every exported normal, including secondary skin normals. Overrides **Keep Normals**. |
| **Keep Normals** | Preserves authored corner normals and hard edges through triangulation and UV splitting. Overrides the export dialog's **Smooth Vertex Normals** option. |
| **Shatter** | Writes the W3D shatterable flag (`0x10000000`). |
| **Prelit** | Writes the Max/TT prelit flag (`0x40000000`). This flag does not bake lighting or create the older prelit/lightmap material chunks. |
| **Always Dynamic Light** | Writes the Max/TT always-dynamically-lit flag (`0x80000000`). |

For **Vertex Alpha**, select the color attribute in **Mesh Data > Color
Attributes**, paint its RGB values, and use an alpha-blended or alpha-tested
material pass. Black gives zero alpha; white gives full alpha. Existing alpha in
imported `DCG_*` layers continues to export with this checkbox off. The other
per-pass color layers retain their existing meaning.

Import restores the three W3D flags and enables **Keep Normals** for meshes with
stored normals. The file does not record whether **Z Normal** or **Vertex Alpha**
was used to produce the data, so import preserves the resulting normals and alpha
without enabling either conversion again. All geometry preparation happens on a
temporary export mesh and leaves the source mesh unchanged.

**Shatter**, **Prelit**, and **Always Dynamic Light** are W3D-only metadata;
W3X export reports when these are selected. Normal and vertex-alpha operations
also work on W3X geometry. **Hide**, **Shadow**, **Two Sided**, and **Tangents**
remain available.

Reference: Max's [mesh flags and normal export](https://github.com/w3dhub/max2w3d/blob/master/w3dmaxtools/Source/w3dexport.cpp),
[geometry option definitions](https://github.com/w3dhub/max2w3d/blob/master/w3dmaxtools/Redist/w3dappdatachunk.h),
and OpenW3D's [mesh header flags](https://github.com/w3dhub/OpenW3D/blob/main/Code/ww3d2/w3d_file.h).

### Aggregates and helper objects

Set **HLOD Role** to **Aggregate** in Object Properties > W3D Object to export a
building reference without processing or writing its mesh geometry. Aggregate
and Proxy references are included even when a saved **Export Geometry** setting
is off, including scenes
containing only attachments. Use Hierarchical Model or Terrain export (or enable
the Renegade workflow) to write the HLOD data.

Turn off **Export Object** to keep a cookie cutter or other helper in the blend file
while omitting its geometry, transform, and attachment from W3D/W3X export. This
also keeps long helper names out of export name validation. The setting applies
to the individual object; its children retain their own export settings. Viewport
visibility and the W3D **Hide** flag remain separate from export inclusion.

### Map materials and missing textures

W3D vertex-material imports keep the material pass stack, both texture stages,
each stage's UV channel, and per-pass shader settings. Texture IDs select from
the file's texture table independently of Blender material slots, including
terrain passes that share a detail texture. The viewport approximates common
detail and alpha blends; engine-specific texture mapping and lighting can still
look different in-game. Faces with different texture IDs receive separate
Blender materials. Exporting those face-specific material assignments remains
limited; uniform terrain pass stacks support import and export.

Missing textures do not stop an import. Use **File > External Data > Find Missing
Files**, then select your texture folder. Missing images retain file references
so Blender can relink them, including textures used by secondary stages.

### Game bone directions

Imported armatures show directional controls for recognized OpenW3D pivots in
Object and Pose Mode. For an existing import, select the armature and enable
**Object Properties > W3D Object > Game Bone Directions**. Toggle it off to
return to Blender's standard bone shapes, or off and on to refresh after
renaming bones. The selected bone's **W3D Properties** panel describes its axes.

| Bone name (case-insensitive) | Arrow direction | Rotation ring |
| --- | --- | --- |
| `MUZZLE*` | Local +X, firing direction | None |
| `TURRET` | Local +X, forward | Around local Z, turret turn |
| `BARREL` | Local +X, forward | Around local Y, barrel pitch |
| `WheelP*` | Local -Z, suspension toward ground | None |
| `WheelC*` | Local +Z, wheel axle | Around local Z, wheel rotation |
| `WheelF*` | Local +Y, fork hinge | Around local Y, fork rotation |
| `WheelT*` | Local +Z, suspension translation axis | None |

Arrows follow each pivot's current orientation, including parent transforms.
They do not automatically align incorrectly oriented pivots with the ground or
barrel. Bone transforms, animation, and exported axes retain their original
meaning. Other bone names keep Blender's standard display, and existing custom
shapes supplied by an animator are preserved. Edit Mode uses Blender's native
bone display; enable **Armature Data > Viewport Display > Axes** to inspect all
three axes when editing a pivot.

These conventions come from OpenW3D's
[weapon firing](https://github.com/w3dhub/OpenW3D/blob/main/Code/Combat/weapons.cpp#L801),
[vehicle aiming](https://github.com/w3dhub/OpenW3D/blob/main/Code/Combat/vehicle.cpp#L1154),
[wheel documentation](https://github.com/w3dhub/OpenW3D/blob/main/Code/wwphys/wheel.h#L57),
and [fork rotation](https://github.com/w3dhub/OpenW3D/blob/main/Code/wwphys/wheel.cpp#L529).

### Dazzle types and dazzle.ini

Open **Edit > Preferences > Add-ons**, search for **W3D**, and expand the
**Import/Export Westwood W3D Format** add-on. Use the **Dazzle INI** file picker
to select your game's `dazzle.ini`. Names from its `[Dazzles_List]` section are
added to the built-in dazzle presets. Save Preferences if Blender's automatic
preference saving is disabled.

On a dazzle object, choose the preset in **Object Properties > W3D Object >
Dazzle**. Set **Export Type** to **Dazzle** when creating a new one. Imported names missing from the preset list,
such as `REN_HEADLIGHT_SMALL`, use **Custom** and remain editable in **Custom
Dazzle Type**. The exact name survives saving the blend file and exporting W3D,
even without that game's INI. This setting supplies type names; it does not
locate missing texture files or reproduce the game's dazzle rendering.

### HLOD light references

W3D imports and exports preserve the Max exporter's HLOD light array (`0x707`),
including each reference's identifier and parent bone. Imported references
appear as empties with **Object Properties > W3D Object > HLOD Role** set to
**Light Reference**. They follow the same export-inclusion rules as Aggregate
and Proxy attachments. These entries reference lights; they do not contain
light color, intensity, or other Blender light settings.

### Tangent and binormal chunks

W3D imports read tangent (`0x60`) and binormal (`0x61`) vectors both on meshes
and inside material passes, including prelit passes. The latter form is written
by the Max exporter's **Tangents** geometry option. Import enables Blender's
**Object Properties > W3D Object > Geometry Flags > Tangents** setting for these meshes.

With that setting enabled, W3D export writes the vectors in the first material
pass and sets the NPatchable and vertex-channel flags. Shader materials continue
to receive mesh-level tangent data. Blender recalculates exported vectors from
the current mesh and UV coordinates; imported custom tangent vectors are not
used as a replacement for Blender's tangent calculation. Meshes need UVs and a
material pass to export the Tangents geometry option.

Reference: [Max exporter tangent serialization and material-pass placement](https://github.com/w3dhub/max2w3d/blob/master/w3dmaxtools/Source/w3dexport.cpp).

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
