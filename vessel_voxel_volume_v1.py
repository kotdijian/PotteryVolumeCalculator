#!/usr/bin/env python3
"""
PotteryVolumeCalculator
Version 1.0.0

OBJ / PLY の土器メッシュから、内面を明示的に抽出せず、
「液体が最初に外へ溢れ出す直前までの最大内容量」を voxel 法で推定する。

v1 の主要方針
--------------
1. PyMeshLab で入力メッシュを独立QA
2. 完全同一座標の duplicate vertex と unreferenced vertex だけを除去
   （穴埋め、近接頂点融合、non-manifold修復は自動実行しない）
3. PyMeshLab の処理済み頂点・faceを Trimesh に渡す
4. 内部計算は mm に統一して surface voxelization
5. 高さ制限付き 3D flood fill により spill level を探索
6. spill直前までの空隙を最大保持液量として計算
7. 出力PLYの座標単位は入力モデルと同じ単位へ戻す
8. 出力ファイルは専用フォルダ内へ整理

対象（v1）
----------
- 単純な単口縁
- 口縁に大きな突起・把手・注口なし
- 内面が滑らか
- 大きな欠損なし
- 土器の上下方向が Z 軸
- 入力座標単位は mm / cm / m

注意
----
- surface voxel は厚さを持つため、容量は解像度依存。
  0.5 / 1.0 / 2.0 mm 等の複数 pitch で収束を確認する。
- PyMeshLab QA と voxel QA は別物。
  元メッシュがトポロジー上閉じていても voxel化後に隙間が生じる場合がある。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

__version__ = "1.0.0"


# ----------------------------------------------------------------------
# Dependencies
# ----------------------------------------------------------------------

def dependency_error(exc: ModuleNotFoundError) -> None:
    missing = exc.name or "unknown"
    package = {
        "PIL": "Pillow",
        "numpy": "numpy",
        "scipy": "scipy",
        "trimesh": "trimesh",
        "pymeshlab": "pymeshlab",
    }.get(missing, missing)

    print(
        "\nERROR: 必要なPythonモジュールが見つかりません。\n"
        f"missing module : {missing}\n"
        f"install package: {package}\n\n"
        "仮想環境 (.venv) を有効にした状態で次を実行してください。\n"
        "  python3 -m pip install -r requirements.txt\n\n"
        "requirements.txt を使わない場合:\n"
        "  python3 -m pip install numpy scipy trimesh Pillow pymeshlab\n",
        file=sys.stderr,
    )
    raise SystemExit(2)


try:
    import numpy as np
    import trimesh
    import pymeshlab
    import PIL  # noqa: F401  # trimesh の soft dependency 対策
    from scipy import ndimage
except ModuleNotFoundError as exc:
    dependency_error(exc)


# ----------------------------------------------------------------------
# General helpers
# ----------------------------------------------------------------------

UNIT_SCALE_TO_MM = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
}

VOLUME_UNIT_BY_INPUT = {
    "mm": "mm^3",
    "cm": "cm^3",
    "m": "m^3",
}


def jsonable(value):
    """PyMeshLab / NumPy の戻り値を JSON に保存可能な型へ変換する。"""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(jsonable(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def pitch_label(pitch: float) -> str:
    text = f"{pitch:g}".replace(".", "p")
    return f"pitch_{text}mm"


def native_length(mm_value: float, unit: str) -> float:
    return mm_value / UNIT_SCALE_TO_MM[unit]


def native_volume_from_mm3(volume_mm3: float, unit: str) -> float:
    # length scale is s mm per native unit -> volume scale s^3
    s = UNIT_SCALE_TO_MM[unit]
    return volume_mm3 / (s ** 3)


# ----------------------------------------------------------------------
# Output layout
# ----------------------------------------------------------------------

def make_output_layout(
    input_path: Path,
    pitch: float,
    output_dir: Path | None,
):
    if output_dir is None:
        base = input_path.parent / f"{input_path.stem}_PotteryVolume_v1"
    else:
        base = Path(output_dir)

    processed_dir = base / "processed"
    qa_dir = base / "qa"
    run_dir = base / pitch_label(pitch)
    run_qa_dir = run_dir / "qa"
    qc_dir = run_dir / "qc"

    for p in (base, processed_dir, qa_dir, run_dir, run_qa_dir, qc_dir):
        p.mkdir(parents=True, exist_ok=True)

    return {
        "base": base,
        "processed": processed_dir,
        "qa": qa_dir,
        "run": run_dir,
        "run_qa": run_qa_dir,
        "qc": qc_dir,
    }


# ----------------------------------------------------------------------
# Stage A: PyMeshLab QA and conservative preprocessing
# ----------------------------------------------------------------------

def topology_summary(measures: dict) -> dict:
    """
    get_topological_measures() の主要項目を抽出。
    キーが存在しないバージョンでも raw 辞書は別途保存する。
    """
    keys = [
        "vertices_number",
        "faces_number",
        "edges_number",
        "boundary_edges",
        "connected_components_number",
        "is_mesh_two_manifold",
        "non_two_manifold_edges",
        "non_two_manifold_vertices",
        "incident_faces_on_non_two_manifold_edges",
        "incident_faces_on_non_two_manifold_vertices",
        "unreferenced_vertices",
        "number_holes",
        "genus",
    ]
    return {k: jsonable(measures.get(k)) for k in keys if k in measures}


def pymeshlab_preprocess(
    input_path: Path,
    processed_dir: Path,
    qa_dir: Path,
):
    """
    PyMeshLabでQA後、完全同一座標のduplicate vertexと
    unreferenced vertexのみ除去する。

    幾何形状を変更しうる以下は自動実行しない:
    - Close Holes
    - Merge Close Vertices
    - Repair non-manifold edges/vertices
    """
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(str(input_path))

    mesh_before = ms.current_mesh()
    before_counts = {
        "vertices": int(mesh_before.vertex_number()),
        "faces": int(mesh_before.face_number()),
    }

    topo_before_raw = ms.get_topological_measures()
    topo_before = {
        "counts": before_counts,
        "summary": topology_summary(topo_before_raw),
        "raw": jsonable(topo_before_raw),
    }
    write_json(qa_dir / "pymeshlab_before.json", topo_before)

    # Conservative preprocessing only
    ms.meshing_remove_duplicate_vertices()
    ms.meshing_remove_unreferenced_vertices()

    mesh_after = ms.current_mesh()
    # vertex_matrix / face_matrix の取得前に配列をcompact化する。
    # PyMeshLab公式APIではこれらのmatrix取得はcompact meshを前提とする。
    mesh_after.compact()

    after_counts = {
        "vertices": int(mesh_after.vertex_number()),
        "faces": int(mesh_after.face_number()),
    }

    topo_after_raw = ms.get_topological_measures()
    topo_after = {
        "counts": after_counts,
        "summary": topology_summary(topo_after_raw),
        "raw": jsonable(topo_after_raw),
        "operations": [
            "meshing_remove_duplicate_vertices",
            "meshing_remove_unreferenced_vertices",
        ],
        "geometry_changing_repairs_applied": False,
    }
    write_json(qa_dir / "pymeshlab_after.json", topo_after)

    cleaned_path = processed_dir / f"{input_path.stem}_pymeshlab_cleaned.ply"
    # PyMeshLab stays in the original/native input coordinate scale.
    ms.save_current_mesh(str(cleaned_path), save_textures=False)

    vertices_native = np.asarray(mesh_after.vertex_matrix(), dtype=np.float64).copy()
    faces = np.asarray(mesh_after.face_matrix(), dtype=np.int64).copy()

    report = {
        "before": topo_before,
        "after": topo_after,
        "vertices_removed": int(before_counts["vertices"] - after_counts["vertices"]),
        "faces_changed": int(after_counts["faces"] - before_counts["faces"]),
        "processed_mesh": str(cleaned_path),
    }

    return vertices_native, faces, report


# ----------------------------------------------------------------------
# Stage B: Trimesh QA
# ----------------------------------------------------------------------

def edge_diagnostics(mesh: trimesh.Trimesh):
    unique_edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    inverse = np.asarray(mesh.edges_unique_inverse, dtype=np.int64)
    counts = np.bincount(inverse, minlength=len(unique_edges))
    boundary_edges = unique_edges[counts == 1]
    nonmanifold_edges = unique_edges[counts > 2]
    return boundary_edges, nonmanifold_edges


def export_edge_vertices_native(
    mesh_mm: trimesh.Trimesh,
    edges: np.ndarray,
    path: Path,
    scale_to_mm: float,
) -> int:
    if edges.size == 0:
        return 0
    vertex_ids = np.unique(edges.reshape(-1))
    points_native = np.asarray(mesh_mm.vertices)[vertex_ids] / scale_to_mm
    trimesh.points.PointCloud(points_native).export(str(path))
    return int(len(points_native))


def trimesh_validate(
    mesh_mm: trimesh.Trimesh,
    unit: str,
    qa_dir: Path,
    qc_dir: Path,
):
    boundary_edges, nonmanifold_edges = edge_diagnostics(mesh_mm)

    try:
        body_count = int(mesh_mm.body_count)
    except Exception:
        body_count = None

    scale_ref = max(float(mesh_mm.extents.max()), 1.0)
    area_tol = (scale_ref ** 2) * 1e-14
    degenerate_faces = int(
        np.count_nonzero(np.asarray(mesh_mm.area_faces) <= area_tol)
    )

    report = {
        "watertight": bool(mesh_mm.is_watertight),
        "winding_consistent": bool(mesh_mm.is_winding_consistent),
        "euler_number": int(mesh_mm.euler_number),
        "body_count": body_count,
        "boundary_edges": int(len(boundary_edges)),
        "nonmanifold_edges": int(len(nonmanifold_edges)),
        "degenerate_faces": degenerate_faces,
        "coordinates_internal_unit": "mm",
        "qc_ply_coordinate_unit": unit,
    }

    scale = UNIT_SCALE_TO_MM[unit]
    if len(boundary_edges):
        p = qc_dir / "trimesh_boundary_points.ply"
        n = export_edge_vertices_native(mesh_mm, boundary_edges, p, scale)
        report["boundary_points_ply"] = str(p)
        report["boundary_vertices_exported"] = n

    if len(nonmanifold_edges):
        p = qc_dir / "trimesh_nonmanifold_points.ply"
        n = export_edge_vertices_native(mesh_mm, nonmanifold_edges, p, scale)
        report["nonmanifold_points_ply"] = str(p)
        report["nonmanifold_vertices_exported"] = n

    write_json(qa_dir / "trimesh_qa.json", report)
    return report


# ----------------------------------------------------------------------
# Voxel helpers
# ----------------------------------------------------------------------

def padded_world_to_index(
    vox: trimesh.voxel.VoxelGrid,
    point_xyz_mm: np.ndarray,
    pad: int,
) -> np.ndarray:
    idx = np.asarray(
        vox.points_to_indices(np.asarray(point_xyz_mm).reshape(1, 3))[0],
        dtype=int,
    )
    return idx + pad


def padded_indices_to_points_mm(
    vox: trimesh.voxel.VoxelGrid,
    indices: np.ndarray,
    pad: int,
) -> np.ndarray:
    indices = np.asarray(indices, dtype=int)
    return vox.indices_to_points(indices - pad)


def central_opening_at_slice(
    surface_slice: np.ndarray,
    center_xy: tuple[int, int],
    min_area_voxels: int,
    close_iterations: int = 1,
):
    """
    XY断面で中央付近の閉じた空隙を探す。
    seed検出だけに使う2D処理であり、3Dメッシュ修復ではない。
    """
    if close_iterations > 0:
        sealed_ring = ndimage.binary_closing(
            surface_slice,
            structure=np.ones((3, 3), dtype=bool),
            iterations=close_iterations,
        )
    else:
        sealed_ring = surface_slice.copy()

    filled = ndimage.binary_fill_holes(
        sealed_ring,
        structure=ndimage.generate_binary_structure(2, 1),
    )
    holes = filled & ~sealed_ring

    labels, n_labels = ndimage.label(
        holes,
        structure=ndimage.generate_binary_structure(2, 1),
    )

    if n_labels == 0:
        return None

    cx, cy = center_xy

    # center pointを含む空隙を優先
    if 0 <= cx < labels.shape[0] and 0 <= cy < labels.shape[1]:
        label_id = int(labels[cx, cy])
        if label_id > 0:
            opening = labels == label_id
            area = int(np.count_nonzero(opening))
            if area >= min_area_voxels:
                return opening, area

    # fallback: 十分大きい空隙のうちcenterに最も近いもの
    best = None
    best_distance = float("inf")
    for label_id in range(1, n_labels + 1):
        coords = np.argwhere(labels == label_id)
        area = len(coords)
        if area < min_area_voxels:
            continue
        centroid = coords.mean(axis=0)
        d = math.hypot(float(centroid[0] - cx), float(centroid[1] - cy))
        if d < best_distance:
            best_distance = d
            best = (labels == label_id, int(area))

    return best


def find_interior_seed(
    surface: np.ndarray,
    center_xy: tuple[int, int],
    min_area_voxels: int,
    persistence: int,
    close_iterations: int,
    z_start_fraction: float = 0.10,
    z_end_fraction: float = 0.60,
):
    """
    土器の底端そのものを避け、下部〜中部の範囲で内部seedを探索。
    """
    nz = surface.shape[2]
    k0 = max(0, int(math.floor(nz * z_start_fraction)))
    k1 = min(nz - persistence, int(math.ceil(nz * z_end_fraction)))

    for k in range(k0, k1 + 1):
        candidates = []
        for offset in range(persistence):
            kk = k + offset
            result = central_opening_at_slice(
                surface[:, :, kk],
                center_xy=center_xy,
                min_area_voxels=min_area_voxels,
                close_iterations=close_iterations,
            )
            if result is None:
                candidates = []
                break
            candidates.append(result)

        if candidates:
            mid = persistence // 2
            seed_k = k + mid
            opening, area = candidates[mid]
            coords = np.argwhere(opening)
            centroid = coords.mean(axis=0)
            d2 = np.sum((coords - centroid) ** 2, axis=1)
            seed_xy = coords[int(np.argmin(d2))]
            seed_xyz = (int(seed_xy[0]), int(seed_xy[1]), int(seed_k))
            return seed_xyz, int(area), (z_start_fraction, z_end_fraction)

    raise RuntimeError(
        "土器内部のseed空隙を自動検出できませんでした。\n"
        "考えられる原因:\n"
        "- 土器がZ軸に直立していない\n"
        "- voxel pitchが粗すぎる\n"
        "- 底〜胴部に大きな欠損がある\n"
        "- 現在の単純器形条件から外れている"
    )


def touches_boundary(mask: np.ndarray) -> bool:
    return bool(
        mask[0, :, :].any()
        or mask[-1, :, :].any()
        or mask[:, 0, :].any()
        or mask[:, -1, :].any()
        or mask[:, :, 0].any()
        or mask[:, :, -1].any()
    )


def propagate_below_level(
    free: np.ndarray,
    seed_xyz: tuple[int, int, int],
    level_k: int,
):
    if level_k < seed_xyz[2]:
        raise ValueError("level_k は seed の高さ以上である必要があります。")

    allowed = free.copy()
    if level_k + 1 < allowed.shape[2]:
        allowed[:, :, level_k + 1:] = False

    seed = np.zeros_like(free, dtype=bool)
    seed[seed_xyz] = True

    return ndimage.binary_propagation(
        seed,
        structure=ndimage.generate_binary_structure(3, 1),
        mask=allowed,
    )


def find_spill_level(
    free: np.ndarray,
    seed_xyz: tuple[int, int, int],
):
    """
    内部空隙が外部境界へ初めて接続する最小Z indexを二分探索。
    """
    seed_k = int(seed_xyz[2])
    top_k = free.shape[2] - 1
    evaluations = 0

    low_component = propagate_below_level(free, seed_xyz, seed_k)
    evaluations += 1
    if touches_boundary(low_component):
        raise RuntimeError(
            "内部seedの高さですでに外部へ漏れています。\n"
            "口縁より低い位置にメッシュ/voxel障壁の穴がある可能性があります。"
        )

    high_component = propagate_below_level(free, seed_xyz, top_k)
    evaluations += 1
    if not touches_boundary(high_component):
        raise RuntimeError(
            "最上層まで許可しても内部空隙が外部へ接続しません。\n"
            "voxel化によって口が閉じた可能性があります。pitchを小さくしてください。"
        )

    lo = seed_k   # leak=False
    hi = top_k    # leak=True

    while hi - lo > 1:
        mid = (lo + hi) // 2
        comp = propagate_below_level(free, seed_xyz, mid)
        evaluations += 1
        if touches_boundary(comp):
            hi = mid
        else:
            lo = mid

    safe_component = propagate_below_level(free, seed_xyz, lo)
    spill_component = propagate_below_level(free, seed_xyz, hi)
    evaluations += 2

    return lo, hi, safe_component, spill_component, evaluations


def voxel_connectivity_report(surface_raw: np.ndarray) -> dict:
    report = {}
    for conn, name in ((1, "6"), (2, "18"), (3, "26")):
        _, n = ndimage.label(
            surface_raw,
            structure=ndimage.generate_binary_structure(3, conn),
        )
        report[f"surface_components_{name}conn"] = int(n)
    return report


def export_mask_native(
    vox: trimesh.voxel.VoxelGrid,
    mask: np.ndarray,
    pad: int,
    path: Path,
    scale_to_mm: float,
    surface_only: bool = True,
):
    if surface_only:
        eroded = ndimage.binary_erosion(
            mask,
            structure=ndimage.generate_binary_structure(3, 1),
            border_value=0,
        )
        export_mask = mask & ~eroded
    else:
        export_mask = mask

    indices = np.argwhere(export_mask)
    if len(indices) == 0:
        return 0

    points_mm = padded_indices_to_points_mm(vox, indices, pad)
    points_native = points_mm / scale_to_mm
    trimesh.points.PointCloud(points_native).export(str(path))
    return int(len(points_native))


def export_surface_voxels_native(
    vox: trimesh.voxel.VoxelGrid,
    path: Path,
    scale_to_mm: float,
):
    points_native = np.asarray(vox.points) / scale_to_mm
    if len(points_native) == 0:
        return 0
    trimesh.points.PointCloud(points_native).export(str(path))
    return int(len(points_native))


def make_spill_slab(
    surface: np.ndarray,
    spill_component: np.ndarray,
    spill_k: int,
    half_width: int = 2,
):
    z0 = max(0, spill_k - half_width)
    z1 = min(surface.shape[2], spill_k + half_width + 1)

    selector = np.zeros_like(surface, dtype=bool)
    selector[:, :, z0:z1] = True
    return surface & selector, spill_component & selector


# ----------------------------------------------------------------------
# Main calculation
# ----------------------------------------------------------------------

def estimate_volume(
    input_path: Path,
    pitch: float,
    unit: str,
    pad: int,
    min_cavity_area_mm2: float,
    seed_persistence: int,
    close_iterations: int,
    output_dir: Path | None,
    debug_voxels: bool,
):
    started = time.perf_counter()

    if unit not in UNIT_SCALE_TO_MM:
        raise ValueError("unit は mm / cm / m のいずれかを指定してください。")
    if pitch <= 0:
        raise ValueError("pitch は正数にしてください。")

    scale_to_mm = UNIT_SCALE_TO_MM[unit]
    layout = make_output_layout(input_path, pitch, output_dir)

    print(f"=== PotteryVolumeCalculator v{__version__} ===")
    print(f"output dir : {layout['base']}")

    # ---- Stage A: PyMeshLab ----
    print("\n=== Stage A: PyMeshLab QA / preprocessing ===")
    tp = time.perf_counter()
    vertices_native, faces, pml_report = pymeshlab_preprocess(
        input_path,
        processed_dir=layout["processed"],
        qa_dir=layout["qa"],
    )
    pml_time = time.perf_counter() - tp

    before = pml_report["before"]["summary"]
    after = pml_report["after"]["summary"]

    print(f"vertices before : {pml_report['before']['counts']['vertices']:,}")
    print(f"vertices after  : {pml_report['after']['counts']['vertices']:,}")
    print(f"duplicate/unref removed: {pml_report['vertices_removed']:,}")
    print(f"boundary edges before: {before.get('boundary_edges', 'n/a')}")
    print(f"boundary edges after : {after.get('boundary_edges', 'n/a')}")
    print(f"components after     : {after.get('connected_components_number', 'n/a')}")
    print(f"2-manifold after     : {after.get('is_mesh_two_manifold', 'n/a')}")
    print(f"non-2-manifold edges : {after.get('non_two_manifold_edges', 'n/a')}")
    print(f"time                  : {pml_time:.2f} s")
    print(f"processed mesh        : {pml_report['processed_mesh']}")

    # ---- Internal Trimesh in mm ----
    vertices_mm = vertices_native * scale_to_mm
    mesh_mm = trimesh.Trimesh(
        vertices=vertices_mm,
        faces=faces,
        process=False,
        validate=False,
    )

    bounds_mm = np.asarray(mesh_mm.bounds, dtype=float)
    extents_mm = np.asarray(mesh_mm.extents, dtype=float)
    center_mm = bounds_mm.mean(axis=0)

    print("\n=== Input scale ===")
    print(f"input unit : {unit}")
    print(f"internal   : mm")
    print(f"scale      : x{scale_to_mm:g} -> mm")
    print(
        f"extents    : "
        f"X={native_length(extents_mm[0], unit):.6g}, "
        f"Y={native_length(extents_mm[1], unit):.6g}, "
        f"Z={native_length(extents_mm[2], unit):.6g} {unit}"
    )

    # ---- Stage B: Trimesh QA ----
    print("\n=== Stage B: Trimesh QA ===")
    tt = time.perf_counter()
    tm_report = trimesh_validate(
        mesh_mm,
        unit=unit,
        qa_dir=layout["run_qa"],
        qc_dir=layout["qc"],
    )
    tm_time = time.perf_counter() - tt

    print(f"watertight         : {tm_report['watertight']}")
    print(f"winding consistent : {tm_report['winding_consistent']}")
    print(f"body count         : {tm_report['body_count']}")
    print(f"boundary edges     : {tm_report['boundary_edges']:,}")
    print(f"non-manifold edges : {tm_report['nonmanifold_edges']:,}")
    print(f"time                : {tm_time:.2f} s")

    # ---- Stage C: voxelization ----
    print("\n=== Stage C: Surface voxelization ===")
    print(f"pitch : {pitch:.3f} mm")
    tv = time.perf_counter()
    vox = mesh_mm.voxelized(pitch=pitch, method="subdivide")
    voxelize_time = time.perf_counter() - tv

    surface_raw = np.asarray(vox.matrix, dtype=bool)
    voxel_qa = voxel_connectivity_report(surface_raw)

    print(f"time       : {voxelize_time:.2f} s")
    print(f"voxel grid : {tuple(int(v) for v in vox.shape)}")
    print(f"surface vox: {int(vox.filled_count):,}")
    print(
        "components : "
        f"6={voxel_qa['surface_components_6conn']:,}, "
        f"18={voxel_qa['surface_components_18conn']:,}, "
        f"26={voxel_qa['surface_components_26conn']:,}"
    )

    surface = np.pad(
        surface_raw,
        pad_width=pad,
        mode="constant",
        constant_values=False,
    )
    voxel_qa["voxel_grid_shape"] = [int(v) for v in vox.shape]
    voxel_qa["padded_grid_shape"] = [int(v) for v in surface.shape]
    voxel_qa["surface_voxels"] = int(vox.filled_count)
    voxel_qa["pitch_mm"] = float(pitch)

    total_cells = int(np.prod(surface.shape))
    print(f"padded grid: {surface.shape} = {total_cells:,} cells")
    print(f"bool/grid  : ~{total_cells / (1024**2):.1f} MiB per array")

    # ---- Interior seed ----
    print("\n=== Interior seed ===")
    center_idx = padded_world_to_index(vox, center_mm, pad)
    center_xy = (int(center_idx[0]), int(center_idx[1]))
    min_area_voxels = max(
        1,
        int(math.ceil(min_cavity_area_mm2 / (pitch ** 2))),
    )

    ts = time.perf_counter()
    seed_xyz, seed_area, seed_band = find_interior_seed(
        surface=surface,
        center_xy=center_xy,
        min_area_voxels=min_area_voxels,
        persistence=seed_persistence,
        close_iterations=close_iterations,
    )
    seed_time = time.perf_counter() - ts

    seed_mm = padded_indices_to_points_mm(
        vox,
        np.asarray([seed_xyz], dtype=int),
        pad,
    )[0]
    seed_native = seed_mm / scale_to_mm

    print(f"search band: {seed_band[0]:.2f}-{seed_band[1]:.2f} of height")
    print(f"seed index : {seed_xyz}")
    print(
        f"seed XYZ   : {seed_native[0]:.6g}, "
        f"{seed_native[1]:.6g}, {seed_native[2]:.6g} {unit}"
    )
    print(f"seed area  : {seed_area:,} voxels")
    print(f"time       : {seed_time:.2f} s")

    # ---- Spill search ----
    free = ~surface
    print("\n=== Spill-level search ===")
    tf = time.perf_counter()

    try:
        safe_k, spill_k, fluid, spill_component, evaluations = find_spill_level(
            free,
            seed_xyz,
        )
    except Exception as exc:
        # Failure diagnostics: always export surface voxels.
        surface_path = layout["qc"] / "surface_voxels_on_error.ply"
        export_surface_voxels_native(vox, surface_path, scale_to_mm)
        voxel_qa["surface_voxels_on_error_ply"] = str(surface_path)
        write_json(layout["run_qa"] / "voxel_qa.json", voxel_qa)

        error_report = {
            "program_version": __version__,
            "status": "error",
            "error": str(exc),
            "input": str(input_path),
            "input_unit": unit,
            "pitch_mm": pitch,
            "output_directory": str(layout["base"]),
            "pymeshlab_qa": pml_report,
            "trimesh_qa": tm_report,
            "voxel_qa": voxel_qa,
        }
        write_json(layout["run"] / "error.json", error_report)
        raise

    spill_search_time = time.perf_counter() - tf

    safe_z_mm = float(
        vox.indices_to_points(
            np.asarray([[0, 0, safe_k - pad]], dtype=int)
        )[0][2]
    )
    spill_z_mm = float(
        vox.indices_to_points(
            np.asarray([[0, 0, spill_k - pad]], dtype=int)
        )[0][2]
    )

    zmin_mm = float(bounds_mm[0, 2])
    zmax_mm = float(bounds_mm[1, 2])
    mesh_height_mm = max(zmax_mm - zmin_mm, 1e-12)
    spill_fraction = (spill_z_mm - zmin_mm) / mesh_height_mm
    rim_like = bool(spill_fraction >= 0.75)

    safe_z_native = native_length(safe_z_mm, unit)
    spill_z_native = native_length(spill_z_mm, unit)

    print(f"safe level : {safe_z_native:.6g} {unit}")
    print(f"spill level: {spill_z_native:.6g} {unit}")
    print(f"spill ratio: {spill_fraction:.3f} of mesh height")
    print(f"flood fills: {evaluations}")
    print(f"time       : {spill_search_time:.2f} s")

    if rim_like:
        print("QC assessment: spillは上部25%以内。単純器形では口縁由来の可能性が高い。")
    else:
        print(
            "WARNING: spill levelが低すぎます。"
            "実メッシュの穴またはvoxel化で生じた隙間の可能性があります。"
        )

    # ---- Volume ----
    fluid_voxels = int(np.count_nonzero(fluid))
    volume_mm3 = float(fluid_voxels * (pitch ** 3))
    volume_ml = volume_mm3 / 1000.0
    volume_l = volume_ml / 1000.0
    volume_native = native_volume_from_mm3(volume_mm3, unit)
    native_volume_unit = VOLUME_UNIT_BY_INPUT[unit]

    print("\n=== Maximum retained liquid volume ===")
    print(f"fluid voxels : {fluid_voxels:,}")
    print(f"volume       : {volume_native:.9g} {native_volume_unit}")
    print(f"volume       : {volume_l:.9g} L")
    print(f"volume       : {volume_ml:.6f} mL")
    print(
        f"spill bracket: {safe_z_native:.6g} < spill <= "
        f"{spill_z_native:.6g} {unit}"
    )

    # ---- QC output in native input units ----
    print("\n=== QC output ===")
    qc_files = {}

    fluid_path = layout["qc"] / "fluid_surface.ply"
    n = export_mask_native(
        vox, fluid, pad, fluid_path, scale_to_mm, surface_only=True
    )
    qc_files["fluid_surface_ply"] = str(fluid_path)
    print(f"fluid surface : {fluid_path} ({n:,} points)")

    seed_mask = np.zeros_like(surface, dtype=bool)
    seed_mask[seed_xyz] = True
    seed_path = layout["qc"] / "seed_point.ply"
    export_mask_native(
        vox, seed_mask, pad, seed_path, scale_to_mm, surface_only=False
    )
    qc_files["seed_point_ply"] = str(seed_path)

    # Spill-level region
    spill_plane = np.zeros_like(surface, dtype=bool)
    spill_plane[:, :, spill_k] = spill_component[:, :, spill_k]
    spill_path = layout["qc"] / "spill_level_region.ply"
    n = export_mask_native(
        vox, spill_plane, pad, spill_path, scale_to_mm, surface_only=False
    )
    qc_files["spill_level_region_ply"] = str(spill_path)
    print(f"spill region  : {spill_path} ({n:,} points)")

    # If abnormal, or requested, export complete surface voxels + local slab.
    if debug_voxels or not rim_like:
        surface_path = layout["qc"] / "surface_voxels.ply"
        n = export_surface_voxels_native(vox, surface_path, scale_to_mm)
        qc_files["surface_voxels_ply"] = str(surface_path)
        print(f"surface voxels: {surface_path} ({n:,} points)")

        slab_surface, slab_free = make_spill_slab(
            surface,
            spill_component,
            spill_k,
            half_width=2,
        )

        slab_surface_path = layout["qc"] / "spill_slab_surface.ply"
        slab_free_path = layout["qc"] / "spill_slab_free.ply"

        export_mask_native(
            vox, slab_surface, pad, slab_surface_path,
            scale_to_mm, surface_only=False
        )
        export_mask_native(
            vox, slab_free, pad, slab_free_path,
            scale_to_mm, surface_only=False
        )
        qc_files["spill_slab_surface_ply"] = str(slab_surface_path)
        qc_files["spill_slab_free_ply"] = str(slab_free_path)
        print(f"spill slab wall: {slab_surface_path}")
        print(f"spill slab free: {slab_free_path}")

    voxel_qa.update({
        "safe_level_z_mm": safe_z_mm,
        "spill_level_z_mm": spill_z_mm,
        "safe_level_native": safe_z_native,
        "spill_level_native": spill_z_native,
        "native_length_unit": unit,
        "spill_fraction_of_mesh_height": spill_fraction,
        "spill_rim_like_soft_check": rim_like,
    })
    write_json(layout["run_qa"] / "voxel_qa.json", voxel_qa)

    total_time = time.perf_counter() - started

    result = {
        "program": "PotteryVolumeCalculator",
        "program_version": __version__,
        "status": "ok",
        "definition": (
            "maximum retained liquid volume immediately below the first "
            "spill level under +Z gravity orientation"
        ),
        "input": str(input_path),
        "input_unit": unit,
        "output_coordinate_unit": unit,
        "internal_coordinate_unit": "mm",
        "scale_to_mm": scale_to_mm,
        "pitch_mm": pitch,
        "output_directory": str(layout["base"]),
        "run_directory": str(layout["run"]),
        "mesh_extents_native": [
            native_length(float(v), unit) for v in extents_mm
        ],
        "mesh_extents_native_unit": unit,
        "pymeshlab_qa": pml_report,
        "trimesh_qa": tm_report,
        "voxel_qa": voxel_qa,
        "seed_index": [int(v) for v in seed_xyz],
        "seed_xyz_native": [float(v) for v in seed_native],
        "seed_xyz_native_unit": unit,
        "safe_level_native": safe_z_native,
        "spill_level_native": spill_z_native,
        "spill_level_native_unit": unit,
        "spill_fraction_of_mesh_height": spill_fraction,
        "spill_rim_like_soft_check": rim_like,
        "fluid_voxels": fluid_voxels,
        "volume_native": volume_native,
        "volume_native_unit": native_volume_unit,
        "volume_mm3": volume_mm3,
        "volume_ml": volume_ml,
        "volume_l": volume_l,
        "vertical_resolution_mm": pitch,
        "timing_seconds": {
            "pymeshlab": pml_time,
            "trimesh_qa": tm_time,
            "voxelization": voxelize_time,
            "seed_search": seed_time,
            "spill_search": spill_search_time,
            "total": total_time,
        },
        "qc_files": qc_files,
    }

    result_path = layout["run"] / "result.json"
    write_json(result_path, result)

    print(f"\nresult JSON : {result_path}")
    print(f"output unit : coordinate={unit}, volume={native_volume_unit}")
    print(f"total time  : {total_time:.2f} s")

    return result


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "PyMeshLab QA + voxel spill-level法により、"
            "土器が液体を保持できる最大内容積を推定"
        )
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("input", type=Path, help="入力 OBJ または PLY")
    parser.add_argument(
        "--unit",
        choices=["mm", "cm", "m"],
        default="mm",
        help="入力メッシュの座標単位。既定値 mm",
    )
    parser.add_argument(
        "--pitch",
        type=float,
        default=1.0,
        help="voxel edge length [mm]。既定値 1.0",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "出力ルートフォルダ。省略時は入力ファイルと同じ階層に "
            "<stem>_PotteryVolume_v1/ を作成"
        ),
    )
    parser.add_argument(
        "--pad",
        type=int,
        default=4,
        help="voxel grid周囲の余白セル数。既定値 4",
    )
    parser.add_argument(
        "--min-cavity-area",
        type=float,
        default=100.0,
        help="内部seed候補の最小断面積 [mm^2]。既定値 100",
    )
    parser.add_argument(
        "--seed-persist",
        type=int,
        default=3,
        help="内部seed認定に必要な連続slice数。既定値 3",
    )
    parser.add_argument(
        "--close-iters",
        type=int,
        default=1,
        help=(
            "seed検出用2D断面だけに適用するclosing回数。"
            "3Dメッシュ/voxel本体は修復しない。既定値 1"
        ),
    )
    parser.add_argument(
        "--debug-voxels",
        action="store_true",
        help="surface voxel全体とspill付近スラブを常に出力",
    )

    args = parser.parse_args()

    try:
        estimate_volume(
            input_path=args.input,
            pitch=args.pitch,
            unit=args.unit,
            pad=args.pad,
            min_cavity_area_mm2=args.min_cavity_area,
            seed_persistence=args.seed_persist,
            close_iterations=args.close_iters,
            output_dir=args.output_dir,
            debug_voxels=args.debug_voxels,
        )
    except ModuleNotFoundError as exc:
        dependency_error(exc)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
