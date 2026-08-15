#!/usr/bin/env python3
"""
vessel_voxel_volume.py

OBJ/PLY の土器メッシュから、内面を明示的に抽出せずに内容積を推定する
実験用 voxel アルゴリズム。

対象:
- 単純な単口縁
- 口縁に突起・把手・注口なし
- 内面は滑らか
- 大きな欠損なし
- 土器は Z 軸方向に直立
- 入力座標単位は mm / cm / m に対応（内部では mm に変換）

処理:
1. メッシュ全体を surface voxelize
2. 上方から水平断面を走査し、器中心を含む閉じた空隙を口部として検出
3. その空隙を仮想 cap で閉じる
4. cap 直下を seed として 3D flood fill
5. 外部に漏れなければ、その連結空隙を内容積とする
6. QC 用に cavity surface と cap を PLY で保存

注意:
surface voxel は厚さを持つため、内容積は一般にやや過小評価されます。
0.5 / 1.0 / 2.0 mm など複数 pitch で収束を確認してください。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import trimesh
from scipy import ndimage


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


def padded_world_to_index(
    vox: trimesh.voxel.VoxelGrid,
    point_xyz: np.ndarray,
    pad: int,
) -> np.ndarray:
    """world 座標を padding 後 voxel index に変換。"""
    idx = np.asarray(vox.points_to_indices(np.asarray(point_xyz).reshape(1, 3))[0],
                     dtype=int)
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
    XY 断面で器中心を含む閉じた空隙を探す。

    戻り値:
      opening_mask : 中央空隙
      sealed_ring  : 口縁検出用に軽く closing した壁
      area_voxels  : opening のセル数
    """
    if close_iterations > 0:
        sealed_ring = ndimage.binary_closing(
            surface_slice,
            structure=np.ones((3, 3), dtype=bool),
            iterations=close_iterations,
        )
    else:
        sealed_ring = surface_slice.copy()

    # 2D 外周から到達できない空隙を hole とする
    filled = ndimage.binary_fill_holes(
        sealed_ring,
        structure=ndimage.generate_binary_structure(2, 1),
    )
    holes = filled & ~sealed_ring

    labels, _ = ndimage.label(
        holes,
        structure=ndimage.generate_binary_structure(2, 1),
    )

    cx, cy = center_xy
    if not (0 <= cx < labels.shape[0] and 0 <= cy < labels.shape[1]):
        return None

    label_id = int(labels[cx, cy])
    if label_id == 0:
        return None

    opening = labels == label_id
    area = int(np.count_nonzero(opening))

    if area < min_area_voxels:
        return None

    return opening, sealed_ring, area


def detect_cap_slice(
    surface: np.ndarray,
    center_xy: tuple[int, int],
    min_area_voxels: int,
    persistence: int = 3,
    close_iterations: int = 1,
):
    """
    上から下へ走査し、中央空隙が persistence 枚連続して存在する
    最上位の slice を cap 高さとして採用。
    """
    nz = surface.shape[2]

    for k in range(nz - 1, persistence - 2, -1):
        candidates = []

        for offset in range(persistence):
            kk = k - offset
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
            opening, sealed_ring, area = candidates[0]
            return k, opening, sealed_ring, area

    raise RuntimeError(
        "口部を自動検出できませんでした。"
        "土器がZ軸に直立しているか、メッシュに欠損がないか確認してください。"
        "必要なら --cap-z で口縁高さを手動指定してください。"
    )


def choose_seed(
    free: np.ndarray,
    cap_mask: np.ndarray,
    k_cap: int,
    search_depth: int = 30,
    search_radius: int = 5,
):
    """cap 中央直下から、内部 flood fill 用の free voxel を探す。"""
    xy = np.argwhere(cap_mask)
    if len(xy) == 0:
        raise RuntimeError("cap mask が空です。")

    center = np.rint(xy.mean(axis=0)).astype(int)
    cx, cy = int(center[0]), int(center[1])

    for dz in range(1, search_depth + 1):
        z = k_cap - dz
        if z < 0:
            break

        for r in range(search_radius + 1):
            x0, x1 = max(0, cx - r), min(free.shape[0], cx + r + 1)
            y0, y1 = max(0, cy - r), min(free.shape[1], cy + r + 1)

            coords = np.argwhere(free[x0:x1, y0:y1, z])
            if len(coords):
                x = int(coords[0, 0] + x0)
                y = int(coords[0, 1] + y0)
                return x, y, z

    raise RuntimeError("cap直下に内部 seed voxel を見つけられませんでした。")


def touches_boundary(mask: np.ndarray) -> bool:
    """連結領域が計算領域外周に接しているか。"""
    return bool(
        mask[0, :, :].any()
        or mask[-1, :, :].any()
        or mask[:, 0, :].any()
        or mask[:, -1, :].any()
        or mask[:, :, 0].any()
        or mask[:, :, -1].any()
    )


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
        return

    points = padded_indices_to_points(vox, indices, pad=pad)
    trimesh.points.PointCloud(points).export(str(path))


def estimate_volume(
    input_path: Path,
    pitch: float = 1.0,
    unit: str = "mm",
    pad: int = 4,
    min_opening_area_mm2: float = 100.0,
    persistence: int = 3,
    close_iterations: int = 1,
    cap_z: float | None = None,
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

    bounds = mesh.bounds
    extents = mesh.extents
    center_world = bounds.mean(axis=0)

    print("=== Input mesh ===")
    print(f"file       : {input_path}")
    print(f"input unit : {unit}")
    print(f"scale      : x{scale:g} -> mm")
    print(f"vertices   : {len(mesh.vertices):,}")
    print(f"faces      : {len(mesh.faces):,}")
    print(f"watertight : {mesh.is_watertight}")
    print(
        "extents mm : "
        f"X={extents[0]:.3f}, Y={extents[1]:.3f}, Z={extents[2]:.3f}"
    )

    if pitch <= 0:
        raise ValueError("pitch は正数にしてください。")

    print("\n=== Surface voxelization ===")
    print(f"pitch      : {pitch:.3f} mm")

    tv = time.perf_counter()

    # surface voxelization:
    # 内部を fill しないことが重要。
    # method='subdivide' は surface の6-connectivityを得やすいが、
    # 巨大で細長い triangle がある場合は重くなることがある。
    vox = mesh.voxelized(
        pitch=pitch,
        method="subdivide",
    )

    print(f"time       : {time.perf_counter() - tv:.2f} s")
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
        int(math.ceil(min_opening_area_mm2 / (pitch * pitch))),
    )

    print("\n=== Rim / cap ===")

    if cap_z is None:
        k_cap, cap_mask, sealed_ring, cap_area = detect_cap_slice(
            surface=surface,
            center_xy=center_xy,
            min_area_voxels=min_area_voxels,
            persistence=persistence,
            close_iterations=close_iterations,
        )
    else:
        manual_world = np.array(
            [center_world[0], center_world[1], float(cap_z)],
            dtype=float,
        )
        manual_idx = padded_world_to_index(vox, manual_world, pad=pad)
        k_cap = int(manual_idx[2])

        if not (0 <= k_cap < surface.shape[2]):
            raise ValueError("--cap-z が voxel grid の範囲外です。")

        result = central_opening_at_slice(
            surface[:, :, k_cap],
            center_xy=center_xy,
            min_area_voxels=min_area_voxels,
            close_iterations=close_iterations,
        )
        if result is None:
            raise RuntimeError(
                f"指定した cap-z={cap_z} mm の断面で中央空隙を検出できません。"
            )

        cap_mask, sealed_ring, cap_area = result

    # padded index -> original voxel index -> world coordinate
    world_at_cap = vox.indices_to_points(
        np.array([[0, 0, k_cap - pad]], dtype=int)
    )[0]
    cap_z_world = float(world_at_cap[2])

    print(f"cap index  : {k_cap}")
    print(f"cap Z      : {cap_z_world:.3f} mm")
    print(
        f"opening    : {cap_area:,} voxels "
        f"(~{cap_area * pitch * pitch:.1f} mm^2)"
    )

    # 仮想capを作る。
    # 同じsliceでclosingされたringも加え、小さな1-cell gapからの漏れを抑える。
    barrier = surface.copy()
    barrier[:, :, k_cap] |= cap_mask
    barrier[:, :, k_cap] |= sealed_ring

    free = ~barrier

    seed_xyz = choose_seed(
        free=free,
        cap_mask=cap_mask,
        k_cap=k_cap,
    )
    print(f"seed index : {seed_xyz}")

    print("\n=== 3D cavity flood fill ===")
    seed = np.zeros_like(free, dtype=bool)
    seed[seed_xyz] = True

    tf = time.perf_counter()
    cavity = ndimage.binary_propagation(
        seed,
        structure=ndimage.generate_binary_structure(3, 1),  # 6-connectivity
        mask=free,
    )
    flood_time = time.perf_counter() - tf
    print(f"time       : {flood_time:.2f} s")

    if touches_boundary(cavity):
        raise RuntimeError(
            "\n内部領域が grid 外周まで漏れました。\n"
            "原因候補:\n"
            "- メッシュに穴・欠損がある\n"
            "- voxel pitch が粗すぎて表面 barrier が途切れた\n"
            "- cap が口縁を完全に閉じていない\n"
            "- 土器がZ軸に正しく直立していない\n"
            "まず CloudCompare 等でメッシュを確認するか、pitch を小さくしてください。"
        )

    cavity_voxels = int(np.count_nonzero(cavity))
    volume_mm3 = cavity_voxels * (pitch ** 3)
    volume_ml = volume_mm3 / 1000.0
    volume_l = volume_ml / 1000.0

    print("\n=== Result ===")
    print(f"cavity voxels : {cavity_voxels:,}")
    print(f"volume        : {volume_mm3:,.1f} mm^3")
    print(f"volume        : {volume_ml:,.3f} mL")
    print(f"volume        : {volume_l:,.6f} L")

    if output_prefix is None:
        output_prefix = input_path.with_name(
            f"{input_path.stem}_voxel_{pitch:g}mm"
        )

    output_prefix = Path(output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    qc_files = {}

    if export_qc:
        cavity_path = Path(f"{output_prefix}_cavity_surface.ply")
        cap_path = Path(f"{output_prefix}_cap.ply")

        print("\n=== Export QC ===")
        export_qc_pointcloud(
            vox=vox,
            mask=cavity,
            pad=pad,
            path=cavity_path,
            surface_only=True,
        )

        cap3d = np.zeros_like(cavity, dtype=bool)
        cap3d[:, :, k_cap] = cap_mask

        export_qc_pointcloud(
            vox=vox,
            mask=cap3d,
            pad=pad,
            path=cap_path,
            surface_only=False,
        )

        qc_files["cavity_surface_ply"] = str(cavity_path)
        qc_files["cap_ply"] = str(cap_path)

        print(f"cavity QC  : {cavity_path}")
        print(f"cap QC     : {cap_path}")

    total_time = time.perf_counter() - t0

    summary = {
        "input": str(input_path),
        "input_unit": unit,
        "scale_to_mm": float(scale),
        "pitch_mm": pitch,
        "mesh_vertices": int(len(mesh.vertices)),
        "mesh_faces": int(len(mesh.faces)),
        "mesh_watertight": bool(mesh.is_watertight),
        "mesh_extents_mm": [float(v) for v in extents],
        "cap_z_mm": cap_z_world,
        "cap_opening_voxels": cap_area,
        "cap_opening_area_mm2": float(cap_area * pitch * pitch),
        "cavity_voxels": cavity_voxels,
        "volume_mm3": float(volume_mm3),
        "volume_ml": float(volume_ml),
        "volume_l": float(volume_l),
        "total_time_s": float(total_time),
        "qc_files": qc_files,
    }

    json_path = Path(f"{output_prefix}_result.json")
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"result JSON: {json_path}")
    print(f"total time : {total_time:.2f} s")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="OBJ/PLY 土器メッシュから voxel 法で内容積を推定"
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
        "--min-opening-area",
        type=float,
        default=100.0,
        help="口部候補の最小面積 [mm^2]。既定値 100",
    )
    parser.add_argument(
        "--persist",
        type=int,
        default=3,
        help="口部と認定するため連続して検出するslice数。既定値 3",
    )
    parser.add_argument(
        "--close-iters",
        type=int,
        default=1,
        help="口縁断面の1-cell gapを閉じる2D closing回数。既定値 1",
    )
    parser.add_argument(
        "--cap-z",
        type=float,
        default=None,
        help="cap の Z 座標 [mm] を手動指定。入力単位に関係なく mm で指定。省略時は自動検出",
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
            min_opening_area_mm2=args.min_opening_area,
            persistence=args.persist,
            close_iterations=args.close_iters,
            cap_z=args.cap_z,
            output_prefix=args.output_prefix,
            export_qc=not args.no_qc,
        )
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
