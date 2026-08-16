#!/usr/bin/env python3
"""
PotteryVolumeCalculator
Version 1.2.0

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
9. raw boundary edge を「破片境界候補」として別系統で保存
10. duplicate removal 前後の boundary を比較し、spillとの近接も診断

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
import colorsys
import csv
import io
import json
import math
import platform
import sys
import time
from contextlib import redirect_stdout
from importlib import metadata as importlib_metadata
from pathlib import Path

__version__ = "1.2.0"


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
        "  python3 -m pip install numpy scipy trimesh Pillow\n"
        "PyMeshLab cross-checkも使う場合:\n"
        "  python3 -m pip install pymeshlab\n",
        file=sys.stderr,
    )
    raise SystemExit(2)


try:
    import numpy as np
    import trimesh
    import PIL  # noqa: F401  # trimesh の soft dependency 対策
    from scipy import ndimage
    from scipy.spatial import cKDTree
except ModuleNotFoundError as exc:
    dependency_error(exc)

# PyMeshLab is an optional cross-check layer in v1.2.
# Core preprocessing and volume calculation do not depend on its plugins.
try:
    import pymeshlab
    PYMESHLAB_IMPORT_ERROR = None
except Exception as exc:  # plugin/dynamic-library import failures are also non-fatal
    pymeshlab = None
    PYMESHLAB_IMPORT_ERROR = repr(exc)


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

    archaeological_dir = base / "archaeological"
    processed_dir = base / "processed"
    qa_dir = base / "qa"
    run_dir = base / pitch_label(pitch)
    run_qa_dir = run_dir / "qa"
    qc_dir = run_dir / "qc"

    for p in (
        base, archaeological_dir, processed_dir, qa_dir,
        run_dir, run_qa_dir, qc_dir
    ):
        p.mkdir(parents=True, exist_ok=True)

    return {
        "base": base,
        "archaeological": archaeological_dir,
        "processed": processed_dir,
        "qa": qa_dir,
        "run": run_dir,
        "run_qa": run_qa_dir,
        "qc": qc_dir,
    }



# ----------------------------------------------------------------------
# Archaeological derivative: raw fragment-boundary candidates
# ----------------------------------------------------------------------

def boundary_edges_from_arrays(vertices, faces):
    """Trimesh topologyから1 faceだけに属するboundary edgeを取得。"""
    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
        validate=False,
    )
    unique_edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    inverse = np.asarray(mesh.edges_unique_inverse, dtype=np.int64)
    counts = np.bincount(inverse, minlength=len(unique_edges))
    return mesh, unique_edges[counts == 1]


def sample_edge_points(vertices, edges, spacing_native):
    """
    boundary edgeを線としてCloudCompareで見やすくするため等間隔サンプリング。
    元メッシュの座標単位のまま返す。
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    edges = np.asarray(edges, dtype=np.int64)
    if len(edges) == 0:
        return np.empty((0, 3), dtype=np.float64)

    chunks = []
    spacing_native = max(float(spacing_native), np.finfo(float).eps)
    for a, b in edges:
        p0 = vertices[a]
        p1 = vertices[b]
        length = float(np.linalg.norm(p1 - p0))
        n = max(2, int(math.ceil(length / spacing_native)) + 1)
        t = np.linspace(0.0, 1.0, n, endpoint=True)[:, None]
        chunks.append(p0[None, :] * (1.0 - t) + p1[None, :] * t)
    return np.vstack(chunks)


def boundary_statistics(vertices, edges, unit):
    vertices = np.asarray(vertices, dtype=np.float64)
    edges = np.asarray(edges, dtype=np.int64)
    if len(edges) == 0:
        return {
            "boundary_edges": 0,
            "boundary_vertices": 0,
            "total_boundary_length": 0.0,
            "length_unit": unit,
        }
    seg = vertices[edges[:, 1]] - vertices[edges[:, 0]]
    lengths = np.linalg.norm(seg, axis=1)
    return {
        "boundary_edges": int(len(edges)),
        "boundary_vertices": int(len(np.unique(edges.reshape(-1)))),
        "total_boundary_length": float(lengths.sum()),
        "mean_edge_length": float(lengths.mean()),
        "median_edge_length": float(np.median(lengths)),
        "max_edge_length": float(lengths.max()),
        "length_unit": unit,
    }


def face_components(mesh):
    """
    face adjacencyをUnion-Findで分割する。
    raw meshでは接合線でトポロジーが切れていれば、破片候補componentとして残る。
    """
    n_faces = len(mesh.faces)
    parent = np.arange(n_faces, dtype=np.int64)
    rank = np.zeros(n_faces, dtype=np.int8)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(int(a)), find(int(b))
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            parent[ra] = rb
        elif rank[ra] > rank[rb]:
            parent[rb] = ra
        else:
            parent[rb] = ra
            rank[ra] += 1

    for a, b in np.asarray(mesh.face_adjacency, dtype=np.int64):
        union(a, b)

    groups = {}
    for f in range(n_faces):
        root = find(f)
        groups.setdefault(root, []).append(f)
    components = [np.asarray(v, dtype=np.int64) for v in groups.values()]
    components.sort(key=len, reverse=True)
    return components


def component_color(index, total):
    """component表示用の決定的なRGB色。解析値には使用しない。"""
    hue = (index * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.95)
    return np.array([r, g, b, 1.0]) * 255.0


def export_component_products(mesh, components, archaeological_dir, unit, prefix):
    """component統計CSV/JSONと色分けPLYを保存する。"""
    rows = []
    face_colors = np.zeros((len(mesh.faces), 4), dtype=np.uint8)

    for i, face_ids in enumerate(components, start=1):
        face_ids = np.asarray(face_ids, dtype=np.int64)
        face_colors[face_ids] = component_color(i, len(components)).astype(np.uint8)
        component_faces = np.asarray(mesh.faces)[face_ids]
        vertex_ids = np.unique(component_faces.reshape(-1))
        pts = np.asarray(mesh.vertices)[vertex_ids]
        area = float(np.asarray(mesh.area_faces)[face_ids].sum())
        centroid = pts.mean(axis=0)
        bmin = pts.min(axis=0)
        bmax = pts.max(axis=0)
        rows.append({
            "component_id": i,
            "faces": int(len(face_ids)),
            "vertices": int(len(vertex_ids)),
            "surface_area": area,
            "area_unit": f"{unit}^2",
            "centroid_x": float(centroid[0]),
            "centroid_y": float(centroid[1]),
            "centroid_z": float(centroid[2]),
            "bbox_min_x": float(bmin[0]),
            "bbox_min_y": float(bmin[1]),
            "bbox_min_z": float(bmin[2]),
            "bbox_max_x": float(bmax[0]),
            "bbox_max_y": float(bmax[1]),
            "bbox_max_z": float(bmax[2]),
            "length_unit": unit,
        })

    csv_path = archaeological_dir / f"{prefix}_components.csv"
    if rows:
        with csv_path.open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    json_path = archaeological_dir / f"{prefix}_components.json"
    write_json(json_path, {
        "note": (
            "Connected components are topology-derived fragment candidates; "
            "they are not automatically asserted to be archaeological sherds."
        ),
        "component_count": len(rows),
        "components": rows,
    })

    colored_path = archaeological_dir / f"{prefix}_components_colored.ply"
    colored_mesh = mesh.copy()
    colored_mesh.visual.face_colors = face_colors
    colored_mesh.export(str(colored_path))

    return {
        "components_csv": str(csv_path),
        "components_json": str(json_path),
        "components_colored_ply": str(colored_path),
        "component_count": int(len(rows)),
    }


def export_boundary_products(vertices, faces, archaeological_dir, unit, prefix,
                             sample_spacing_mm=0.5):
    """
    boundaryを考古学的派生データとして保存。
    sample_spacing_mmは入力単位へ変換して線上サンプルを作る。
    """
    mesh, edges = boundary_edges_from_arrays(vertices, faces)
    scale = UNIT_SCALE_TO_MM[unit]
    spacing_native = sample_spacing_mm / scale
    stats = boundary_statistics(vertices, edges, unit)
    stats["sample_spacing_mm"] = float(sample_spacing_mm)

    vertex_path = archaeological_dir / f"{prefix}_boundary_vertices.ply"
    sampled_path = archaeological_dir / f"{prefix}_boundaries_sampled.ply"
    stats_path = archaeological_dir / f"{prefix}_boundary_stats.json"

    if len(edges):
        ids = np.unique(edges.reshape(-1))
        trimesh.points.PointCloud(np.asarray(vertices)[ids]).export(str(vertex_path))
        sampled = sample_edge_points(vertices, edges, spacing_native)
        trimesh.points.PointCloud(sampled).export(str(sampled_path))
    else:
        sampled = np.empty((0, 3), dtype=np.float64)

    component_info = export_component_products(
        mesh, face_components(mesh), archaeological_dir, unit, prefix
    )

    stats.update({
        "boundary_vertices_ply": str(vertex_path) if len(edges) else None,
        "boundaries_sampled_ply": str(sampled_path) if len(edges) else None,
        "sampled_points": int(len(sampled)),
        **component_info,
    })
    write_json(stats_path, stats)
    stats["boundary_stats_json"] = str(stats_path)
    return stats, sampled


def export_boundary_comparison(archaeological_dir, raw_stats, cleaned_stats,
                               vertices_removed):
    raw_edges = int(raw_stats.get("boundary_edges", 0))
    cleaned_edges = int(cleaned_stats.get("boundary_edges", 0))
    comparison = {
        "raw_boundary_edges": raw_edges,
        "after_duplicate_removal_boundary_edges": cleaned_edges,
        "boundary_edges_removed": raw_edges - cleaned_edges,
        "boundary_edges_remaining_fraction": (
            cleaned_edges / raw_edges if raw_edges else None
        ),
        "raw_connected_components": raw_stats.get("component_count"),
        "after_duplicate_removal_connected_components": cleaned_stats.get("component_count"),
        "vertices_removed_by_exact_weld": int(vertices_removed),
        "interpretation": (
            "Large reduction after exact-coordinate weld suggests topological seams at "
            "coincident geometry. Remaining boundaries may represent actual gaps, rim, "
            "or other open boundaries."
        ),
    }
    path = archaeological_dir / "boundary_before_after_comparison.json"
    write_json(path, comparison)
    comparison["comparison_json"] = str(path)
    return comparison


def export_colored_overlap(boundary_points_native, spill_points_native, path):
    """raw fragment boundary候補とspill free-spaceを1つの色付きPLYに保存。"""
    boundary_points_native = np.asarray(boundary_points_native, dtype=np.float64)
    spill_points_native = np.asarray(spill_points_native, dtype=np.float64)
    if len(boundary_points_native) == 0 or len(spill_points_native) == 0:
        return 0
    points = np.vstack([boundary_points_native, spill_points_native])
    colors = np.vstack([
        np.tile(np.array([[255, 60, 60, 255]], dtype=np.uint8), (len(boundary_points_native), 1)),
        np.tile(np.array([[40, 180, 255, 255]], dtype=np.uint8), (len(spill_points_native), 1)),
    ])
    trimesh.points.PointCloud(points, colors=colors).export(str(path))
    return int(len(points))


def boundary_spill_proximity(boundary_points_native, spill_points_native, unit, pitch_mm):
    """spill付近free voxelがraw boundary候補にどの程度近いかを定量化。"""
    boundary_points_native = np.asarray(boundary_points_native, dtype=np.float64)
    spill_points_native = np.asarray(spill_points_native, dtype=np.float64)
    if len(boundary_points_native) == 0 or len(spill_points_native) == 0:
        return {"available": False}

    scale = UNIT_SCALE_TO_MM[unit]
    boundary_mm = boundary_points_native * scale
    spill_mm = spill_points_native * scale
    tree = cKDTree(boundary_mm)
    distances, _ = tree.query(spill_mm, k=1, workers=-1)
    distances = np.asarray(distances, dtype=np.float64)
    return {
        "available": True,
        "spill_points_evaluated": int(len(distances)),
        "distance_min_mm": float(distances.min()),
        "distance_median_mm": float(np.median(distances)),
        "distance_p90_mm": float(np.percentile(distances, 90)),
        "fraction_within_half_pitch": float(np.mean(distances <= 0.5 * pitch_mm)),
        "fraction_within_one_pitch": float(np.mean(distances <= pitch_mm)),
        "interpretation": (
            "A high fraction within one voxel pitch means the detected spill path is "
            "spatially close to raw boundary/seam candidates; this supports, but does "
            "not by itself prove, seam-related leakage."
        ),
    }

# ----------------------------------------------------------------------
# Stage A: deterministic preprocessing + optional PyMeshLab cross-check
# ----------------------------------------------------------------------

def load_mesh_arrays_with_trimesh(input_path: Path):
    """
    File I/O is handled only by Trimesh.
    process=False prevents automatic topology edits during loading.
    """
    loaded = trimesh.load(
        str(input_path),
        process=False,
        force="mesh",
    )

    if isinstance(loaded, trimesh.Scene):
        geometries = [
            g for g in loaded.geometry.values()
            if isinstance(g, trimesh.Trimesh)
            and len(g.vertices) > 0
            and len(g.faces) > 0
        ]
        if not geometries:
            raise ValueError("入力ファイルから三角形メッシュを取得できませんでした。")
        loaded = trimesh.util.concatenate(geometries)

    if not isinstance(loaded, trimesh.Trimesh):
        raise TypeError(f"Trimeshとして読み込めませんでした: {type(loaded)}")

    if len(loaded.vertices) == 0 or len(loaded.faces) == 0:
        raise ValueError("入力メッシュに頂点または三角形faceがありません。")

    vertices = np.asarray(loaded.vertices, dtype=np.float64).copy()
    faces = np.asarray(loaded.faces, dtype=np.int64).copy()

    if not np.isfinite(vertices).all():
        raise ValueError("入力メッシュの頂点座標に NaN または Inf があります。")
    if faces.min() < 0 or faces.max() >= len(vertices):
        raise ValueError("face index が頂点配列の範囲外です。")

    return vertices, faces


def deterministic_exact_vertex_cleanup(vertices, faces):
    """
    Exact-coordinate vertex welding implemented only with NumPy.

    - Removes unreferenced vertices.
    - Merges only vertices whose XYZ values are exactly equal.
    - Does NOT merge merely close vertices.
    - Does NOT move any vertex.
    - Does NOT remove or add faces.

    Vertex ordering follows the first occurrence in the referenced input set.
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)

    referenced_ids = np.unique(faces.reshape(-1))
    referenced_vertices = vertices[referenced_ids]

    unique_sorted, first_idx, inverse_sorted = np.unique(
        referenced_vertices,
        axis=0,
        return_index=True,
        return_inverse=True,
    )

    # Preserve first-occurrence order rather than np.unique's lexicographic order.
    first_order = np.argsort(first_idx)
    unique_vertices = unique_sorted[first_order]

    sorted_to_first_order = np.empty(len(first_order), dtype=np.int64)
    sorted_to_first_order[first_order] = np.arange(len(first_order), dtype=np.int64)
    inverse_first_order = sorted_to_first_order[inverse_sorted]

    old_to_new = np.full(len(vertices), -1, dtype=np.int64)
    old_to_new[referenced_ids] = inverse_first_order
    new_faces = old_to_new[faces]

    # Strong geometry-preservation check:
    # every referenced old vertex must map to exactly the same XYZ.
    mapped_back = unique_vertices[old_to_new[referenced_ids]]
    geometry_preserved_exact = bool(
        np.array_equal(referenced_vertices, mapped_back, equal_nan=True)
    )

    if not geometry_preserved_exact:
        raise RuntimeError("exact vertex weld の幾何座標保存検証に失敗しました。")

    report = {
        "input_vertices": int(len(vertices)),
        "input_faces": int(len(faces)),
        "referenced_vertices": int(len(referenced_ids)),
        "unreferenced_vertices_removed": int(len(vertices) - len(referenced_ids)),
        "exact_duplicate_vertices_removed": int(len(referenced_ids) - len(unique_vertices)),
        "output_vertices": int(len(unique_vertices)),
        "output_faces": int(len(new_faces)),
        "faces_added_or_removed": int(len(new_faces) - len(faces)),
        "geometry_preserved_exact": geometry_preserved_exact,
        "coordinate_tolerance": 0.0,
        "vertex_positions_moved": False,
    }

    return unique_vertices, new_faces, report


def topology_summary_from_arrays(vertices, faces):
    """
    Deterministic topology summary based on edge incidence.

    This is the reference QA used by the calculator; it does not depend on
    PyMeshLab plugin availability.
    """
    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
        validate=False,
    )

    edges = np.sort(
        np.vstack([
            mesh.faces[:, [0, 1]],
            mesh.faces[:, [1, 2]],
            mesh.faces[:, [2, 0]],
        ]),
        axis=1,
    )
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)

    boundary_mask = counts == 1
    nonmanifold_mask = counts > 2
    boundary_edges = unique_edges[boundary_mask]
    nonmanifold_edges = unique_edges[nonmanifold_mask]

    referenced = np.unique(mesh.faces.reshape(-1))
    components = face_components(mesh)

    # A 2-manifold with boundary permits edge incidence 1 or 2;
    # a closed 2-manifold requires every edge incidence exactly 2.
    is_two_manifold_edges = bool(np.all(counts <= 2))
    is_closed_two_manifold = bool(np.all(counts == 2))

    if len(nonmanifold_edges):
        nonmanifold_vertices = np.unique(nonmanifold_edges.reshape(-1))
    else:
        nonmanifold_vertices = np.empty(0, dtype=np.int64)

    return {
        "vertices_number": int(len(mesh.vertices)),
        "faces_number": int(len(mesh.faces)),
        "edges_number": int(len(unique_edges)),
        "boundary_edges": int(np.count_nonzero(boundary_mask)),
        "connected_components_number": int(len(components)),
        "is_mesh_two_manifold": is_two_manifold_edges,
        "is_closed_two_manifold": is_closed_two_manifold,
        "non_two_manifold_edges": int(np.count_nonzero(nonmanifold_mask)),
        "non_two_manifold_vertices": int(len(nonmanifold_vertices)),
        "unreferenced_vertices": int(len(mesh.vertices) - len(referenced)),
        "winding_consistent_trimesh": bool(mesh.is_winding_consistent),
        "watertight_trimesh": bool(mesh.is_watertight),
    }


def get_installed_version(distribution_name: str):
    try:
        return importlib_metadata.version(distribution_name)
    except Exception:
        return None


def pymeshlab_loaded_filter_names(ms=None):
    """
    Returns only filters we can positively verify as loaded.

    We never call apply_filter blindly. This is important because apply_filter
    itself may exist even when a particular plugin/filter is not loaded.
    """
    names = set()

    if pymeshlab is None:
        return names, "unavailable"

    module_filter_list = getattr(pymeshlab, "filter_list", None)
    if callable(module_filter_list):
        try:
            names.update(str(x) for x in module_filter_list())
            return names, "pymeshlab.filter_list"
        except Exception:
            pass

    if ms is not None:
        # Newer generated filter methods, when loaded, appear as MeshSet methods.
        for name in (
            "get_topological_measures",
            "meshing_remove_duplicate_vertices",
            "meshing_remove_unreferenced_vertices",
        ):
            if callable(getattr(ms, name, None)):
                names.add(name)

        # Older releases may only expose print_filter_list().
        printer = getattr(ms, "print_filter_list", None)
        if callable(printer):
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    printer()
                text = buf.getvalue()
                for name in (
                    "get_topological_measures",
                    "meshing_remove_duplicate_vertices",
                    "meshing_remove_unreferenced_vertices",
                ):
                    if name in text:
                        names.add(name)
                if names:
                    return names, "MeshSet.print_filter_list"
            except Exception:
                pass

    return names, "direct-method inspection"


def pymeshlab_call_verified(ms, filter_name, loaded_filters, **kwargs):
    """
    Call a PyMeshLab filter ONLY after confirming that it is loaded.
    """
    if filter_name not in loaded_filters:
        raise RuntimeError(f"PyMeshLab filter not loaded: {filter_name}")

    direct = getattr(ms, filter_name, None)
    if callable(direct):
        return direct(**kwargs)

    apply_filter = getattr(ms, "apply_filter", None)
    if callable(apply_filter):
        return apply_filter(filter_name, **kwargs)

    raise RuntimeError(
        f"PyMeshLab filterはロード済みですが呼び出しAPIがありません: {filter_name}"
    )


def pymeshlab_environment_report():
    report = {
        "available": pymeshlab is not None,
        "import_error": PYMESHLAB_IMPORT_ERROR,
        "version": get_installed_version("pymeshlab"),
        "plugins_loaded": None,
        "filter_list_api_available": False,
        "loaded_filter_count": None,
        "required_filters": {},
    }

    if pymeshlab is None:
        return report

    number_plugins = getattr(pymeshlab, "number_plugins", None)
    if callable(number_plugins):
        try:
            report["plugins_loaded"] = int(number_plugins())
        except Exception as exc:
            report["plugins_loaded_error"] = repr(exc)

    report["filter_list_api_available"] = bool(
        callable(getattr(pymeshlab, "filter_list", None))
    )

    # Inspect module-level list and, for older releases, MeshSet methods/list.
    try:
        probe_ms = pymeshlab.MeshSet()
    except Exception:
        probe_ms = None
    names, source = pymeshlab_loaded_filter_names(probe_ms)
    if names:
        report["loaded_filter_count"] = int(len(names))
    report["filter_discovery_source"] = source

    for name in (
        "get_topological_measures",
        "meshing_remove_duplicate_vertices",
        "meshing_remove_unreferenced_vertices",
    ):
        report["required_filters"][name] = bool(name in names)

    return report


def pymeshlab_crosscheck(
    vertices_before,
    faces_before,
    reference_before,
    vertices_after,
    faces_after,
    reference_after,
    qa_dir: Path,
    require_pymeshlab: bool = False,
):
    """
    Optional independent cross-check.

    The calculation mesh NEVER comes from PyMeshLab in v1.2.
    PyMeshLab is allowed only to check the deterministic baseline.
    """
    env = pymeshlab_environment_report()
    report = {
        "environment": env,
        "status": "unavailable",
        "used_for_calculation_mesh": False,
        "topology_before": None,
        "topology_after": None,
        "cleanup_crosscheck": None,
        "synthetic_smoke_test": None,
        "errors": [],
    }

    if pymeshlab is None:
        write_json(qa_dir / "pymeshlab_crosscheck.json", report)
        if require_pymeshlab:
            raise RuntimeError(
                "PyMeshLabが利用できません。--require-pymeshlab が指定されています。"
            )
        return report

    try:
        pm_mesh = pymeshlab.Mesh(
            vertex_matrix=np.asarray(vertices_before, dtype=np.float64),
            face_matrix=np.asarray(faces_before, dtype=np.int32),
        )
        ms = pymeshlab.MeshSet()
        ms.add_mesh(pm_mesh, "input_crosscheck")
    except Exception as exc:
        report["status"] = "mesh_construction_failed"
        report["errors"].append(repr(exc))
        write_json(qa_dir / "pymeshlab_crosscheck.json", report)
        if require_pymeshlab:
            raise RuntimeError(f"PyMeshLab mesh construction failed: {exc}")
        return report

    loaded_filters, discovery_source = pymeshlab_loaded_filter_names(ms)
    report["environment"]["filter_discovery_source"] = discovery_source
    report["environment"]["loaded_filter_count"] = int(len(loaded_filters))
    for name in report["environment"]["required_filters"]:
        report["environment"]["required_filters"][name] = bool(
            name in loaded_filters
        )

    # Topological measures, if actually loaded.
    topo_name = "get_topological_measures"
    if topo_name in loaded_filters:
        try:
            topo_before = pymeshlab_call_verified(
                ms, topo_name, loaded_filters
            )
            report["topology_before"] = jsonable(topo_before)
        except Exception as exc:
            report["errors"].append(
                f"get_topological_measures(before): {exc!r}"
            )

    # Cleanup cross-check, if both filters are actually loaded.
    dup_name = "meshing_remove_duplicate_vertices"
    unref_name = "meshing_remove_unreferenced_vertices"
    if dup_name in loaded_filters and unref_name in loaded_filters:
        try:
            ms_clean = pymeshlab.MeshSet()
            ms_clean.add_mesh(
                pymeshlab.Mesh(
                    vertex_matrix=np.asarray(vertices_before, dtype=np.float64),
                    face_matrix=np.asarray(faces_before, dtype=np.int32),
                ),
                "cleanup_crosscheck",
            )

            pymeshlab_call_verified(ms_clean, dup_name, loaded_filters)
            pymeshlab_call_verified(ms_clean, unref_name, loaded_filters)

            pm_after = ms_clean.current_mesh()
            compact = getattr(pm_after, "compact", None)
            if callable(compact):
                compact()

            pml_vertices = np.asarray(
                pm_after.vertex_matrix(), dtype=np.float64
            ).copy()
            pml_faces = np.asarray(
                pm_after.face_matrix(), dtype=np.int64
            ).copy()

            pml_topology = topology_summary_from_arrays(
                pml_vertices, pml_faces
            )
            report["cleanup_crosscheck"] = {
                "pymeshlab_vertices": int(len(pml_vertices)),
                "pymeshlab_faces": int(len(pml_faces)),
                "reference_vertices": int(len(vertices_after)),
                "reference_faces": int(len(faces_after)),
                "vertex_count_matches_reference": bool(
                    len(pml_vertices) == len(vertices_after)
                ),
                "face_count_matches_reference": bool(
                    len(pml_faces) == len(faces_after)
                ),
                "pymeshlab_topology_after_cleanup": pml_topology,
                "reference_topology_after_cleanup": reference_after,
            }

            if topo_name in loaded_filters:
                try:
                    report["topology_after"] = jsonable(
                        pymeshlab_call_verified(
                            ms_clean, topo_name, loaded_filters
                        )
                    )
                except Exception as exc:
                    report["errors"].append(
                        f"get_topological_measures(after): {exc!r}"
                    )

            # Synthetic smoke test for the duplicate-removal plugin.
            sv = np.array([
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [1.0, 0.0, 0.0],  # duplicate of vertex 1
                [1.0, 1.0, 0.0],
                [0.0, 1.0, 0.0],  # duplicate of vertex 2
            ], dtype=np.float64)
            sf = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int32)

            sms = pymeshlab.MeshSet()
            sms.add_mesh(
                pymeshlab.Mesh(vertex_matrix=sv, face_matrix=sf),
                "synthetic_duplicate_test",
            )
            before_n = int(sms.current_mesh().vertex_number())
            pymeshlab_call_verified(sms, dup_name, loaded_filters)
            pymeshlab_call_verified(sms, unref_name, loaded_filters)
            after_n = int(sms.current_mesh().vertex_number())

            report["synthetic_smoke_test"] = {
                "input_vertices": before_n,
                "output_vertices": after_n,
                "expected_output_vertices": 4,
                "passed": bool(after_n == 4),
            }

        except Exception as exc:
            report["errors"].append(f"cleanup cross-check: {exc!r}")

    required_available = all(
        report["environment"]["required_filters"].values()
    )
    smoke_ok = (
        report["synthetic_smoke_test"] is None
        or report["synthetic_smoke_test"].get("passed", False)
    )

    if required_available and not report["errors"] and smoke_ok:
        report["status"] = "fully_available_and_passed"
    elif loaded_filters:
        report["status"] = "partial_or_failed"
    else:
        report["status"] = "plugins_or_required_filters_unavailable"

    write_json(qa_dir / "pymeshlab_crosscheck.json", report)

    if require_pymeshlab and report["status"] != "fully_available_and_passed":
        raise RuntimeError(
            "PyMeshLab cross-checkが完全成功しませんでした。"
            "qa/pymeshlab_crosscheck.json を確認してください。"
        )

    return report


def stage_a_preprocess(
    input_path: Path,
    processed_dir: Path,
    qa_dir: Path,
    archaeological_dir: Path,
    unit: str,
    boundary_sample_mm: float,
    require_pymeshlab: bool = False,
):
    """
    Reference preprocessing:
      1. Trimesh file I/O, process=False
      2. Preserve raw archaeological boundary derivatives
      3. Deterministic raw topology QA
      4. NumPy exact-coordinate weld + unreferenced removal
      5. Deterministic post-weld topology QA
      6. Optional PyMeshLab cross-check ONLY
    """
    vertices_before, faces_before = load_mesh_arrays_with_trimesh(input_path)

    raw_boundary_stats, raw_boundary_samples = export_boundary_products(
        vertices_before,
        faces_before,
        archaeological_dir,
        unit,
        prefix="raw",
        sample_spacing_mm=boundary_sample_mm,
    )

    topology_before = topology_summary_from_arrays(
        vertices_before, faces_before
    )
    write_json(qa_dir / "topology_before_exact_weld.json", topology_before)

    vertices_after, faces_after, cleanup = deterministic_exact_vertex_cleanup(
        vertices_before, faces_before
    )

    topology_after = topology_summary_from_arrays(
        vertices_after, faces_after
    )
    write_json(qa_dir / "topology_after_exact_weld.json", topology_after)
    write_json(qa_dir / "exact_weld_report.json", cleanup)

    cleaned_boundary_stats, cleaned_boundary_samples = export_boundary_products(
        vertices_after,
        faces_after,
        archaeological_dir,
        unit,
        prefix="after_exact_weld",
        sample_spacing_mm=boundary_sample_mm,
    )

    boundary_comparison = export_boundary_comparison(
        archaeological_dir,
        raw_boundary_stats,
        cleaned_boundary_stats,
        vertices_removed=(
            cleanup["exact_duplicate_vertices_removed"]
            + cleanup["unreferenced_vertices_removed"]
        ),
    )

    cleaned_path = processed_dir / f"{input_path.stem}_exact_welded.ply"
    trimesh.Trimesh(
        vertices=vertices_after,
        faces=faces_after,
        process=False,
        validate=False,
    ).export(str(cleaned_path))

    pml_report = pymeshlab_crosscheck(
        vertices_before=vertices_before,
        faces_before=faces_before,
        reference_before=topology_before,
        vertices_after=vertices_after,
        faces_after=faces_after,
        reference_after=topology_after,
        qa_dir=qa_dir,
        require_pymeshlab=require_pymeshlab,
    )

    report = {
        "reference_engine": "NumPy + Trimesh",
        "before": {
            "counts": {
                "vertices": int(len(vertices_before)),
                "faces": int(len(faces_before)),
            },
            "summary": topology_before,
        },
        "after": {
            "counts": {
                "vertices": int(len(vertices_after)),
                "faces": int(len(faces_after)),
            },
            "summary": topology_after,
        },
        "cleanup": cleanup,
        "vertices_removed": int(
            cleanup["exact_duplicate_vertices_removed"]
            + cleanup["unreferenced_vertices_removed"]
        ),
        "faces_changed": int(len(faces_after) - len(faces_before)),
        "processed_mesh": str(cleaned_path),
        "input_reader": "trimesh",
        "processed_mesh_writer": "trimesh",
        "pymeshlab_crosscheck": pml_report,
        "raw_boundary": raw_boundary_stats,
        "after_exact_weld_boundary": cleaned_boundary_stats,
        "boundary_comparison": boundary_comparison,
    }
    write_json(qa_dir / "preprocessing_summary.json", report)

    archaeological = {
        "raw_boundary_stats": raw_boundary_stats,
        "cleaned_boundary_stats": cleaned_boundary_stats,
        "boundary_comparison": boundary_comparison,
        "raw_boundary_samples_native": raw_boundary_samples,
        "cleaned_boundary_samples_native": cleaned_boundary_samples,
    }

    return vertices_after, faces_after, report, archaeological


def environment_diagnostics():
    """Return runtime diagnostics without requiring an input mesh."""
    report = {
        "program_version": __version__,
        "python_version": sys.version,
        "platform": platform.platform(),
        "packages": {
            "numpy": get_installed_version("numpy"),
            "scipy": get_installed_version("scipy"),
            "trimesh": get_installed_version("trimesh"),
            "Pillow": get_installed_version("Pillow"),
            "pymeshlab": get_installed_version("pymeshlab"),
        },
        "pymeshlab": pymeshlab_environment_report(),
    }
    return report


def print_environment_diagnostics():
    report = environment_diagnostics()
    print(f"PotteryVolumeCalculator {__version__}")
    print(f"Python       : {sys.version.split()[0]}")
    print(f"Platform     : {report['platform']}")
    for k, v in report["packages"].items():
        print(f"{k:12s}: {v or 'not installed'}")

    pml = report["pymeshlab"]
    print("\nPyMeshLab")
    print(f"  import available : {pml['available']}")
    print(f"  plugins loaded   : {pml.get('plugins_loaded')}")
    print(f"  filter_list API  : {pml.get('filter_list_api_available')}")
    for name, available in pml.get("required_filters", {}).items():
        print(f"  {name}: {available}")

    if not pml["available"]:
        print(
            "\nNOTE: PyMeshLabは利用できませんが、"
            "v1.2では容量計算の必須依存ではありません。"
        )
    elif not all(pml.get("required_filters", {}).values()):
        print(
            "\nNOTE: PyMeshLabの必要フィルタがロードされていません。"
            "本体はNumPy/Trimesh基準QAで継続できます。"
        )

    return report


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
    boundary_sample_mm: float,
    require_pymeshlab: bool = False,
):
    started = time.perf_counter()

    if unit not in UNIT_SCALE_TO_MM:
        raise ValueError("unit は mm / cm / m のいずれかを指定してください。")
    if pitch <= 0:
        raise ValueError("pitch は正数にしてください。")
    if boundary_sample_mm <= 0:
        raise ValueError("boundary-sample-mm は正数にしてください。")

    scale_to_mm = UNIT_SCALE_TO_MM[unit]
    layout = make_output_layout(input_path, pitch, output_dir)

    print(f"=== PotteryVolumeCalculator v{__version__} ===")
    print(f"output dir : {layout['base']}")

    # ---- Stage A: deterministic preprocessing + optional PyMeshLab ----
    print("\n=== Stage A: deterministic QA / exact-coordinate weld ===")
    print("file I/O       : Trimesh (process=False)")
    print("reference QA   : NumPy + Trimesh")
    print("calculation mesh: exact-coordinate weld only")
    tp = time.perf_counter()
    vertices_native, faces, pml_report, archaeological = stage_a_preprocess(
        input_path,
        processed_dir=layout["processed"],
        qa_dir=layout["qa"],
        archaeological_dir=layout["archaeological"],
        unit=unit,
        boundary_sample_mm=boundary_sample_mm,
        require_pymeshlab=require_pymeshlab,
    )
    pml_time = time.perf_counter() - tp

    before = pml_report["before"]["summary"]
    after = pml_report["after"]["summary"]

    print(f"vertices before : {pml_report['before']['counts']['vertices']:,}")
    print(f"vertices after  : {pml_report['after']['counts']['vertices']:,}")
    print(f"exact dup/unref removed: {pml_report['vertices_removed']:,}")
    print(f"boundary edges before: {before.get('boundary_edges', 'n/a')}")
    print(f"boundary edges after : {after.get('boundary_edges', 'n/a')}")
    print(f"components after     : {after.get('connected_components_number', 'n/a')}")
    print(f"2-manifold after     : {after.get('is_mesh_two_manifold', 'n/a')}")
    print(f"closed 2-manifold    : {after.get('is_closed_two_manifold', 'n/a')}")
    print(f"non-2-manifold edges : {after.get('non_two_manifold_edges', 'n/a')}")
    print(f"geometry preserved   : {pml_report['cleanup']['geometry_preserved_exact']}")
    print(f"time                  : {pml_time:.2f} s")
    print(f"processed mesh        : {pml_report['processed_mesh']}")

    pml_cross = pml_report["pymeshlab_crosscheck"]
    pml_env = pml_cross["environment"]
    print("\n=== Stage A2: PyMeshLab independent cross-check ===")
    print(f"PyMeshLab version : {pml_env.get('version') or 'not installed'}")
    print(f"plugins loaded    : {pml_env.get('plugins_loaded')}")
    print(f"cross-check status: {pml_cross.get('status')}")
    print("used for calculation mesh: False")
    print(
        f"raw boundary edges    : "
        f"{archaeological['raw_boundary_stats']['boundary_edges']:,}"
    )
    print(
        f"after duplicate edges : "
        f"{archaeological['cleaned_boundary_stats']['boundary_edges']:,}"
    )
    print(
        f"raw components        : "
        f"{archaeological['raw_boundary_stats']['component_count']:,}"
    )
    print(f"archaeological output : {layout['archaeological']}")

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
            "preprocessing_qa": pml_report,
            "archaeological_boundary_derivatives": {
                "raw": archaeological["raw_boundary_stats"],
                "after_duplicate_removal": archaeological["cleaned_boundary_stats"],
                "comparison": archaeological["boundary_comparison"],
            },
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

        # Quantify and visualize relation between spill path and raw fragment boundaries.
        slab_free_indices = np.argwhere(slab_free)
        spill_free_native = (
            padded_indices_to_points_mm(vox, slab_free_indices, pad) / scale_to_mm
            if len(slab_free_indices) else np.empty((0, 3), dtype=np.float64)
        )
        raw_boundary_samples = archaeological["raw_boundary_samples_native"]
        proximity = boundary_spill_proximity(
            raw_boundary_samples, spill_free_native, unit, pitch
        )
        proximity_path = layout["run_qa"] / "spill_boundary_proximity.json"
        write_json(proximity_path, proximity)
        qc_files["spill_boundary_proximity_json"] = str(proximity_path)

        overlap_path = layout["qc"] / "spill_vs_raw_fragment_boundaries.ply"
        overlap_count = export_colored_overlap(
            raw_boundary_samples, spill_free_native, overlap_path
        )
        if overlap_count:
            qc_files["spill_vs_raw_fragment_boundaries_ply"] = str(overlap_path)
            print(f"spill vs seams : {overlap_path} ({overlap_count:,} points)")
        if proximity.get("available"):
            print(
                "spill near raw boundary: "
                f"<=0.5 pitch {proximity['fraction_within_half_pitch']:.3f}, "
                f"<=1 pitch {proximity['fraction_within_one_pitch']:.3f}"
            )

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
        "preprocessing_qa": pml_report,
        "archaeological_boundary_derivatives": {
            "raw": archaeological["raw_boundary_stats"],
            "after_duplicate_removal": archaeological["cleaned_boundary_stats"],
            "comparison": archaeological["boundary_comparison"],
        },
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
            "preprocessing": pml_time,
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
            "deterministic QA + optional PyMeshLab cross-check + voxel spill-level法により、"
            "土器が液体を保持できる最大内容積を推定"
        )
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--diagnose-env",
        action="store_true",
        help="Python/PyMeshLabの実行環境とロード済みプラグインを診断して終了",
    )
    parser.add_argument(
        "--require-pymeshlab",
        action="store_true",
        help=(
            "PyMeshLab cross-checkが完全成功しない場合にエラー終了する。"
            "通常は指定不要"
        ),
    )
    parser.add_argument("input", type=Path, nargs="?", help="入力 OBJ または PLY")
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
        "--boundary-sample-mm",
        type=float,
        default=0.5,
        help=(
            "raw/cleaned boundaryを線として保存する際のサンプリング間隔 [mm]。"
            "既定値 0.5。容量計算には影響しない"
        ),
    )
    parser.add_argument(
        "--debug-voxels",
        action="store_true",
        help="surface voxel全体とspill付近スラブを常に出力",
    )

    args = parser.parse_args()

    if args.diagnose_env:
        print_environment_diagnostics()
        return

    if args.input is None:
        parser.error("input OBJ/PLY が必要です（--diagnose-env の場合を除く）")

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
            boundary_sample_mm=args.boundary_sample_mm,
            require_pymeshlab=args.require_pymeshlab,
        )
    except ModuleNotFoundError as exc:
        dependency_error(exc)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
