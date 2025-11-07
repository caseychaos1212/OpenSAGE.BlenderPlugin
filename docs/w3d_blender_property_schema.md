# W3D Blender Property & UI Expansion Plan

## Goals

1. Mirror the Renegade-focused options exposed by the 3ds Max exporter so artists can stay inside Blender.  
2. Avoid ad‑hoc properties scattered across mesh/material data; create explicit `PropertyGroup` objects that the exporter and tooling can rely on.  
3. Keep the UX consistent with Blender’s conventions (panels, operators, boxed layouts) while keeping the Max names so existing documentation still applies.

Key references while drafting the plan:

| Area | Reference Snapshot |
| --- | --- |
| Export modal dialog layout | `exporter/max2w3d-master/w3dmaxtools/w3dmaxtools.rc:332-520` |
| Export dialog logic | `exporter/max2w3d-master/w3dmaxtools/Source/Dialog/w3dexportdlg.cpp:1-240` |
| Node-level roll-up (export flags, geometry/collision toggles) | `exporter/max2w3d-master/w3dmaxtools/w3dmaxtools.rc:204-360` and `Source/Dialog/w3dexportsettingsdlg.cpp:233-720` |
| Material passes (vertex/shader/texture tabs) | `exporter/max2w3d-master/w3dmaxtools/w3dmaxtools.rc:66-200` and `Source/w3dmaterial.cpp:262-520` |
| Current Blender implementation | `io_mesh_w3d/custom_properties.py`, `io_mesh_w3d/__init__.py`, `io_mesh_w3d/export_utils.py` |

## Export Operator Schema

The existing `ExportW3D` operator only exposes the format/mode selectors plus a handful of toggles. The new schema keeps those but adds properties grouped into logical tabs that match the Max UI.

### Properties

| Property | Type | Modes | Default | Notes |
| --- | --- | --- | --- | --- |
| `export_mode` | Enum (`HM`, `HAM`, `A`, `H`, `M`, `TERRAIN`) | All | `HM` | Adds a `TERRAIN` entry (mapped to Max’ Terrain radio). |
| `smooth_vertex_normals` | Bool | HM, HAM, TERRAIN | `True` | Mirrors `IDC_SMOOTH_VERTICES`. |
| `optimize_collision` | Bool | HM, HAM, M | `True` | `IDC_OPT_COLLISONS`. |
| `deduplicate_reference_meshes` | Bool | HM, HAM | `True` | `IDC_DEDUPLICATE`. |
| `build_new_aabtree` | Bool | HM, HAM, M, TERRAIN | `False` | `IDC_NEWAABTREE`. |
| `use_existing_skeleton` | Bool | HM, HAM, A | `False` | Already present; now paired with file path inputs. |
| `existing_skeleton_path` | String (filepath) | HM, HAM, A | empty | Exposed when `use_existing_skeleton` is true; uses Blender’s file picker. |
| `animation_frame_start` | Int | HAM, A | Scene start | Equivalent to `IDC_FRAMES_SPIN`. |
| `animation_frame_end` | Int | HAM, A | Scene end | Equivalent to `IDC_FRAMES_TO_SPIN`. |
| `review_log` | Bool | All | `False` | Shows the export log in a popup after completion. |
| `force_vertex_materials` | Bool | Mesh exports | `False` | Existing option, remains. |
| `individual_files` | Bool | W3X HM/H exports | `False` | Existing option, remains. |
| `create_texture_xmls` | Bool | W3X mesh exports | `False` | Existing option, remains. |

### UI Layout

* **Top section** retains Format + Mode boxes. Selecting `TERRAIN` hides animation/skeleton widgets and shows only the smoothing/AABTree toggles.  
* **Settings Box** replicates Max tabs as collapsible Blender boxes:
  * `General`: `smooth_vertex_normals`, `optimize_collision`, `build_new_aabtree`, `deduplicate_reference_meshes`.
  * `Skeleton`: `use_existing_skeleton`, `existing_skeleton_path`, `force_vertex_materials`.
  * `Animation`: `animation_frame_start`, `animation_frame_end`, `animation_compression`.
  * `Output`: `review_log`, `individual_files`, `create_texture_xmls`.
* Use `layout.prop` conditionals identical to Max’ logic (e.g., frame fields only when animation is part of the mode).

### Data Plumbing

* Store the new fields in `context.scene[w3dExportSettings]` along with the existing ones so presets survive across Blender sessions.
* Extend `export_settings` dict in `ExportW3D.execute` to pass the new switches into `export_utils.save_data`.
* Update `export_utils.retrieve_data` and downstream exporters so they respect the new options (e.g., skip smoothing when disabled, load external skeleton path, limit animation ranges to the requested frame span).
* Capture exporter logs (info/warnings) into a buffer and drive a lightweight modal operator when `review_log` is enabled.

## Object-Level Settings

The Max plugin edits per-node data via app-data chunks. In Blender we will add a dedicated `PropertyGroup` and attach it to `Object`, so both Mesh and Empty objects can carry the flags.

### PropertyGroup Definition

```python
class W3DObjectSettings(PropertyGroup):
    export_transform: BoolProperty(default=True)
    export_geometry: BoolProperty(default=True)
    geometry_type: EnumProperty(
        items=REN_EXPORT_GEOMETRY_TYPES,  # Normal, CamParal, OBBox, AABox, CamOrient, NullLOD, Dazzle, Aggregate, CamZOrient
        default='NORMAL'
    )
    static_sort_level: IntProperty(min=0, max=32, default=0)
    screen_size: FloatProperty(min=0.0, default=1.0)
    dazzle_name: EnumProperty(items=load_dazzle_list())
    geom_hide: BoolProperty(name="Hide")
    geom_two_sided: BoolProperty(name="Two Sided")
    geom_shadow: BoolProperty(name="Shadow")
    geom_vertex_alpha: BoolProperty(name="Vertex Alpha")
    geom_z_normal: BoolProperty(name="Z Normal")
    geom_shatter: BoolProperty(name="Shatter")
    geom_tangents: BoolProperty(name="Tangents")
    geom_keep_normals: BoolProperty(name="Keep Normals")
    geom_prelit: BoolProperty(name="Prelit")
    geom_always_dyn_light: BoolProperty(name="Always Dyn Light")
    coll_physical: BoolProperty(name="Physical")
    coll_projectile: BoolProperty(name="Projectile")
    coll_vis: BoolProperty(name="Vis")
    coll_camera: BoolProperty(name="Camera")
    coll_vehicle: BoolProperty(name="Vehicle")
```

Additional helpers:

* `load_dazzle_list()` reads a configurable INI/JSON (defaulting to `exporter/max2w3d-master/w3dmaxtools/Content/dazzle.ini`) once at register time.  
* For linked duplicates, add an operator “Apply W3D Settings to Instances” that copies the active object’s `W3DObjectSettings` to every selected linked duplicate (mirrors Max’ instance sync).

### UI Layout

Split the existing `MESH_PROPERTIES_PANEL_PT_w3d` panel into:

1. **W3D – Object Type**: retains the mesh type selector (`MESH/BOX/DAZZLE/GEOMETRY/BONE_VOLUME`) because that data drives collision box export.  
2. **W3D – Export Flags**: shows `export_transform`, `export_geometry`, `geometry_type`, `static_sort_level`, `screen_size`.  
3. **W3D – Geometry Flags**: checkboxes for the ten geometry flags plus dazzle picker (enabled only when `geometry_type == 'DAZZLE'`).  
4. **W3D – Collision Flags**: the five collision toggles (always available when `export_geometry` is true or the mesh type is BOX).

Selection helpers from the Max “W3D Tools” roll-up can live under the existing `VIEW_3D > W3D Tools` panel as operator buttons (e.g., “Select Physical Collision Meshes”).

### Export Serialization

* Update `io_mesh_w3d/export_utils.py` and lower-level exporters so they consume the new settings instead of the legacy mesh-level flags.  
* Collision box exporting already emits bit masks; extend `box_export` helpers to read the new boolean flags and map them back to bit values identical to Max’.  
* `screen_size` will be written into the `.w3d` HLOD data where applicable (currently pulled from hardcoded lists); the exporter should prefer the user-defined value per object.

## Material-Level Settings

The current add-on stores dozens of scalar properties directly on `Material`. To support Renegade’s multi-pass authoring we need a layered schema.

### Data Model

```python
class W3DStage(PropertyGroup):
    enabled: BoolProperty()
    image: PointerProperty(type=bpy.types.Image)
    clamp_u: BoolProperty()
    clamp_v: BoolProperty()
    no_lod: BoolProperty()
    publish: BoolProperty()
    display: BoolProperty()
    frames: IntProperty(min=0, max=999, default=1)
    fps: FloatProperty(min=0.0, max=60.0, default=15.0)
    animation_mode: EnumProperty(items=REN_STAGE_ANIM_MODES)
    pass_hint: EnumProperty(items=REN_PASS_HINTS)
    alpha_bitmap: PointerProperty(type=bpy.types.Image)

class W3DShaderSettings(PropertyGroup):
    blend_mode: EnumProperty(...)
    custom_src: EnumProperty(...)
    custom_dest: EnumProperty(...)
    write_z: BoolProperty()
    alpha_test: BoolProperty()
    pri_gradient: EnumProperty(...)
    sec_gradient: EnumProperty(...)
    depth_compare: EnumProperty(...)
    detail_color: EnumProperty(...)
    detail_alpha: EnumProperty(...)

class W3DMaterialPass(PropertyGroup):
    name: StringProperty()
    ambient: FloatVectorProperty(...)
    diffuse: FloatVectorProperty(...)
    specular: FloatVectorProperty(...)
    emissive: FloatVectorProperty(...)
    specular_to_diffuse: BoolProperty()
    opacity: FloatProperty()
    translucency: FloatProperty()
    shininess: FloatProperty()
    uv_channel_stage0: IntProperty(min=1, max=99, default=1)
    uv_channel_stage1: IntProperty(min=1, max=99, default=1)
    stage0: PointerProperty(type=W3DStage)
    stage1: PointerProperty(type=W3DStage)
    shader: PointerProperty(type=W3DShaderSettings)

class W3DMaterialSettings(PropertyGroup):
    pass_collection: CollectionProperty(type=W3DMaterialPass)
    active_pass_index: IntProperty()
    surface_type: EnumProperty(...)
    material_type: EnumProperty(...)
    attributes: EnumProperty(options={'ENUM_FLAG'})
    recolor fields / environment textures / etc. from the existing schema.
```

Migration plan:

1. Keep the existing top-level enums/fields for backward compatibility but mark them as “legacy” in the UI.  
2. Add an operator “Convert to Pass-Based Material” that ingests the current data and seeds `pass_collection[0]`.  
3. Update exporters to iterate over pass collection(s) and emit the same chunk structures as Max.

### UI Layout

Rework `MATERIAL_PROPERTIES_PANEL_PT_w3d` into three collapsible sections:

1. **Material Overview** – shows material type, surface type, high-level attributes, recolor/environment toggles (mirrors the “Surface Type” dialog in Max).  
2. **Pass Stack** – list UI (similar to modifiers) with add/remove/reorder buttons. Selecting a pass reveals sub-panels:  
   * `Pass – Vertex` (colors, opacity, UV channel selectors)  
   * `Pass – Shader` (blend/gradient/depth options)  
   * `Pass – Stage 0/Stage 1` (texture settings, animation controls, alpha bitmap toggles)  
3. **Legacy Properties** – collapsed by default, exposing the old flat fields for scenes created before the migration.

### Export Integration

* Modify `io_mesh_w3d/common/utils/material_export.py` (new module) to convert the pass data into the same structures Max writes (`W3DMaterialParamID`).  
* Extend selection utilities (e.g., “Select Alpha Meshes”) to check the per-stage `alpha_bitmap` bools in the new property group.

## Implementation Outline

1. **Data layer**  
   * Add the new property groups to `io_mesh_w3d/custom_properties.py`.  
   * Register them in `io_mesh_w3d/__init__.py` and attach to `Object`, `Material`, and `Scene`.  
2. **UI layer**  
   * Replace the single mesh/material panels with the split structure described above.  
   * Add operators for copying object settings to selected instances, managing pass collections, loading dazzle lists, and reviewing exporter logs.  
3. **Exporter plumbing**  
   * Update `export_utils.py`, `w3d/export_w3d.py`, and related helpers to honor the new flags.  
   * Introduce a logging buffer + modal popup invoked when `review_log` is enabled.  
   * Ensure defaults match the Max exporter by cross-checking `W3DExportSettings` in `exporter/max2w3d-master/w3dmaxtools/Redist/w3dexport.h`.
4. **Backwards compatibility**  
   * Provide migration utilities (operators) for old scenes.  
   * Keep the old custom properties readable so existing `.blend` files export unchanged until the user opts in.

This plan establishes the schema and UI contracts needed for the Renegade feature parity work. The next milestones can now tackle the actual property definitions, UI code, and exporter wiring in manageable chunks.
