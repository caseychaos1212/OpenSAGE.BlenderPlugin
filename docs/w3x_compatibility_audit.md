# W3X / C&C3 compatibility audit

Audited September 12, 2026, using installed Blender 5.2.0 LTS, build
`fbe6228777e7`, in separate factory-startup background processes.

**Recommendation:** bring in upstream's Blender compatibility improvements through
a reviewed integration, and fix the fork's W3X regressions before using it for
C&C3 export. Successful import/export operator results currently conceal data
loss. Importing the sampled assets completes, but this audit does not establish
visual or animation fidelity.

The initial audit below describes fork commit `727db3e`. Its assessment did
not modify add-on source or original mod assets. Generated XML, snapshots,
scripts, and logs are under ignored `TestResults/w3x-audit/`.

## Follow-up: upstream merge

Upstream `53d77d3` was subsequently merged at the user's request. The 15
conflicted files were resolved while preserving the Renegade workflow, material
passes, hierarchy/animation behavior, and removed updater. Fork-only modules now
use relative imports, the material bridge uses the upstream API helpers, and
extension metadata identifies OpenW3D 0.8.1. The existing animation compatibility
layer supplies both the fork and upstream action-curve entry points. CI includes
Blender 5.2 and uses upstream's corrected download URL.

On Blender 5.2, the merged suite runs 384 tests: **342 pass, 31 fail, and 11
error**. There are no newly failing test IDs relative to the original audit;
`test_bone_visibility_channel_creation` now passes. The remaining 42 failing or
erroring tests predate the merge. W3X remains at 50/56 passing; the export defects
documented below still require separate fixes.

The ten sampled C&C3 workflows also complete after merging, with identical
imported scene summaries and exported XML structure to the original fork.
The existing UV loss and hierarchy differences remain reproducible.

The extension manifest validates with Blender's CLI. Isolated loading under
`bl_ext.merge_audit.io_mesh_w3d` passes registration/unregistration, Renegade
property callbacks, W3D/W3X cube exports, and restoration of the material's
surface render method after export. This checks extension namespace behavior,
not installation into the user's Blender preferences.

Merge test evidence is in `merged-results.json`, `merged-suite.log`,
`extension-smoke.log`, and `extension-smoke/results.json` within the audit
output directory. The initial recommendation and source line references below
are retained as a historical record of the pre-merge findings.

## Versions and test results

| Checkout | Commit | Tests | Passed | Failures | Errors |
| --- | --- | ---: | ---: | ---: | ---: |
| Fork `master` | `727db3e` | 384 | 341 | 31 | 12 |
| Current upstream `master` | `53d77d3` | 364 | 364 | 0 | 0 |
| Common ancestor | `e9b652c` | 364 | 346 | 0 | 18 |

W3X-specific results: the fork passes **50/56**, with five failures and one
error; current upstream passes **56/56**. The fork has 20 more tests overall.
These are each checkout's own unchanged test suites, not identical suites.

The failures are not 43 independent production bugs. For example, one test still
accesses removed `Action.fcurves`, several expect the old AABB tree structure,
and some synthetic attachment arrays reference pivots outside their reduced
test skeletons. The data-loss findings below were reproduced separately using
actual XML files and the supplied mod assets.

## Confirmed fork regressions

### 1. Imported W3X meshes lose UV coordinates on export â€” high priority

In `io_mesh_w3d/common/utils/mesh_export.py:302`, imported material settings
activate the new pass configuration. At line 325, assigning W3X UV coordinates
requires `pass_config is None`, so it is skipped. The W3D texture-stage path
does not populate the fields serialized by W3X's `Mesh.create`.

- Synthetic input: two UV sets, eight coordinates each.
- Fork output: one empty `<TexCoords>` element.
- Upstream output: both eight-coordinate sets retained.
- Actual mod workflows: **51/51 mesh exports had empty UV coordinates** in the
  fork; **0/51** were empty in upstream. These include repeated assets tested
  through both combined and split-file workflows, not 51 unique models.

The relevant export change is in fork commit `b83962f`. Importing shader
materials populates the pass settings unconditionally in
`common/utils/material_import.py:250`. Turning off the Renegade scene toggle
does not avoid this regression; the failing probes used its default off state.

### 2. Hierarchy round-trips accumulate root pivots â€” high priority

`common/utils/hierarchy_import.py:51` creates a bone for every pivot, including
`ROOTTRANSFORM`. `common/utils/hierarchy_export.py:15` also creates a synthetic
root before exporting all pose bones. The importer change in `bc9e4c3` removed
the root-pivot skip and changed how the root transform is stored.

A two-pivot W3X skeleton grows **2 â†’ 3 â†’ 4 â†’ 5 pivots** over three round-trips.
The first output contains duplicate `ROOTTRANSFORM` names. Later imports rename
bones and change parent relationships. The original root translation moves
from the root pivot to an added child. Upstream remains at two pivots and
preserves the root translation.

Real examples: the light tank exports with 13 pivots in the fork versus 12 in
upstream; the minigunner exports with 26 versus 25. Keep the intended Renegade
animation behavior when correcting this shared importer/exporter mismatch;
simply reverting all animation work would have a wider effect.

### 3. W3D material passes overwrite W3X shader settings â€” high priority

`common/utils/material_settings_bridge.py:149` derives `alpha_test` solely from
opacity, and line 180 replaces the texture count with the enabled W3D stage
count. The shared mesh exporter applies this bridge to W3X shader materials.

Direct XML probes show:

- `Opacity=1`, `AlphaTestEnable=true` becomes `AlphaTestEnable=false`.
- A shader with `Texture_0`, `Texture_1`, and `NumTextures=2` exports
  `NumTextures=1`.

Upstream preserves these settings in the same probes (a default true alpha-test
value is omitted from its output). W3X shader values need to remain independent
of the Renegade pass representation, or the bridge needs a lossless mapping.

### 4. Renegade mode changes W3X export mode â€” medium priority

`export_utils.py:46` reads the scene's Renegade workflow flag without checking
the output format. A requested W3X Mesh (`M`) export becomes Hierarchical Model
(`HM`) and emits hierarchy/container nodes. Confirmed with a generated cube.
Scope this behavior to W3D or make the W3X behavior an explicit choice.

## Checks on the supplied C&C3 mod files

Read-only XML inventory found no XML parse errors in:

- `C:\Users\admin\Documents\cc3tools\recovery\tiberiandawn\art\combined`:
  182 W3X files.
- `C:\Users\admin\Downloads\bigtool\source`: 1,533 W3X files, comprising 823
  meshes, 310 collision boxes, 148 containers, 146 hierarchies, and 106 animations.

Ten workflows completed import, export, and re-import on both versions:

| Workflow | Input in the supplied folder | Fork UV loss / mesh exports | Fork / upstream output pivots |
| --- | --- | ---: | ---: |
| Combined tank | `nutltnk.w3x` | 8/8 | 13 / 12 |
| Combined infantry | `nutmngnnr_skn.w3x` | 2/2 | 26 / 25 |
| Combined aircraft + animation | `nutchnk_skn.w3x`, `nutchnk_mov.w3x` | 3/3 | 13 / 12 |
| Combined artillery + animation | `nutarty.w3x`, `nutarty_atk1.w3x` | 18/18 | 24 / 14 |
| Combined building | `nbthlpd.w3x` | 1/1 | 6 / 5 |
| Combined animated building | `nbtpwrplnt.w3x` | 6/6 | 22 / 21 |
| Split tank | `NUTLTNK_CTR.w3x` | 8/8 | 13 / 12 |
| Split aircraft + animation | `NUTCHNK_SKN.w3x`, `NUTCHNK_MOV.w3x` | 3/3 | 13 / 12 |
| Split infantry | `NUTMNGNNR_SKN.w3x` | 2/2 | 26 / 25 |
| Split hierarchy | `NUTLTNK_HRC.w3x` | No meshes | 13 / 12 |

The artillery animation include loads the model again: both versions export 18
meshes in that workflow. This duplication is separate from the fork's UV loss;
the unusually large fork pivot count also needs coverage for repeated imports.

These are structural checks, not rendered comparisons or C&C3 compiler/game
validation. Both versions emitted keyframe-insertion warnings in the aircraft
animation workflow. Animation pose equivalence remains unverified.

## What upstream contributes

The fork is 18 commits ahead of the common ancestor; upstream has six commits
not present in the fork:

| Commit | Change | Recommendation |
| --- | --- | --- |
| `1e59aac` | Blender 5.1 action-curve access and related tests | Reconcile with the fork's existing `animation_compat.py`; keep one consistent approach and update old tests. |
| `1244985` | CI Blender-version matrix changes | Adapt the matrix to the versions this fork intends to support. |
| `feb80cd` | Upstream version/changelog update | Preserve OpenW3D branding and versioning. |
| `95e9ff7`, `79ff60c` | CI Blender download URL fixes | Incorporate the final working configuration. |
| `53d77d3` | Blender 5.2 compatibility and extension packaging | Port the relevant compatibility changes and adapt packaging to this fork. |

The [Blender 5.2 commit](https://github.com/OpenSAGE/OpenSAGE.BlenderPlugin/commit/53d77d38bb39b6aa2414ebfe092fc2a1c3cee1db)
updates material transparency APIs, UV/color access, node setup, the Blender
4.1 auto-smooth guard, XML element truth testing, and package imports. Its
compatibility helpers also need applying to fork-only code such as
`material_settings_bridge.py`; an upstream patch cannot update files upstream
does not have.

A `git merge-tree` preview reports **15 conflicted files**, including the add-on
entry point, shared import/export helpers, mesh/material code, animation code,
and W3D import. No merge was started in the working tree.

Keep the fork's removed updater removed. Upstream still references it, and its
extension manifest uses upstream branding/version metadata. Relative imports
would also need converting in the fork's additional modules for an extension
installation to work consistently.

## Upstream is not a complete C&C3 fidelity guarantee

Additional synthetic probes found two issues shared with current upstream:

- `retrieve_shader_material(..., w3x=False)` has W3X-specific constant names,
  but the mesh export caller does not pass `w3x=True`. `ColorDiffuse` becomes
  `DiffuseColor` in generated XML in both versions.
- A supplied shader `TechniqueIndex=2` becomes `0` in both versions.

These are observed serialization differences, not regressions introduced by
this fork. Verify the shader constants and technique against the mod's shader
requirements as part of C&C3 export validation. Upstream's passing tests do not
cover full preservation of these values.

## Recommended integration order

1. Preserve the confirmed UV, hierarchy, and shader-setting probes as focused
   regression tests with assertions on serialized output and repeated imports.
2. Fix the W3X regressions in shared code, preserving the Renegade behavior that
   motivated the fork. Restrict W3D workflow overrides by format.
3. Integrate upstream's Blender compatibility work, consolidate action-curve
   access, and adapt CI and optional extension packaging.
4. Re-run W3D, common, and W3X suites. Classify/update intentional test changes
   individually; do not weaken assertions just to obtain a passing suite.
5. Validate sampled mod output through its asset compiler and inspect textured
   models and animation poses before relying on production exports.

## Local evidence and reproduction

`TestResults/w3x-audit/` contains:

- `fork-results.json`, `upstream-results.json`, `base-results.json`: full test
  results with per-test tracebacks; corresponding `*-suite.log` files.
- `fork-probes/`, `upstream-probes/`: synthetic input/output W3X and JSON results.
- `fork-assets/`, `upstream-assets/`: sampled mod exports and JSON results.
- `asset-inventory.json`: read-only inventory of all 1,715 supplied W3X files.
- `merge-preview.txt`: merge-conflict preview.
- `run_suite.py`, `run_probes.py`, `run_assets.py`, `inventory_assets.py`,
  `summarize_results.py`: local audit scripts.
- `upstream/`, `base/`: isolated source snapshots; their updater dependency is
  the pinned upstream commit `981aa2984117a1c686b7fa40d086794ce1c7665e`.

From the repository root, re-run the fork suite with PowerShell:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' `
  --factory-startup -noaudio -b --python-exit-code 1 `
  --python TestResults/w3x-audit/run_suite.py -- `
  . TestResults/w3x-audit/fork-results.json
```

For `run_probes.py` or `run_assets.py`, the second argument is an output
directory instead of a JSON filename. The asset script uses the supplied local
paths and writes only to its output directory. Run suites sequentially because
the existing test helpers share a temporary output location.
