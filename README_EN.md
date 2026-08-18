# Pottery Capacity Estimation Tools

A set of experimental Python tools for estimating pottery vessel capacity from either 3D meshes or 2D archaeological drawings.

The repository currently contains three complementary workflows:

1. **PotteryVolumeCalculator (voxel-fluid)** — estimates retained liquid directly from voxelized 3D free-space connectivity.
2. **PotteryRadialSections** — derives radial section profiles from a 3D mesh and estimates capacity using section-based numerical models.
3. **PotteryDrawingCapacity** — digitizes left/right inner profiles from a 2D drawing and evaluates them with the same `single` integration core used by PotteryRadialSections.

The section/profile workflows share `pottery_volume_core.py`. The voxel-fluid workflow is methodologically independent and does not call the shared profile-integration core.

## Contents

- [PotteryVolumeCalculator — voxel-fluid method](#potteryvolumecalculator-v131)
- [PotteryRadialSections — radial-section method](#potteryradialsections-v060)
- [PotteryDrawingCapacity — drawing-based method](#potterydrawingcapacity-v060)

---


## PotteryVolumeCalculator v1.3.1

Experimental Python CLI for estimating the **maximum retained liquid capacity** of a pottery 3D mesh using a voxel-based fluid-space method.

The target quantity is the volume retained immediately before liquid first reaches the exterior, assuming the vessel is upright with **+Z upward** and gravity in the -Z direction.

### Overview

PotteryVolumeCalculator operates directly on the 3D free space defined by a mesh. It does not require an explicit inner-surface extraction or an artificial horizontal cap at the rim.

Core workflow:

```text
PLY / OBJ
  -> geometry-preserving preprocessing and topology QA
  -> exact-coordinate vertex weld
  -> conversion to internal millimetres
  -> whole-mesh surface voxelization
  -> cavity-seed validation
  -> height-limited 3-D flood fill
  -> binary search for safe / first-spill levels
  -> fluid voxel count
  -> retained volume
```

The voxel-fluid implementation is independent of the section/profile-based `PotteryRadialSections`, `PotteryDrawingCapacity`, and `PotteryVolumeCore` workflow.

### Capacity definition

The reported capacity is:

> The maximum liquid volume that can be retained by the existing geometry immediately before the connected fluid region first reaches the exterior.

For a complete vessel this approximates the vessel's maximum retained capacity. For a partially preserved vessel with a continuous bottom and walls, the result is the capacity retained by the **surviving geometry**, not a reconstruction of the original complete vessel.

### Intended input

- PLY or OBJ triangular mesh
- known coordinate unit: `mm`, `cm`, or `m`
- vessel oriented with +Z upward
- continuous geometry sufficient to define a fluid-retaining cavity

Large holes, missing walls, or openings are treated as potential leakage paths. The program does not automatically reconstruct missing vessel geometry.

### Installation

Python 3 is required. Install either the core dependencies:

```bash
python3 -m pip install -r requirements-core.txt
```

or the full dependency set including the optional PyMeshLab cross-check:

```bash
python3 -m pip install -r requirements.txt
```

Primary dependencies are NumPy, SciPy, Trimesh, and Pillow. PyMeshLab is optional and is not required for the capacity calculation.

### Usage

#### Single-pitch calculation

```bash
python3 vessel_voxel_volume.py model.ply --unit m --pitch 1.0
```

`--pitch` is always specified in millimetres, regardless of the input coordinate unit.

#### Multi-pitch validation

```bash
python3 vessel_voxel_volume.py model.ply --unit m --validate
```

Validation mode runs three independent full pipelines:

```text
2.0 mm
1.0 mm
0.5 mm
```

Use `--output-dir` for reproducible runs that should not share files with earlier executions.

```bash
python3 vessel_voxel_volume.py model.ply --unit m --pitch 1.0 --output-dir run_01
```

Environment diagnostics:

```bash
python3 vessel_voxel_volume.py --diagnose-env
```

### Method

#### 1. Geometry-preserving preprocessing

The processing path removes unreferenced vertices and merges vertices only when their XYZ coordinates are **exactly identical**. No tolerance-based welding, automatic hole filling, non-manifold repair, or vertex displacement is applied.

#### 2. Surface voxelization

The complete mesh surface is voxelized at pitch `p`. Surface voxels are treated as barriers; candidate liquid occupies connected free voxels.

Because the barrier has finite voxel thickness, the result is resolution-dependent. Multi-pitch validation is therefore part of the intended research workflow.

#### 3. Cavity-seed validation

A candidate seed must represent the vessel cavity rather than a free-space region between wall surfaces. The current validation logic requires a candidate to be enclosed in a local horizontal section, connected to the exterior when the full height is allowed, and not already leaking when movement is restricted to the seed elevation.

#### 4. First-spill search

For each candidate water level, movement is allowed only through free voxels at or below that level. A 6-connected flood fill starts from the validated cavity seed.

Connectivity is monotonic as the permitted maximum Z increases, so a binary search identifies:

- the highest non-leaking level (`safe level`), and
- the first leaking level (`spill level`).

#### 5. Volume

At the safe level, if `N` connected fluid voxels are retained at voxel pitch `p` mm:

```text
V = N * p^3  [mm^3]
```

Results are also reported in mL and L.

### QA and audit outputs

The workflow records, among other diagnostics:

- vertex/face counts before and after exact-coordinate welding
- topology summaries and non-manifold/boundary diagnostics
- voxel grid dimensions and surface-voxel counts
- cavity-seed candidates and selected seed
- safe and spill levels
- fluid-surface and spill-region QC point clouds
- per-run JSON results
- multi-pitch CSV/JSON summaries

QC point clouds can be overlaid on the source mesh in software such as CloudCompare.

### Validation summary

Validation dataset:

**Human-face ink-inscribed pottery, Nara period**  
Goten / Ninomiya Site, Iwata City, Shizuoka, Japan  
Collection: Iwata City Archaeological Center  
Legashizu3D model LS0015  
Source: https://lega-shizu.com/legashizu3d/archives/data/117

Input used for validation: `0015Jinmen_small.ply`, oriented with +Z upward.

| voxel pitch | safe level | first-spill upper level | fluid voxels | capacity | total time |
|---:|---:|---:|---:|---:|---:|
| 2.0 mm | 240.0 mm | 242.0 mm | 725,340 | **5.802720 L** | 14.84 s |
| 1.0 mm | 241.0 mm | 242.0 mm | 5,917,481 | **5.917481 L** | 33.25 s |
| 0.5 mm | 240.5 mm | 241.0 mm | 47,583,957 | **5.947995 L** | 132.08 s |

Observed refinement:

```text
5.802720 -> 5.917481 -> 5.947995 L
```

The 1.0 mm to 0.5 mm difference is **30.514 mL**, or approximately **0.513% of the 0.5 mm result**. The spill upper level varied by 1 mm across the three resolutions.

A three-point empirical convergence diagnostic gave an estimated order of approximately 1.91 and an extrapolated value of approximately 5.959 L. This extrapolation is a diagnostic model value, **not a measured capacity**. The finest directly computed value, 5.947995 L, is the primary detailed result for this dataset.

### Texture-UV seam note

The validation audit showed that Trimesh's normal texture handling can re-index vertices along face-corner UV discontinuities. In this dataset that produced apparent pre-weld boundary edges that could be mistaken for archaeological sherd joins.

For v1.3.1, `archaeological/raw_*` derivatives and raw-boundary/spill proximity diagnostics are therefore disabled. This change does **not** alter the voxel-fluid capacity algorithm. Post-weld topology outputs remain QA products and must not be interpreted as automatic sherd identification.

### Output structure

Typical validation output:

```text
<stem>_PotteryVolume_v1/
├── archaeological/
│   ├── after_exact_weld_boundary_stats.json
│   ├── after_exact_weld_components.csv
│   ├── after_exact_weld_components.json
│   └── after_exact_weld_components_colored.ply
├── processed/
├── qa/
├── pitch_2mm/
├── pitch_1mm/
├── pitch_0p5mm/
├── validation_summary.csv
└── validation_summary.json
```

### Limitations

- Capacity depends on voxel pitch; convergence should be checked on representative data.
- Input orientation directly controls the gravity/spill direction.
- Large geometric gaps may cause early leakage or failure to identify a stable cavity.
- Very fine pitch values can require substantial memory because the voxel grid is three-dimensional.
- The method estimates capacity of the represented geometry; it does not infer missing original vessel geometry.
- Archaeological sherd-boundary detection is outside the current capacity algorithm.

### Relationship to the section-based tools

```text
Voxel-fluid family
3-D mesh
  -> surface voxels / free-space topology
  -> first-spill connectivity
  -> retained voxel volume

Section/profile family
3-D mesh or 2-D drawing
  -> sectional profiles / areas
  -> PotteryVolumeCore
  -> numerical integration
```

Agreement between the two families is treated as validation evidence, not as a calibration objective.



---


## PotteryRadialSections v0.6.0

Python CLI for estimating pottery capacity from **radial longitudinal sections extracted from a 3D mesh**. The program estimates a vertical rotation axis from horizontal inner-surface sections, extracts radial inner profiles, and evaluates capacity with several section-based models.

Capacity integration is delegated to the shared `pottery_volume_core.py` module.

> **Development status (August 2026):** the current radial-section workflow is treated as a stable v0.6.0 baseline. Further investigation of spill-level modeling is being handled separately from the radial-section geometry/integration workflow.

### Overview

```text
3-D mesh
  -> horizontal mesh sections
  -> inner contour extraction
  -> robust ellipse fits
  -> rotation-axis estimate
  -> radial longitudinal sections
  -> inner radius profiles r(theta, z)
  -> PotteryVolumeCore
  -> capacity estimates
```

The current implementation supports four capacity modes:

- `single`
- `optimized`
- `angular`
- `ellipse`

`single` uses the same numerical integration function as `PotteryDrawingCapacity`, allowing 3D-derived and 2D-digitized profiles to be compared without duplicating the capacity integrator.

### Intended input

- PLY or OBJ triangular mesh
- vessel oriented with +Z upward
- known coordinate unit: `mm`, `cm`, or `m`
- inner vessel surface present for capacity calculation
- complete or nearly complete vessel geometry is preferred

The outer surface can be used for rotation-axis estimation, but the current capacity modes require the actual inner surface.

### Installation

Python 3.10+ is recommended.

```bash
python3 -m pip install -r requirements.txt
```

Main dependencies: NumPy, SciPy, Trimesh, and Matplotlib. `pottery_radial_sections.py` and `pottery_volume_core.py` must be importable from the same environment.

Numerical core self-test:

```bash
python3 pottery_volume_core.py --self-test
```

### Quick start

```bash
python3 pottery_radial_sections.py vessel.ply --unit m
```

Default settings include:

```text
axis surface         inner
horizontal sections 20
radial angle step    30 degrees
volume Z step        0.5 mm
volume modes         all
```

Use a dedicated output directory for formal comparisons:

```bash
python3 pottery_radial_sections.py vessel.ply --unit m --output-dir run_30deg
```

### Rotation-axis estimation

The vessel height is sampled with horizontal XY sections. By default, 20 equal-height intervals are used and the section is taken at each interval midpoint.

For each usable section:

1. mesh-plane intersections are assembled into closed contours;
2. outer and inner contours are classified;
3. the selected contour is resampled by arc length;
4. a robust ellipse is fitted;
5. ellipse centers are collected across Z;
6. center outliers are rejected using a 2-D MAD criterion;
7. the arithmetic mean of accepted centers defines the XY position of a Z-parallel rotation axis.

A linear center drift with Z is reported as a diagnostic tilt, but v0.6.0 does not automatically rotate or deform the source geometry to remove it.

Axis surface modes:

```bash
--axis-surface inner   # default and recommended for capacity work
--axis-surface outer
--axis-surface both    # fit both; final axis uses inner
```

Horizontal sampling can be controlled by relative subdivision:

```bash
--z-sections 20
```

or an absolute interval:

```bash
--z-step-mm 10
```

### Radial section extraction

After the axis is estimated, vertical planes passing through that axis are extracted at a regular angular interval.

Default:

```bash
--angle-step 30
```

Examples:

```bash
--angle-step 15
--angle-step 10
--angle-step 5
```

A 30-degree interval produces 12 radial half-sections and six opposing full section planes.

At each Z sample along a radial ray, the current inner-profile extractor interprets the smallest positive intersection radius as the inner surface when multiple wall intersections are available. Deduplication, short-gap handling, longest finite-run selection, and profile-span reliability checks are used to suppress local failures.

### Capacity modes

#### `single`

One full longitudinal section is represented by two opposing inner profiles, `r_A(z)` and `r_B(z)`.

The equivalent horizontal area is:

```text
A(z) = pi/2 * [r_A(z)^2 + r_B(z)^2]
```

The two profiles are interpolated to a common Z grid and integrated by the shared `PotteryVolumeCore` single routine. This is the same numerical method used by the 2D drawing tool.

```bash
python3 pottery_radial_sections.py vessel.ply --unit m \
  --volume-mode single --single-angle 0
```

#### `optimized`

At each Z, radii from multiple directions are combined using a MAD-based robust estimator. The accepted radii are averaged to form an axisymmetric representative radius `r_opt(z)`, then:

```text
A(z) = pi * r_opt(z)^2
```

This mode reduces directional sensitivity but intentionally collapses non-axisymmetric variation into a representative radius.

#### `angular`

This mode retains directional variation and approximates the polar cross-sectional area directly:

```text
A(z) = 1/2 * integral r(theta, z)^2 dtheta
```

For uniformly spaced directions the integral is discretized over the sampled angles. Missing angular values are periodically interpolated only when the minimum valid-direction criterion is satisfied.

#### `ellipse`

Horizontal inner ellipses obtained during axis estimation provide semi-major and semi-minor axes `a(z)` and `b(z)`:

```text
A(z) = pi * a(z) * b(z)
```

The ellipse mode uses a different geometric representation from the radial profiles and is intended primarily as an independent section-model QA estimate.

Select methods with:

```bash
--volume-mode all
--volume-mode single
--volume-mode optimized angular
--volume-mode ellipse
--volume-mode none
```

### PotteryVolumeCore

`pottery_radial_sections.py` is responsible for mesh interpretation, axis estimation, profile extraction, validity decisions, physical bounds, and output generation. Numerical integration is performed by `pottery_volume_core.py`.

The core is source-agnostic: it does not know whether a profile originated from a 3D mesh or a 2D drawing.

Detailed numerical specifications are documented in `docs/volume_core.md`.

### Output

Typical 30-degree output:

```text
<stem>_RadialSections_30deg/
├── metadata.json
├── sections_summary.csv
├── axis_estimation/
│   ├── horizontal_sections.csv
│   ├── axis_summary.csv
│   ├── rotation_axis_edges.ply
│   ├── section_centers_points.ply
│   ├── all_horizontal_section_points.ply
│   └── all_fitted_ellipse_points.ply
├── full_sections/
├── radial_half_sections/
├── volume/
│   ├── volume_summary.csv
│   ├── volume_summary.json
│   ├── radial_inner_profiles.csv
│   ├── radial_inner_profile_points.ply
│   ├── optimized_rotation_profile.csv
│   ├── angular_area_profile.csv
│   └── horizontal_ellipse_area_samples.csv
└── visualization/
    ├── axis_validation_xz.png
    ├── axis_validation_yz.png
    ├── axis_centers_xy.png
    ├── horizontal_sections_oblique.png
    ├── full_sections_oblique.png
    └── radial_half_sections_oblique.png
```

Coordinate-preserving PLY outputs are written in the source coordinate system/unit and can be overlaid on the original mesh for audit.

### Validation summary

Validation dataset: `0015Jinmen_small.ply`, the same LS0015 archaeological pottery model used for the voxel-fluid validation.

Input geometry:

```text
350,070 vertices
700,000 triangles
X extent 231.424 mm
Y extent 229.222 mm
Z extent 283.793 mm
```

#### Axis QA

Using 20 horizontal intervals and the inner-surface ellipse centers:

```text
valid / used horizontal sections  19 / 20
axis X                           138.092372 mm
axis Y                          -107.491406 mm
RMS radial center offset           2.3259 mm
diagnostic centerline tilt         1.2695 degrees
```

The tilt is reported but not automatically corrected.

#### Standard 30-degree results

Volume Z step: 0.5 mm.

| method | capacity | difference from voxel-fluid 0.5 mm |
|---|---:|---:|
| single 0/180 deg | **6.238484 L** | +4.88% |
| optimized | **5.986216 L** | +0.64% |
| angular | **6.017601 L** | +1.17% |
| ellipse | **6.000679 L** | +0.89% |
| voxel-fluid 0.5 mm, independent method | **5.947995 L** | - |

The voxel-fluid result is **not** treated as ground truth or as a calibration target for RadialSections.

#### Directional sensitivity: six full sections

Each of the six opposing section planes at 30-degree intervals was evaluated independently with the `single` method.

```text
mean       6.109743 L
sample SD  0.164891 L
CV         2.70%
minimum    5.895449 L
maximum    6.318373 L
range      0.422925 L
```

This quantifies the directional uncertainty introduced when one full longitudinal section is assumed to represent the complete vessel.

#### Directional sensitivity: twelve half-sections

Each radial half-profile was independently revolved through 360 degrees using its own profile extent.

```text
mean       6.184020 L
sample SD  0.190278 L
CV         3.08%
minimum    5.891436 L
maximum    6.498725 L
range      0.607290 L
```

Using a common upper integration bound for all 12 directions, the mean half-section rotational volume was **6.017393 L**, compared with **6.017601 L** from the 30-degree angular method. The difference was approximately **0.208 mL (0.00345%)**, providing an internal consistency check between the extracted radial profiles and angular integration.

#### Angular-step convergence

To isolate angular shape-integration discretization from changes in the upper integration bound, the 30/15/10/5-degree runs were re-integrated with a common upper bound of 241.114 mm. The 5-degree run is used only as the finest computed reference in this test.

| angle step | optimized | difference from 5 deg | angular | difference from 5 deg |
|---:|---:|---:|---:|---:|
| 30 deg | 5.972111 L | -0.2196% | 6.003301 L | -0.0867% |
| 15 deg | 5.986187 L | +0.0156% | 6.008410 L | -0.0017% |
| 10 deg | 5.982442 L | -0.0470% | 6.009079 L | +0.0094% |
| 5 deg | 5.985256 L | reference | 6.008513 L | reference |

For this vessel, angular shape integration was already within approximately 0.22% of the 5-degree result at 30 degrees, and both `optimized` and `angular` were within 0.05% at 15 and 10 degrees.

This convergence statement concerns the **sectional shape integration**. Upper-bound/spill-level modeling is a separate issue from the current radial-section baseline.

### QA and reproducibility

For research use, retain at least:

- source mesh identity/hash
- program and `PotteryVolumeCore` versions
- input units
- axis parameters and axis-surface mode
- horizontal-section settings
- radial angle step and Z step
- extracted radial profiles
- physical integration bounds
- `volume_summary.csv/json`
- axis and profile QC outputs

A scalar capacity without the actual geometric profile/area representation used for integration should not be considered independently auditable.

### Limitations

- The default axis is Z-parallel; diagnosed centerline tilt is not automatically corrected.
- Horizontal inner/outer contour classification is heuristic and is most reliable for relatively simple complete vessels.
- Radial inner-intersection classification can be challenged by complex projections, duplicated surfaces, reconstruction surfaces, or severe noise.
- Capacity modes require an observed inner surface; outer-only models require a separate outer-to-inner reconstruction step.
- A single section is direction-dependent; use multi-direction results when the purpose is whole-vessel capacity estimation.
- Validation to date is based primarily on one archaeological vessel; broader validation across vessel shapes is still required.



---


## PotteryDrawingCapacity v0.6.0

GUI-assisted Python tool for estimating pottery capacity from a **2D archaeological drawing or longitudinal section**. The user calibrates scale, specifies the vertical rotation axis, and digitizes the left and right inner-wall profiles. Capacity is then calculated by the shared `PotteryVolumeCore` `single` method.

### Overview

```text
2-D drawing / section image
  -> rendered working image
  -> manual scale calibration
  -> rotation-axis X position
  -> left and right inner-profile digitization
  -> physical r_left(z), r_right(z)
  -> PotteryVolumeCore
  -> capacity
```

The program is designed to make the geometric observations used for the calculation explicit and auditable rather than attempting fully automatic line recognition in drawings that may contain restoration lines, decoration, annotations, hatching, or variable line weights.

### Supported input

- PNG
- JPEG / JPG
- TIFF / TIF
- BMP
- WEBP
- SVG
- PDF

SVG and PDF are rendered for measurement. Embedded page dimensions or DPI are **not** accepted as the capacity scale; scale is calibrated explicitly in the GUI from two points and a known physical distance.

### Assumptions

The current workflow assumes:

- a longitudinal pottery drawing or section
- both left and right inner-wall profiles are visible
- the drawing is already upright
- the rotation axis is vertical
- a scale bar, grid, or known physical distance is available
- the inner wall can be represented approximately as one radius per Z on each side

### Installation

Python 3.10+ is recommended.

```bash
python3 -m pip install -r requirements.txt
```

Main dependencies for the drawing workflow are NumPy, Pillow, and PyMuPDF. The GUI uses Tkinter from the Python standard library. `pottery_drawing_capacity.py` and `pottery_volume_core.py` must be importable from the same environment.

### Run

Open the GUI without preselecting a file:

```bash
python3 pottery_drawing_capacity.py
```

Open a drawing directly:

```bash
python3 pottery_drawing_capacity.py pottery_section.png
```

Select a PDF page:

```bash
python3 pottery_drawing_capacity.py report.pdf --page 12
```

Numerical self-tests:

```bash
python3 pottery_volume_core.py --self-test
python3 pottery_drawing_capacity.py --self-test
```

### GUI workflow

```text
Open drawing
  -> 1. Scale calibration (two points)
  -> 2. Rotation-axis X
  -> 3. Left inner profile
  -> 4. Right inner profile
  -> Calculate and save
```

#### Scale calibration

Select two points with a known real-world separation and enter that distance in millimetres.

```text
mm_per_pixel = physical_distance_mm / pixel_distance
```

The explicit calibration is recorded in the metadata.

#### Rotation axis

Because the source drawing is assumed to be upright, only the X position of the clicked axis point is used. Radii are measured as horizontal distances from this axis.

#### Inner profiles

Digitize the left and right inner surfaces from bottom to rim. Add more points where curvature changes rapidly. The current implementation uses piecewise linear interpolation between digitized points; it does not automatically apply spline smoothing.

Undo is available during digitization.

### Capacity method

The two sides are converted to non-negative radius profiles:

```text
r_left(z)
r_right(z)
```

After cleaning and sorting the input, both profiles are interpolated onto a common Z grid. The equivalent horizontal area is:

```text
A(z) = pi/2 * [r_left(z)^2 + r_right(z)^2]
```

Equivalently:

```text
r_eq(z) = sqrt([r_left(z)^2 + r_right(z)^2] / 2)
A(z)    = pi * r_eq(z)^2
```

The current shared `single` implementation integrates cross-sectional area over Z with trapezoidal integration.

The default Z interval is 0.5 mm:

```bash
python3 pottery_drawing_capacity.py pottery.png --z-step-mm 0.5
```

The operational upper bound is the common top of the two digitized profiles, i.e. the lower of the two digitized rim elevations.

### Shared PotteryVolumeCore

`pottery_drawing_capacity.py` performs source rendering, calibration, digitization, coordinate conversion, and QC output. It does **not** contain a separate duplicate capacity integrator.

Both:

```text
PotteryDrawingCapacity
PotteryRadialSections --volume-mode single
```

call:

```text
pottery_volume_core.calculate_single_two_sided(...)
```

Therefore, differences between a 3D-derived full section and a 2D-digitized drawing section arise upstream from profile acquisition, scale, axis placement, source generalization, and integration bounds rather than from different `single` capacity code.

Technical details are documented in `docs/volume_core.md`.

### Output

```text
<input>_DrawingCapacity/
├── source_render.png
├── drawing_profile_raw.csv
├── drawing_profile_resampled.csv
├── drawing_volume_summary.csv
├── drawing_volume_summary.json
├── drawing_metadata.json
├── drawing_qc_overlay.png
└── drawing_profile_plot.png
```

Important audit files:

- `source_render.png`: exact rendered source used in the GUI
- `drawing_profile_raw.csv`: user-clicked profile points
- `drawing_profile_resampled.csv`: Z grid, left/right radii, equivalent radius, and area used for integration
- `drawing_metadata.json`: source SHA-256, rendering information, scale points, mm/pixel, axis X, core version, and method
- `drawing_qc_overlay.png`: source drawing with scale line, axis, digitized profiles, and upper bound overlaid

For research use, inspect `drawing_qc_overlay.png` before accepting the scalar capacity result.

### Validation status

The current analytical self-test uses a cylinder with:

```text
radius = 50 mm
height = 100 mm
```

Analytical volume:

```text
0.785398163 L
```

Both the shared core self-test and the Drawing front-end self-test reproduce this value.

This validates the numerical handoff and the shared two-sided integration path, but it does **not** quantify digitization error, scale-calibration error, or graphical generalization in archaeological drawings. A direct validation using the same vessel and section represented both as a 3D mesh section and as an independently published 2D drawing remains a separate empirical test.

### QA and reproducibility

For an auditable drawing-based result, retain:

- original source identity and SHA-256
- rendered working image
- PDF page number or rendering settings where relevant
- scale-calibration points and physical distance
- `mm_per_pixel`
- axis X position
- raw left/right digitized points
- resampled profile used by the core
- `PotteryVolumeCore` version
- numerical integration settings
- QC overlay

### Limitations

- Inner profiles are manually digitized; the tool does not automatically decide which drawing line represents the inner wall.
- The source must be upright with a vertical rotation axis in the current GUI model.
- Scale is only as accurate as the selected reference points and stated real-world distance.
- Piecewise linear interpolation is used between digitized points; no automatic spline or smoothing model is imposed.
- The method represents one longitudinal section as a two-sided equivalent body of revolution. Directional variability of the real vessel is not available from a single drawing.
- A drawing may include archaeological reconstruction or graphical generalization that is not present in a 3D scan; such differences are part of the source evidence, not numerical integration error.



---
