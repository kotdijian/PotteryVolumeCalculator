# PotteryRadialSections v0.2.0

土器3Dメッシュから、Z軸に平行な中心軸を通る縦断面を一定角度間隔で取得する前処理プログラムです。

## v0.2.0で追加した点

- 各縦断面を **入力メッシュと同じXYZ座標系・同じ単位のPLY点群**として保存します。
- CloudCompare等で元メッシュとそのまま重ねて、測定位置と断面を確認できます。
- CSVには入力座標 `x_input, y_input, z_input` と、mm換算座標 `x_mm, y_mm, z_mm` の両方を保存します。
- 6枚の全縦断面をまとめた色分け点群 `all_full_section_points.ply` を保存します。
- 12方向の放射半断面をまとめた色分け点群 `all_radial_half_section_points.ply` を保存します。
- 元メッシュ上に断面を重ねた斜め俯瞰の参考画像を自動生成します。

## 現在の段階

この版は **縦断面抽出専用**です。以下はまだ実装していません。

- 水平断面の楕円中心による回転軸推定
- inner / outer / both モード
- 内面曲線の抽出
- 回転体復元
- 容量計算

中心軸は暫定的にXY bounding box中心を既定値としています。次版で、水平断面を連続的に取得して楕円中心の外れ値除外平均から回転軸を推定する方式へ変更する予定です。

## 30度間隔の場合

全断面平面は対向方向が同一平面になるため6枚です。

```text
0° / 180°
30° / 210°
60° / 240°
90° / 270°
120° / 300°
150° / 330°
```

放射半断面は12方向です。

```text
0, 30, 60, 90, 120, 150,
180, 210, 240, 270, 300, 330°
```

## 実行例

入力PLYの座標単位がmの場合：

```bash
python3 pottery_radial_sections.py 0015Jinmen_small.ply --unit m
```

30度間隔を明示する場合：

```bash
python3 pottery_radial_sections.py 0015Jinmen_small.ply --unit m --angle-step 30
```

画像出力が不要な場合：

```bash
python3 pottery_radial_sections.py 0015Jinmen_small.ply --unit m --no-visualization
```

## 出力

```text
0015Jinmen_small_RadialSections_30deg/
├── metadata.json
├── sections_summary.csv
├── full_sections/
│   ├── section_000_180.csv
│   ├── section_000_180_edges.ply
│   ├── section_000_180_points.ply
│   ├── ...
│   └── all_full_section_points.ply
├── radial_half_sections/
│   ├── ray_000.csv
│   ├── ray_000_edges.ply
│   ├── ray_000_points.ply
│   ├── ...
│   └── all_radial_half_section_points.ply
└── visualization/
    ├── full_sections_oblique.png
    └── radial_half_sections_oblique.png
```

### PLY座標

`*_points.ply`、`*_edges.ply`、結合点群PLYはすべて **入力メッシュと同じXYZ座標・同じ単位**です。入力PLYがmなら出力PLYもmです。このため元メッシュと直接重ねられます。

### CSV座標

CSVには以下を併記します。

- `x_input, y_input, z_input`: 入力モデルと同じ座標・単位
- `x_mm, y_mm, z_mm`: mm換算
- `signed_r_mm`: 断面平面内の符号付き放射座標
- `radial_r_mm`: 中心軸からの放射距離
- `z_from_bottom_mm`: モデル最下部からの高さ

## 依存モジュール

```bash
python3 -m pip install numpy trimesh matplotlib
```

PLYのtexture UVによる頂点再分割を避けるため、PLYは`fix_texture=False`で幾何topologyを保持して読み込みます。
