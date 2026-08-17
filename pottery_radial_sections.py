#!/usr/bin/env python3
"""
PotteryRadialSections
Version 0.2.0

Extract longitudinal mesh sections through a Z-axis-aligned vessel center.

For an angular interval of 30 degrees:
- 6 unique full section planes are produced: 0/180, 30/210, ... 150/330.
- 12 radial half-sections are produced: 0, 30, ... 330 degrees.

v0.2 additions:
- Section point clouds are exported in the ORIGINAL input coordinate system/unit,
  so they can be overlaid directly on the source mesh in CloudCompare etc.
- CSV files retain both original/native XYZ and mm-reporting coordinates.
- Combined color-coded point clouds are exported for all full sections and all rays.
- Reference oblique 3D images show section positions on the original mesh.

This program ONLY extracts raw mesh/plane intersections. It does not yet
classify inner/outer vessel walls, estimate the rotation axis from horizontal
sections, reconstruct a surface of revolution, or calculate volume.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
import trimesh

__version__ = "0.2.0"

UNIT_SCALE_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def load_geometry(path: Path) -> trimesh.Trimesh:
    """Load geometry without texture-UV re-indexing for PLY files."""
    suffix = path.suffix.lower()
    if suffix == ".ply":
        from trimesh.exchange.ply import load_ply
        from trimesh.resolvers import FilePathResolver

        with path.open("rb") as f:
            data = load_ply(
                f,
                resolver=FilePathResolver(str(path.parent)),
                fix_texture=False,
                skip_materials=True,
                prefer_color="vertex",
            )
        mesh = trimesh.Trimesh(
            vertices=np.asarray(data["vertices"], dtype=np.float64),
            faces=np.asarray(data["faces"], dtype=np.int64),
            process=False,
            validate=False,
        )
        # Preserve vertex colors when available for possible downstream use.
        vc = data.get("vertex_colors")
        if vc is not None and len(vc) == len(mesh.vertices):
            try:
                mesh.visual.vertex_colors = np.asarray(vc, dtype=np.uint8)
            except Exception:
                pass
    else:
        loaded = trimesh.load(str(path), process=False, force="mesh")
        if isinstance(loaded, trimesh.Scene):
            geoms = [
                g for g in loaded.geometry.values()
                if isinstance(g, trimesh.Trimesh)
                and len(g.vertices) > 0
                and len(g.faces) > 0
            ]
            if not geoms:
                raise ValueError("No triangular mesh geometry found.")
            mesh = trimesh.util.concatenate(geoms)
        elif isinstance(loaded, trimesh.Trimesh):
            mesh = loaded
        else:
            raise TypeError(f"Unsupported mesh type: {type(loaded)}")

    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError("Input mesh has no vertices or faces.")
    if not np.isfinite(mesh.vertices).all():
        raise ValueError("Input mesh contains NaN or Inf coordinates.")
    return mesh


def determine_axis_center(
    mesh: trimesh.Trimesh,
    method: str,
    center_x: float | None,
    center_y: float | None,
) -> tuple[float, float]:
    """Temporary v0.2 axis definition; horizontal-section fitting comes later."""
    if method == "bbox":
        b = mesh.bounds
        return float((b[0, 0] + b[1, 0]) / 2.0), float((b[0, 1] + b[1, 1]) / 2.0)
    if method == "centroid":
        c = np.asarray(mesh.vertices).mean(axis=0)
        return float(c[0]), float(c[1])
    if method == "manual":
        if center_x is None or center_y is None:
            raise ValueError("--center-method manual requires --center-x and --center-y.")
        return float(center_x), float(center_y)
    raise ValueError(f"Unknown center method: {method}")


def angle_series(step_deg: float, start_deg: float, span_deg: float) -> list[float]:
    if step_deg <= 0:
        raise ValueError("angle step must be positive.")
    n_float = span_deg / step_deg
    n = int(round(n_float))
    if not math.isclose(n_float, n, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"angle step must divide {span_deg:g} degrees exactly.")
    return [float((start_deg + i * step_deg) % 360.0) for i in range(n)]


def plane_basis(angle_deg: float) -> tuple[np.ndarray, np.ndarray]:
    a = math.radians(angle_deg)
    radial = np.array([math.cos(a), math.sin(a), 0.0], dtype=np.float64)
    normal = np.array([-math.sin(a), math.cos(a), 0.0], dtype=np.float64)
    return radial, normal


def section_segments(mesh: trimesh.Trimesh, center_xy: tuple[float, float], angle_deg: float) -> np.ndarray:
    _radial, normal = plane_basis(angle_deg)
    zmid = float(mesh.bounds[:, 2].mean())
    origin = np.array([center_xy[0], center_xy[1], zmid], dtype=np.float64)
    segments = trimesh.intersections.mesh_plane(
        mesh=mesh,
        plane_normal=normal,
        plane_origin=origin,
        return_faces=False,
    )
    segments = np.asarray(segments, dtype=np.float64)
    if segments.size == 0:
        return np.empty((0, 2, 3), dtype=np.float64)
    return segments.reshape((-1, 2, 3))


def signed_r(points: np.ndarray, center_xy: tuple[float, float], angle_deg: float) -> np.ndarray:
    radial, _ = plane_basis(angle_deg)
    d = np.asarray(points, dtype=np.float64).copy()
    d[..., 0] -= center_xy[0]
    d[..., 1] -= center_xy[1]
    return np.tensordot(d, radial, axes=([-1], [0]))


def clip_segments_to_positive_half(
    segments: np.ndarray,
    center_xy: tuple[float, float],
    ray_angle_deg: float,
    eps: float = 1e-12,
) -> np.ndarray:
    if len(segments) == 0:
        return segments.copy()
    s = signed_r(segments, center_xy, ray_angle_deg)
    out: list[np.ndarray] = []
    for seg, rr in zip(segments, s):
        p0, p1 = seg
        r0, r1 = float(rr[0]), float(rr[1])
        in0 = r0 >= -eps
        in1 = r1 >= -eps
        if in0 and in1:
            out.append(np.array([p0, p1], dtype=np.float64))
            continue
        if (not in0) and (not in1):
            continue
        denom = r0 - r1
        if abs(denom) < eps:
            continue
        t = min(1.0, max(0.0, r0 / denom))
        cross = p0 + t * (p1 - p0)
        out.append(np.array([p0, cross] if in0 else [cross, p1], dtype=np.float64))
    if not out:
        return np.empty((0, 2, 3), dtype=np.float64)
    return np.stack(out, axis=0)


def write_segment_csv(
    path: Path,
    segments: np.ndarray,
    center_xy: tuple[float, float],
    angle_deg: float,
    scale_to_mm: float,
    z_min_native: float,
) -> None:
    """Write section segment endpoints in both native coordinates and mm."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rr = signed_r(segments, center_xy, angle_deg) if len(segments) else np.empty((0, 2))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "segment_id", "endpoint", "angle_deg", "side",
            "x_input", "y_input", "z_input",
            "x_mm", "y_mm", "z_mm",
            "signed_r_mm", "radial_r_mm", "z_from_bottom_mm",
        ])
        for i, seg in enumerate(segments):
            for j in (0, 1):
                r_native = float(rr[i, j])
                p = seg[j]
                w.writerow([
                    i, j, f"{angle_deg:.10g}", "positive" if r_native >= 0 else "negative",
                    f"{p[0]:.12g}", f"{p[1]:.12g}", f"{p[2]:.12g}",
                    f"{p[0] * scale_to_mm:.12g}", f"{p[1] * scale_to_mm:.12g}", f"{p[2] * scale_to_mm:.12g}",
                    f"{r_native * scale_to_mm:.12g}", f"{abs(r_native) * scale_to_mm:.12g}",
                    f"{(p[2] - z_min_native) * scale_to_mm:.12g}",
                ])


def write_edge_ply(path: Path, segments: np.ndarray) -> None:
    """Write independent PLY edges in ORIGINAL input coordinates/units."""
    path.parent.mkdir(parents=True, exist_ok=True)
    points = segments.reshape((-1, 3)) if len(segments) else np.empty((0, 3), dtype=float)
    with path.open("w", encoding="ascii", newline="\n") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {len(points)}\n")
        f.write("property double x\nproperty double y\nproperty double z\n")
        f.write(f"element edge {len(segments)}\n")
        f.write("property int vertex1\nproperty int vertex2\nend_header\n")
        for p in points:
            f.write(f"{p[0]:.12g} {p[1]:.12g} {p[2]:.12g}\n")
        for i in range(len(segments)):
            f.write(f"{2*i} {2*i+1}\n")


def sample_segments(segments: np.ndarray, spacing_native: float) -> np.ndarray:
    if len(segments) == 0:
        return np.empty((0, 3), dtype=np.float64)
    pts: list[np.ndarray] = []
    for p0, p1 in segments:
        length = float(np.linalg.norm(p1 - p0))
        n = max(2, int(math.ceil(length / spacing_native)) + 1)
        t = np.linspace(0.0, 1.0, n)[:, None]
        pts.append(p0[None, :] * (1.0 - t) + p1[None, :] * t)
    return np.vstack(pts)


def hsv_color(index: int, total: int) -> np.ndarray:
    import colorsys
    hue = (index / max(1, total)) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 0.95)
    return np.array([round(255*r), round(255*g), round(255*b), 255], dtype=np.uint8)


def write_points_ply(path: Path, points: np.ndarray, color: np.ndarray | None = None) -> None:
    """Write point cloud in ORIGINAL input coordinates/units."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pts = np.asarray(points, dtype=np.float64)
    if color is None:
        pc = trimesh.points.PointCloud(pts)
    else:
        c = np.asarray(color, dtype=np.uint8).reshape(1, 4)
        colors = np.repeat(c, len(pts), axis=0)
        pc = trimesh.points.PointCloud(pts, colors=colors)
    pc.export(str(path))


def write_combined_points(path: Path, groups: list[tuple[np.ndarray, np.ndarray]]) -> None:
    points = []
    colors = []
    for pts, color in groups:
        if len(pts) == 0:
            continue
        points.append(np.asarray(pts, dtype=np.float64))
        colors.append(np.repeat(np.asarray(color, dtype=np.uint8).reshape(1, 4), len(pts), axis=0))
    if points:
        pc = trimesh.points.PointCloud(np.vstack(points), colors=np.vstack(colors))
    else:
        pc = trimesh.points.PointCloud(np.empty((0, 3), dtype=np.float64))
    path.parent.mkdir(parents=True, exist_ok=True)
    pc.export(str(path))


def make_oblique_plot(
    mesh: trimesh.Trimesh,
    section_groups: list[tuple[np.ndarray, np.ndarray]],
    path: Path,
    scale_to_mm: float,
    title: str,
    max_mesh_points: int = 50000,
    max_section_points_each: int = 12000,
) -> None:
    """Reference image only; geometry files remain the authoritative coordinate output."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    if len(verts) > max_mesh_points:
        idx = np.linspace(0, len(verts)-1, max_mesh_points, dtype=int)
        verts = verts[idx]
    verts_mm = verts * scale_to_mm

    fig = plt.figure(figsize=(8.2, 8.2))
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter(verts_mm[:,0], verts_mm[:,1], verts_mm[:,2], s=0.12, alpha=0.07)

    for pts, color in section_groups:
        if len(pts) == 0:
            continue
        p = np.asarray(pts, dtype=np.float64)
        if len(p) > max_section_points_each:
            idx = np.linspace(0, len(p)-1, max_section_points_each, dtype=int)
            p = p[idx]
        p = p * scale_to_mm
        rgb = np.asarray(color[:3], dtype=float) / 255.0
        ax.scatter(p[:,0], p[:,1], p[:,2], s=1.3, c=[rgb], alpha=0.9)

    b = mesh.bounds * scale_to_mm
    mid = b.mean(axis=0)
    span = (b[1]-b[0]).max()
    half = span * 0.58
    ax.set_xlim(mid[0]-half, mid[0]+half)
    ax.set_ylim(mid[1]-half, mid[1]+half)
    ax.set_zlim(mid[2]-half, mid[2]+half)
    ax.set_xlabel("X [mm]")
    ax.set_ylabel("Y [mm]")
    ax.set_zlabel("Z [mm]")
    ax.set_title(title)
    ax.view_init(elev=24, azim=-55)
    try:
        ax.set_box_aspect((1,1,1))
    except Exception:
        pass
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=220)
    plt.close(fig)


def process(
    input_path: Path,
    unit: str,
    step_deg: float,
    start_deg: float,
    center_method: str,
    center_x: float | None,
    center_y: float | None,
    sample_spacing_mm: float,
    output_dir: Path | None,
    make_visualization: bool,
) -> dict:
    if unit not in UNIT_SCALE_TO_MM:
        raise ValueError(f"Unsupported unit: {unit}")
    if sample_spacing_mm <= 0:
        raise ValueError("--sample-spacing-mm must be positive.")

    scale = UNIT_SCALE_TO_MM[unit]
    mesh = load_geometry(input_path)
    center = determine_axis_center(mesh, center_method, center_x, center_y)
    zmin = float(mesh.bounds[0, 2])
    zmax = float(mesh.bounds[1, 2])

    full_angles = angle_series(step_deg, start_deg, 180.0)
    ray_angles = angle_series(step_deg, start_deg, 360.0)

    if output_dir is None:
        step_label = f"{step_deg:g}".replace(".", "p")
        output_dir = input_path.parent / f"{input_path.stem}_RadialSections_{step_label}deg"
    full_dir = output_dir / "full_sections"
    ray_dir = output_dir / "radial_half_sections"
    vis_dir = output_dir / "visualization"
    for p in (full_dir, ray_dir, vis_dir):
        p.mkdir(parents=True, exist_ok=True)

    metadata = {
        "program": "PotteryRadialSections",
        "version": __version__,
        "input": str(input_path),
        "input_unit": unit,
        "section_ply_coordinate_system": "same XYZ coordinate system and unit as input mesh",
        "csv_coordinates": ["input/native XYZ", "mm XYZ", "signed/radial r in mm", "z from bottom in mm"],
        "axis_direction": [0.0, 0.0, 1.0],
        "axis_center_xy_native": [center[0], center[1]],
        "axis_center_xy_mm": [center[0]*scale, center[1]*scale],
        "axis_center_method": center_method,
        "axis_note": "Temporary v0.2 axis definition. Horizontal-section ellipse-center estimation is not implemented yet.",
        "z_min_native": zmin,
        "z_max_native": zmax,
        "angle_step_deg": step_deg,
        "start_angle_deg": start_deg,
        "full_section_plane_angles_deg": full_angles,
        "radial_half_section_angles_deg": ray_angles,
        "sample_spacing_mm": sample_spacing_mm,
        "visualization_generated": bool(make_visualization),
        "note": "Raw mesh-plane intersections only; no inner/outer classification or volume reconstruction yet.",
    }

    spacing_native = sample_spacing_mm / scale
    full_cache: dict[int, np.ndarray] = {}
    full_groups: list[tuple[np.ndarray, np.ndarray]] = []
    ray_groups: list[tuple[np.ndarray, np.ndarray]] = []
    summary_rows: list[dict] = []

    print(f"=== PotteryRadialSections v{__version__} ===")
    print(f"input       : {input_path}")
    print(f"unit        : {unit}")
    print(f"vertices    : {len(mesh.vertices):,}")
    print(f"faces       : {len(mesh.faces):,}")
    print(f"extents     : X={mesh.extents[0]*scale:.3f}, Y={mesh.extents[1]*scale:.3f}, Z={mesh.extents[2]*scale:.3f} mm")
    print(f"axis center : X={center[0]*scale:.3f}, Y={center[1]*scale:.3f} mm ({center_method})")
    print(f"angle step  : {step_deg:g} deg")
    print(f"output dir  : {output_dir}")

    for i, angle in enumerate(full_angles):
        seg = section_segments(mesh, center, angle)
        full_cache[i] = seg
        opposite = (angle + 180.0) % 360.0
        stem = f"section_{int(round(angle))%360:03d}_{int(round(opposite))%360:03d}"
        write_segment_csv(full_dir / f"{stem}.csv", seg, center, angle, scale, zmin)
        write_edge_ply(full_dir / f"{stem}_edges.ply", seg)
        sampled = sample_segments(seg, spacing_native)
        color = hsv_color(i, len(full_angles))
        write_points_ply(full_dir / f"{stem}_points.ply", sampled, color)
        full_groups.append((sampled, color))
        summary_rows.append({"type":"full_section","angle_deg":angle,"opposite_angle_deg":opposite,"segments":len(seg),"sampled_points":len(sampled)})
        print(f"full {angle:6.1f}/{opposite:6.1f} deg : {len(seg):,} segments")

    for j, ray_angle in enumerate(ray_angles):
        base_index = j % len(full_angles)
        seg_half = clip_segments_to_positive_half(full_cache[base_index], center, ray_angle)
        stem = f"ray_{int(round(ray_angle))%360:03d}"
        write_segment_csv(ray_dir / f"{stem}.csv", seg_half, center, ray_angle, scale, zmin)
        write_edge_ply(ray_dir / f"{stem}_edges.ply", seg_half)
        sampled = sample_segments(seg_half, spacing_native)
        color = hsv_color(j, len(ray_angles))
        write_points_ply(ray_dir / f"{stem}_points.ply", sampled, color)
        ray_groups.append((sampled, color))
        summary_rows.append({"type":"radial_half_section","angle_deg":ray_angle,"opposite_angle_deg":"","segments":len(seg_half),"sampled_points":len(sampled)})
        print(f"ray  {ray_angle:6.1f} deg       : {len(seg_half):,} segments")

    write_combined_points(full_dir / "all_full_section_points.ply", full_groups)
    write_combined_points(ray_dir / "all_radial_half_section_points.ply", ray_groups)

    with (output_dir / "sections_summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["type", "angle_deg", "opposite_angle_deg", "segments", "sampled_points"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(summary_rows)

    if make_visualization:
        make_oblique_plot(mesh, full_groups, vis_dir / "full_sections_oblique.png", scale,
                          "Full longitudinal sections in 3D space")
        make_oblique_plot(mesh, ray_groups, vis_dir / "radial_half_sections_oblique.png", scale,
                          "Radial half-sections in 3D space")

    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Z-axis longitudinal sections of a pottery mesh at regular angular intervals.")
    parser.add_argument("input", type=Path, help="Input PLY or OBJ mesh")
    parser.add_argument("--unit", choices=["mm", "cm", "m"], required=True, help="Coordinate unit of input mesh")
    parser.add_argument("--angle-step", type=float, default=30.0, help="Radial angular interval in degrees (default: 30)")
    parser.add_argument("--start-angle", type=float, default=0.0, help="Start azimuth in degrees (default: 0)")
    parser.add_argument("--center-method", choices=["bbox", "centroid", "manual"], default="bbox",
                        help="Temporary XY center method (default: bbox); horizontal-section axis fitting comes in a later version")
    parser.add_argument("--center-x", type=float, help="Manual center X in input coordinate unit")
    parser.add_argument("--center-y", type=float, help="Manual center Y in input coordinate unit")
    parser.add_argument("--sample-spacing-mm", type=float, default=0.5, help="Point-cloud sampling interval along section lines [mm]")
    parser.add_argument("--output-dir", type=Path, help="Output directory")
    parser.add_argument("--no-visualization", action="store_true", help="Do not generate oblique PNG reference images")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()
    try:
        process(args.input, args.unit, args.angle_step, args.start_angle, args.center_method,
                args.center_x, args.center_y, args.sample_spacing_mm, args.output_dir,
                not args.no_visualization)
    except Exception as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
