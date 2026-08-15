#!/usr/bin/env python3
"""
vessel_voxel_volume.py
Version 0.3.2

OBJ / PLY の土器メッシュから、内面を明示的に抽出せず、
「液体が最初に外へ溢れ出す直前までの最大内容量」を voxel 法で推定する。

対象:
- 単純な単口縁
- 口縁に大きな突起・把手・注口なし
- 内面は滑らか
- 大きな欠損なし
- 土器は Z 軸方向に直立
- 入力座標単位は mm / cm / m に対応（内部では mm に変換）

基本処理:
1. メッシュの幾何学的 QA（watertight、境界edge、非多様体edge等）
2. メッシュ全体を surface voxelize
3. 底部側から内部空隙 seed を自動検出
4. 高さ制限付き 3D flood fill を繰り返し、
   内部空隙が初めて外部へ接続する spill level を二分探索
5. spill level の1層下までの連結空隙を液体領域とし、内容積を計算
6. CloudCompare等で確認できる QC 用 PLY と JSON を保存

注意:
- surface voxel は厚さを持つため、内容積は一般にやや過小評価される。
- 0.5 / 1.0 / 2.0 mm など複数 pitch で収束を確認すること。
- spill level が口縁ではなく胴部・底部の穴で決まる場合、計測値は不適切。
  本コードは境界edgeとspill位置をQC出力し、検証を支援する。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

__version__ = "0.3.2"


def _dependency_error(exc: ModuleNotFoundError) -> None:
    missing = exc.name or "unknown"
    package = {
        "PIL": "Pillow",
        "numpy": "numpy",
        "scipy": "scipy",
        "trimesh": "trimesh",
    }.get(missing, missing)

    print(
        "\nERROR: 必要なPythonモジュールが見つかりません。\n"
        f"missing module : {missing}\n"
        f"install package: {package}\n\n"
        "仮想環境 (.venv) を有効にした状態で、次を実行してください。\n"
        "  python3 -m pip install -r requirements.txt\n\n"
        "requirements.txt を使わない場合:\n"
        "  python3 -m pip install numpy scipy trimesh Pillow\n",
        file=sys.stderr,
    )
    raise SystemExit(2)


try:
    import numpy as np
    import trimesh
    import PIL  # noqa: F401
    from scipy import ndimage
except ModuleNotFoundError as exc:
    _dependency_error(exc)


def load_single_mesh(path: Path) -> trimesh.Trimesh:
    """OBJ/PLY を読み込み、Scene の場合は全 geometry を結合する。"""
    obj = trimesh.load(str(path), force="mesh")

    if isinstance(obj, trimesh.Scene):
        geometries = list(obj.geometry.values())
        if not geometries:
            raise ValueError("メッシュ geometry が見つかりません。")
        mesh = trimesh.util.concatenate(geometries)
    elif isinstance(obj, trimesh.Trimesh):
        mesh = obj
    else:
        raise TypeError(f"未対応の読み込み結果です: {type(obj)}")

    if mesh.vertices.size == 0 or mesh.faces.size == 0:
        raise ValueError("頂点または三角形 face がありません。")

    return mesh


def edge_diagnostics(mesh: trimesh.Trimesh):
    """
    unique edge ごとの利用回数から境界edge・非多様体edgeを求める。
    1 faceのみで使われるedge = boundary edge
    3 face以上で使われるedge = non-manifold edge
    """
    unique_edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    inverse = np.asarray(mesh.edges_unique_inverse, dtype=np.int64)
    counts = np.bincount(inverse, minlength=len(unique_edges))

    boundary_edges = unique_edges[counts == 1]
    nonmanifold_edges = unique_edges[counts > 2]

    return boundary_edges, nonmanifold_edges


def export_edge_vertices(
    mesh: trimesh.Trimesh,
    edges: np.ndarray,
    path: Path,
) -> int:
    """edgeに含まれる頂点をQC用 point cloudとして保存。"""
    if edges.size == 0:
        return 0

    vertex_ids = np.unique(edges.reshape(-1))
    points = np.asarray(mesh.vertices)[vertex_ids]
    trimesh.points.PointCloud(points).export(str(path))
    return len(points)


def validate_mesh(
    mesh: trimesh.Trimesh,
    output_prefix: Path | None = None,
    export_qc: bool = True,
):
    """メッシュの基本QAを実行し、必要なら境界点等をPLY保存する。"""
    boundary_edges, nonmanifold_edges = edge_diagnostics(mesh)

    extents = np.asarray(mesh.extents, dtype=float)
    scale_ref = max(float(extents.max()), 1.0)
    area_tol = (scale_ref ** 2) * 1e-14
    area_faces = np.asarray(mesh.area_faces, dtype=float)
    degenerate_faces = int(np.count_nonzero(area_faces <= area_tol))

    try:
        body_count = int(mesh.body_count)
    except Exception:
        body_count = None

    report = {
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "euler_number": int(mesh.euler_number),
        "body_count": body_count,
        "boundary_edges": int(len(boundary_edges)),
        "nonmanifold_edges": int(len(nonmanifold_edges)),
        "degenerate_faces": degenerate_faces,
    }

    qc_files = {}

    if export_qc and output_prefix is not None:
        if len(boundary_edges):
            p = Path(f"{output_prefix}_mesh_boundary_points.ply")
            n = export_edge_vertices(mesh, boundary_edges, p)
            qc_files["mesh_boundary_points_ply"] = str(p)
            report["boundary_vertices_exported"] = int(n)

        if len(nonmanifold_edges):
            p = Path(f"{output_prefix}_mesh_nonmanifold_points.ply")
            n = export_edge_vertices(mesh, nonmanifold_edges, p)
            qc_files["mesh_nonmanifold_points_ply"] = str(p)
            report["nonmanifold_vertices_exported"] = int(n)

    report["qc_files"] = qc_files
    return report


def padded_world_to_index(
    vox: trimesh.voxel.VoxelGrid,
    point_xyz: np.ndarray,
    pad: int,
) -> np.ndarray:
    """world 座標を padding 後 voxel index に変換。"""
    idx = np.asarray(
        vox.points_to_indices(np.asarray(point_xyz).reshape(1, 3))[0],
        dtype=int,
    )
    return idx + pad


def padded_indices_to_points(
    vox: trimesh.voxel.VoxelGrid,
    indices: np.ndarray,
    pad: int,
) -> np.ndarray:
    """padding 後 voxel index を world 座標に戻す。"""
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

    center_xy が空隙に入っていればそれを優先。
    入っていない場合は、十分大きい空隙のうち中心に最も近いものを採用。
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

    if 0 <= cx < labels.shape[0] and 0 <= cy < labels.shape[1]:
        label_id = int(labels[cx, cy])
        if label_id > 0:
            opening = labels == label_id
            area = int(np.count_nonzero(opening))
            if area >= min_area_voxels:
                return opening, sealed_ring, area

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
            best = (labels == label_id, sealed_ring, int(area))

    return best


def find_interior_seed(
    surface: np.ndarray,
    center_xy: tuple[int, int],
    min_area_voxels: int,
    persistence: int = 3,
    close_iterations: int = 1,
    z_start: int | None = None,
    z_end: int | None = None,
):
    """
    指定したZ範囲で、中央空隙が persistence 層連続で存在する候補を探す。
    候補のうち断面積が最大のものを内部cavity seedとする。

    底部直上には「陶胎そのものの内部」が閉空隙として現れる可能性があるため、
    通常は器高の10〜60%程度に探索範囲を限定する。
    """
    nz = surface.shape[2]
    if z_start is None:
        z_start = 0
    if z_end is None:
        z_end = nz - 1

    z_start = max(0, int(z_start))
    z_end = min(nz - 1, int(z_end))

    best = None
    best_area = -1

    last_start = z_end - persistence + 1
    for k in range(z_start, max(z_start, last_start) + 1):
        candidates = []

        for offset in range(persistence):
            kk = k + offset
            if kk > z_end:
                candidates = []
                break

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
            opening, _, area = candidates[mid]

            if area > best_area:
                coords = np.argwhere(opening)
                centroid = coords.mean(axis=0)
                d2 = np.sum((coords - centroid) ** 2, axis=1)
                seed_xy = coords[int(np.argmin(d2))]
                seed_xyz = (
                    int(seed_xy[0]),
                    int(seed_xy[1]),
                    int(seed_k),
                )
                best = (seed_xyz, opening, int(area))
                best_area = int(area)

    if best is not None:
        return best

    raise RuntimeError(
        "土器内部の seed 空隙を自動検出できませんでした。\n"
        "考えられる原因:\n"
        "- 土器がZ軸に直立していない\n"
        "- voxel pitch が粗すぎる\n"
        "- 探索範囲内に連続した内部空隙がない\n"
        "- 対象形状が現在の単純器形条件から外れている"
    )


def touches_boundary(mask: np.ndarray) -> bool:
    """連結領域が計算領域の6面のどこかに接しているか。"""
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
    """
    Z <= level_k の free voxel のみを許可し、
    seedから6-connectivityで flood fill。
    """
    if level_k < seed_xyz[2]:
        raise ValueError("level_k は seed の高さ以上である必要があります。")

    allowed = free.copy()
    if level_k + 1 < allowed.shape[2]:
        allowed[:, :, level_k + 1 :] = False

    seed = np.zeros_like(free, dtype=bool)
    seed[seed_xyz] = True

    component = ndimage.binary_propagation(
        seed,
        structure=ndimage.generate_binary_structure(3, 1),
        mask=allowed,
    )

    return component


def find_spill_level(
    free: np.ndarray,
    seed_xyz: tuple[int, int, int],
):
    """
    seed内部空隙が外部境界へ初めて接続する最小Z indexを二分探索。
    """
    seed_k = int(seed_xyz[2])
    top_k = free.shape[2] - 1
    evaluations = 0

    low_component = propagate_below_level(free, seed_xyz, seed_k)
    evaluations += 1
    if touches_boundary(low_component):
        raise RuntimeError(
            "内部seedの高さですでに外部へ漏れています。\n"
            "口縁より低い位置にメッシュ穴がある可能性が高いです。\n"
            "出力される mesh_boundary_points.ply をCloudCompareで確認してください。"
        )

    high_component = propagate_below_level(free, seed_xyz, top_k)
    evaluations += 1
    if not touches_boundary(high_component):
        raise RuntimeError(
            "最上層まで許可しても内部空隙が外部へ接続しません。\n"
            "voxel化によって口が閉じてしまった可能性があります。\n"
            "pitchを小さくするか、口縁付近のメッシュを確認してください。"
        )

    lo = seed_k
    hi = top_k

    while hi - lo > 1:
        mid = (lo + hi) // 2
        comp = propagate_below_level(free, seed_xyz, mid)
        evaluations += 1

        if touches_boundary(comp):
            hi = mid
        else:
            lo = mid

    safe_k = lo
    spill_k = hi

    safe_component = propagate_below_level(free, seed_xyz, safe_k)
    spill_component = propagate_below_level(free, seed_xyz, spill_k)
    evaluations += 2

    return safe_k, spill_k, safe_component, spill_component, evaluations


def export_qc_pointcloud(
    vox: trimesh.voxel.VoxelGrid,
    mask: np.ndarray,
    pad: int,
    path: Path,
    surface_only: bool = True,
):
    """boolean voxel mask を QC 用 PLY point cloud として保存。"""
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

    points = padded_indices_to_points(vox, indices, pad=pad)
    trimesh.points.PointCloud(points).export(str(path))
    return len(points)


def make_spill_plane_region(
    spill_component: np.ndarray,
    spill_k: int,
    pad: int,
):
    """
    spill層で内部から外部へつながったfree-spaceをQC表示する。
    padding最外周は除き、元voxel grid周辺に限定する。
    """
    mask = np.zeros_like(spill_component, dtype=bool)

    border = max(pad - 1, 0)
    x0 = border
    x1 = spill_component.shape[0] - border
    y0 = border
    y1 = spill_component.shape[1] - border

    mask[x0:x1, y0:y1, spill_k] = spill_component[
        x0:x1, y0:y1, spill_k
    ]
    return mask


def estimate_volume(
    input_path: Path,
    pitch: float = 1.0,
    unit: str = "mm",
    pad: int = 4,
    min_cavity_area_mm2: float = 100.0,
    seed_persistence: int = 3,
    seed_min_fraction: float = 0.10,
    seed_max_fraction: float = 0.60,
    close_iterations: int = 1,
    output_prefix: Path | None = None,
    export_qc: bool = True,
):
    t0 = time.perf_counter()

    mesh = load_single_mesh(input_path)

    unit_scale_to_mm = {
        "mm": 1.0,
        "cm": 10.0,
        "m": 1000.0,
    }
    if unit not in unit_scale_to_mm:
        raise ValueError("unit は mm / cm / m のいずれかを指定してください。")

    scale = unit_scale_to_mm[unit]
    if scale != 1.0:
        mesh.apply_scale(scale)

    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = np.asarray(mesh.extents, dtype=float)
    center_world = bounds.mean(axis=0)

    if output_prefix is None:
        output_prefix = input_path.with_name(
            f"{input_path.stem}_voxel_{pitch:g}mm"
        )
    output_prefix = Path(output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    print(f"=== Vessel Voxel Volume v{__version__} ===")
    print("\n=== Input mesh ===")
    print(f"file       : {input_path}")
    print(f"input unit : {unit}")
    print(f"scale      : x{scale:g} -> mm")
    print(f"vertices   : {len(mesh.vertices):,}")
    print(f"faces      : {len(mesh.faces):,}")
    print(
        "extents mm : "
        f"X={extents[0]:.3f}, Y={extents[1]:.3f}, Z={extents[2]:.3f}"
    )

    print("\n=== Mesh QA ===")
    tq = time.perf_counter()
    mesh_qa = validate_mesh(
        mesh,
        output_prefix=output_prefix,
        export_qc=export_qc,
    )
    print(f"watertight          : {mesh_qa['watertight']}")
    print(f"winding consistent  : {mesh_qa['winding_consistent']}")
    print(f"body count          : {mesh_qa['body_count']}")
    print(f"boundary edges      : {mesh_qa['boundary_edges']:,}")
    print(f"non-manifold edges  : {mesh_qa['nonmanifold_edges']:,}")
    print(f"degenerate faces    : {mesh_qa['degenerate_faces']:,}")
    print(f"QA time             : {time.perf_counter() - tq:.2f} s")

    if not mesh_qa["watertight"]:
        print(
            "WARNING: メッシュはwatertightではありません。"
            "口縁以外の穴がspill levelを低くする可能性があります。"
        )
    if mesh_qa["boundary_edges"] > 0:
        print(
            "WARNING: boundary edgeがあります。"
            "QC用 mesh_boundary_points.ply を確認してください。"
        )
    if mesh_qa["nonmanifold_edges"] > 0:
        print(
            "WARNING: non-manifold edgeがあります。"
            "QC用 mesh_nonmanifold_points.ply を確認してください。"
        )

    # volume計算が後段で失敗してもメッシュ検証結果を残す
    mesh_qa_path = Path(f"{output_prefix}_mesh_qa.json")
    mesh_qa_record = {
        "program_version": __version__,
        "input": str(input_path),
        "input_unit": unit,
        "scale_to_mm": float(scale),
        "mesh_vertices": int(len(mesh.vertices)),
        "mesh_faces": int(len(mesh.faces)),
        "mesh_extents_mm": [float(v) for v in extents],
        "mesh_bounds_mm": [[float(v) for v in row] for row in bounds],
        "mesh_qa": mesh_qa,
    }
    mesh_qa_path.write_text(
        json.dumps(mesh_qa_record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"mesh QA JSON        : {mesh_qa_path}")

    if pitch <= 0:
        raise ValueError("pitch は正数にしてください。")

    print("\n=== Surface voxelization ===")
    print(f"pitch      : {pitch:.3f} mm")

    tv = time.perf_counter()
    vox = mesh.voxelized(
        pitch=pitch,
        method="subdivide",
    )
    voxelize_time = time.perf_counter() - tv

    print(f"time       : {voxelize_time:.2f} s")
    print(f"voxel grid : {tuple(int(v) for v in vox.shape)}")
    print(f"surface vox: {int(vox.filled_count):,}")

    surface_raw = np.asarray(vox.matrix, dtype=bool)
    surface = np.pad(
        surface_raw,
        pad_width=pad,
        mode="constant",
        constant_values=False,
    )

    total_cells = int(np.prod(surface.shape))
    print(f"padded grid: {surface.shape} = {total_cells:,} cells")
    print(f"bool/grid  : ~{total_cells / (1024**2):.1f} MiB per array")

    center_idx = padded_world_to_index(vox, center_world, pad=pad)
    center_xy = (int(center_idx[0]), int(center_idx[1]))

    min_area_voxels = max(
        1,
        int(math.ceil(min_cavity_area_mm2 / (pitch * pitch))),
    )

    if not (0.0 <= seed_min_fraction < seed_max_fraction <= 1.0):
        raise ValueError(
            "seed_min_fraction / seed_max_fraction は "
            "0 <= min < max <= 1 を満たしてください。"
        )

    z_span_vox = max(int(vox.shape[2]) - 1, 1)
    seed_z_start = pad + int(math.floor(seed_min_fraction * z_span_vox))
    seed_z_end = pad + int(math.ceil(seed_max_fraction * z_span_vox))

    print("\n=== Interior seed ===")
    print(
        f"search band: {seed_min_fraction:.2f}–{seed_max_fraction:.2f} "
        "of voxelized mesh height"
    )
    ts = time.perf_counter()
    seed_xyz, seed_opening, seed_area = find_interior_seed(
        surface=surface,
        center_xy=center_xy,
        min_area_voxels=min_area_voxels,
        persistence=seed_persistence,
        close_iterations=close_iterations,
        z_start=seed_z_start,
        z_end=seed_z_end,
    )
    seed_time = time.perf_counter() - ts

    seed_world = padded_indices_to_points(
        vox,
        np.asarray([seed_xyz], dtype=int),
        pad=pad,
    )[0]

    print(f"seed index : {seed_xyz}")
    print(
        f"seed XYZ mm: "
        f"{seed_world[0]:.3f}, {seed_world[1]:.3f}, {seed_world[2]:.3f}"
    )
    print(
        f"seed area  : {seed_area:,} voxels "
        f"(~{seed_area * pitch * pitch:.1f} mm^2)"
    )
    print(f"time       : {seed_time:.2f} s")

    free = ~surface

    print("\n=== Spill-level search ===")
    tf = time.perf_counter()
    safe_k, spill_k, fluid, spill_component, evaluations = find_spill_level(
        free=free,
        seed_xyz=seed_xyz,
    )
    spill_search_time = time.perf_counter() - tf

    safe_z = float(
        vox.indices_to_points(
            np.array([[0, 0, safe_k - pad]], dtype=int)
        )[0][2]
    )
    spill_z = float(
        vox.indices_to_points(
            np.array([[0, 0, spill_k - pad]], dtype=int)
        )[0][2]
    )

    zmin = float(bounds[0, 2])
    zmax = float(bounds[1, 2])
    height = max(zmax - zmin, 1e-12)
    spill_fraction = (spill_z - zmin) / height

    print(f"safe level : index {safe_k}, Z={safe_z:.3f} mm")
    print(f"spill level: index {spill_k}, Z={spill_z:.3f} mm")
    print(f"spill ratio: {spill_fraction:.3f} of mesh height")
    print(f"flood fills: {evaluations}")
    print(f"time       : {spill_search_time:.2f} s")

    rim_like = spill_fraction >= 0.75
    if rim_like:
        print(
            "QC assessment: spill levelは上部25%以内です。"
            "単純器形では口縁由来として妥当な可能性が高いです。"
        )
    else:
        print(
            "WARNING: spill levelがメッシュ上端から大きく下がっています。\n"
            "胴部・底部の穴や欠損が原因の可能性があります。\n"
            "mesh_boundary_points.ply と spill_level_region.ply を確認してください。"
        )

    fluid_voxels = int(np.count_nonzero(fluid))
    volume_mm3 = fluid_voxels * (pitch ** 3)
    volume_ml = volume_mm3 / 1000.0
    volume_l = volume_ml / 1000.0

    print("\n=== Maximum retained volume ===")
    print(f"fluid voxels : {fluid_voxels:,}")
    print(f"volume       : {volume_mm3:,.1f} mm^3")
    print(f"volume       : {volume_ml:,.3f} mL")
    print(f"volume       : {volume_l:.6f} L")
    print(
        f"vertical discretization bracket: "
        f"{safe_z:.3f} mm < spill <= {spill_z:.3f} mm"
    )

    qc_files = dict(mesh_qa.get("qc_files", {}))
    qc_files["mesh_qa_json"] = str(mesh_qa_path)

    if export_qc:
        print("\n=== Export QC ===")

        cavity_path = Path(f"{output_prefix}_fluid_surface.ply")
        n = export_qc_pointcloud(
            vox=vox,
            mask=fluid,
            pad=pad,
            path=cavity_path,
            surface_only=True,
        )
        qc_files["fluid_surface_ply"] = str(cavity_path)
        print(f"fluid surface : {cavity_path} ({n:,} points)")

        spill_region = make_spill_plane_region(
            spill_component=spill_component,
            spill_k=spill_k,
            pad=pad,
        )
        spill_path = Path(f"{output_prefix}_spill_level_region.ply")
        n = export_qc_pointcloud(
            vox=vox,
            mask=spill_region,
            pad=pad,
            path=spill_path,
            surface_only=False,
        )
        qc_files["spill_level_region_ply"] = str(spill_path)
        print(f"spill region  : {spill_path} ({n:,} points)")

        seed_mask = np.zeros_like(surface, dtype=bool)
        seed_mask[seed_xyz] = True
        seed_path = Path(f"{output_prefix}_seed_point.ply")
        export_qc_pointcloud(
            vox=vox,
            mask=seed_mask,
            pad=pad,
            path=seed_path,
            surface_only=False,
        )
        qc_files["seed_point_ply"] = str(seed_path)
        print(f"seed point    : {seed_path}")

    total_time = time.perf_counter() - t0

    summary = {
        "program_version": __version__,
        "definition": "maximum retained liquid volume immediately below first spill level",
        "input": str(input_path),
        "input_unit": unit,
        "scale_to_mm": float(scale),
        "pitch_mm": float(pitch),
        "mesh_vertices": int(len(mesh.vertices)),
        "mesh_faces": int(len(mesh.faces)),
        "mesh_extents_mm": [float(v) for v in extents],
        "mesh_bounds_mm": [[float(v) for v in row] for row in bounds],
        "mesh_qa": mesh_qa,
        "voxel_grid_shape": [int(v) for v in vox.shape],
        "padded_grid_shape": [int(v) for v in surface.shape],
        "surface_voxels": int(vox.filled_count),
        "seed_search_fraction": [
            float(seed_min_fraction),
            float(seed_max_fraction),
        ],
        "seed_index": [int(v) for v in seed_xyz],
        "seed_xyz_mm": [float(v) for v in seed_world],
        "safe_level_index": int(safe_k),
        "safe_level_z_mm": float(safe_z),
        "spill_level_index": int(spill_k),
        "spill_level_z_mm": float(spill_z),
        "spill_fraction_of_mesh_height": float(spill_fraction),
        "spill_rim_like_soft_check": bool(rim_like),
        "fluid_voxels": fluid_voxels,
        "volume_mm3": float(volume_mm3),
        "volume_ml": float(volume_ml),
        "volume_l": float(volume_l),
        "vertical_resolution_mm": float(pitch),
        "voxelize_time_s": float(voxelize_time),
        "seed_time_s": float(seed_time),
        "spill_search_time_s": float(spill_search_time),
        "total_time_s": float(total_time),
        "qc_files": qc_files,
    }

    json_path = Path(f"{output_prefix}_result.json")
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nresult JSON : {json_path}")
    print(f"total time  : {total_time:.2f} s")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description=(
            "OBJ/PLY土器メッシュから、最初に液体が溢れる直前の最大内容積を"
            "voxel法で推定"
        )
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="入力 OBJ または PLY",
    )
    parser.add_argument(
        "--pitch",
        type=float,
        default=1.0,
        help="voxel edge length [mm]。既定値 1.0",
    )
    parser.add_argument(
        "--unit",
        choices=["mm", "cm", "m"],
        default="mm",
        help="入力メッシュの座標単位。mm / cm / m。既定値 mm",
    )
    parser.add_argument(
        "--pad",
        type=int,
        default=4,
        help="voxel grid 周囲の余白セル数。既定値 4",
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
        help="内部seedと認定するため連続して検出するslice数。既定値 3",
    )
    parser.add_argument(
        "--seed-min-fraction",
        type=float,
        default=0.10,
        help="seed探索を開始する器高割合。既定値 0.10",
    )
    parser.add_argument(
        "--seed-max-fraction",
        type=float,
        default=0.60,
        help="seed探索を終了する器高割合。既定値 0.60",
    )
    parser.add_argument(
        "--close-iters",
        type=int,
        default=1,
        help="seed検出用2D断面の1-cell gapを閉じるclosing回数。既定値 1",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=None,
        help="出力ファイル名のprefix",
    )
    parser.add_argument(
        "--no-qc",
        action="store_true",
        help="QC用 PLY を出力しない",
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
            seed_min_fraction=args.seed_min_fraction,
            seed_max_fraction=args.seed_max_fraction,
            close_iterations=args.close_iters,
            output_prefix=args.output_prefix,
            export_qc=not args.no_qc,
        )
    except ModuleNotFoundError as exc:
        _dependency_error(exc)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
