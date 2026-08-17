# PotteryRadialSections v0.3.0

土器3Dメッシュ（PLY / OBJ）から、**水平断面の楕円中心を用いて回転軸のXY位置を推定し、その軸を通る縦断面を一定角度間隔で抽出する**Python CLIプログラムです。

現段階では回転体復元・容量計算は行いません。処理は、

1. 回転軸推定
2. 30°間隔などの縦断面抽出
3. QA / 可視化出力

までです。

---

## 1. 前提となる3Dモデル

- 完形またはほぼ完形の土器
- Z軸が土器の上下方向
- PLYまたはOBJ
- 入力座標単位は `mm` / `cm` / `m`
- 内面が取得されている資料では `inner` モードを推奨

PLYはtexture UVによる頂点再分割を避けるため、`fix_texture=False`で元のgeometry topologyを保持して読み込みます。

---

## 2. 回転軸推定アルゴリズム

### 2.1 水平断面の位置

既定では器高を**20等分**し、各区間の中央でXY水平断面を取得します。

したがって断面位置は相対器高で、

```text
2.5%, 7.5%, 12.5%, ... , 97.5%
```

となります。

最小Z・最大Zそのものを使わず区間中央を使うことで、底面や口縁への接線となる不安定な断面を避けます。

既定：

```bash
--z-sections 20
```

絶対間隔を使いたい場合は、例えば20 mm間隔として、

```bash
--z-step-mm 20
```

を指定できます。`--z-sections`と`--z-step-mm`は同時指定できません。

### 2.2 横断面輪郭

各Z位置でmeshとXY平面の交線を取得し、線分を閉曲線へ接続します。

閉曲線は面積の大きい順に整理し、

- 最大面積の閉曲線：`outer contour`
- outer内部にあり、outer面積の5%以上を持つ次の閉曲線：`inner contour`

として扱います。

口縁直近などでinner contourが独立した閉曲線として得られない場合、その断面は`inner`軸推定から自動的に除外されます。

### 2.3 等間隔再サンプリング

メッシュの三角形密度が楕円fitの重みにならないよう、輪郭線を弧長方向に等間隔で再サンプリングします。

既定：

```bash
--contour-spacing-mm 0.5
```

### 2.4 robust ellipse fitting

各輪郭に楕円をfitし、次を取得します。

- 楕円中心 X, Y
- 長半径、短半径
- 楕円長軸方向
- eccentricity
- fit RMSE
- relative RMSE
- fitに残った点の割合

fitにはrobust lossを使用し、局所的に大きな残差を持つ点を再fit時に除外します。

特に`outer`モードでは、外面装飾などの局所突出の影響を抑えて**基礎的な仮想楕円外形**を推定することを意図しています。ただし、強い装飾を持つ縄文土器等については今後追加検証が必要です。

---

## 3. axis surface mode

### `inner` — 既定・推奨

```bash
--axis-surface inner
```

各水平断面の**inner ellipse center**を回転軸算出に使用します。

容量復元では最終的に内面形状が必要になるため、内面が十分取得されている完形土器ではこのモードを推奨します。

### `outer`

```bash
--axis-surface outer
```

outer contourからrobust ellipseを作り、その中心を使用します。

外面に装飾がある場合でも局所凹凸の影響を抑えたellipse fitを行います。

> **器厚について**  
> `outer`モードの回転軸推定では器厚情報を使用しません。後続の内面プロファイル復元・容量計算段階では、単一器厚値またはZ位置を伴う複数の器厚実測値を入力し、外面から内面を推定できる設計を予定しています。

### `both`

```bash
--axis-surface both
```

inner / outerの両方をfitしてQC値を保存しますが、**最終回転軸はinner centerから算出**します。

inner / outer ellipse center間距離もCSVに保存します。

---

## 4. 断面中心の外れ値除外と最終回転軸

各有効断面の選択surface中心を、

```text
Ci = (Xi, Yi)
```

とします。

まず全中心のXY中央値を求め、その中央値から各中心までの2D距離を計算します。その距離分布に対しMADを用い、既定では、

```text
median(distance) + 3 × 1.4826 × MAD(distance)
```

を超える中心を外れ値として除外します。

設定：

```bash
--center-outlier-mad 3.0
```

残った中心の**算術平均**を、最終的なZ平行回転軸のXY位置とします。

```text
Xaxis = mean(Xi)
Yaxis = mean(Yi)
rotation axis = (Xaxis, Yaxis, Z)
```

各断面について、

```text
Δx = Xi - Xaxis
Δy = Yi - Yaxis
Δr = sqrt(Δx² + Δy²)
```

を保存します。

---

## 5. 軸の傾き診断

v0.3.0では回転軸自体はZ平行とします。

ただし水平断面中心がZに沿って系統的に移動しているかを、

```text
Xcenter(Z)
Ycenter(Z)
```

の線形回帰から診断します。

出力：

- `axis_drift_x_mm_per_100mm`
- `axis_drift_y_mm_per_100mm`
- `estimated_centerline_tilt_deg`

これは**QA用の診断値のみ**です。v0.3.0ではモデルの自動回転・傾き補正は行いません。

---

## 6. 縦断面

推定された最終回転軸を通る縦断面を取得します。

30°間隔なら、全断面平面は、

```text
0° / 180°
30° / 210°
60° / 240°
90° / 270°
120° / 300°
150° / 330°
```

の6平面です。

同時に、

```text
0°, 30°, 60°, ... , 330°
```

の12方向の放射半断面も出力します。

各断面はCSV、edge PLY、point-cloud PLYとして保存されます。PLYは**入力メッシュと同じXYZ座標系・単位**なので、CloudCompare等で元モデル上に直接重ねられます。

---

## 7. 実行方法

### 必要モジュール

```bash
python3 -m pip install -r requirements.txt
```

または、

```bash
python3 -m pip install numpy scipy trimesh matplotlib
```

### 基本実行

入力PLYの座標単位がmの場合：

```bash
python3 pottery_radial_sections.py 0015Jinmen_small.ply --unit m
```

これは、

- `inner` mode
- 20等分
- 30°縦断面
- contour resampling 0.5 mm

で実行します。

### outer mode

```bash
python3 pottery_radial_sections.py 0015Jinmen_small.ply \
  --unit m \
  --axis-surface outer
```

### 10等分

```bash
python3 pottery_radial_sections.py 0015Jinmen_small.ply \
  --unit m \
  --z-sections 10
```

### 20 mm絶対間隔

```bash
python3 pottery_radial_sections.py 0015Jinmen_small.ply \
  --unit m \
  --z-step-mm 20
```

### Windows PowerShell

仮想環境を有効化した後なら、

```powershell
python pottery_radial_sections.py 0015Jinmen_small.ply --unit m
```

で実行できます。

---

## 8. 出力構成

```text
<model>_RadialSections_30deg/
├── metadata.json
├── sections_summary.csv
├── axis_estimation/
│   ├── horizontal_sections.csv
│   ├── axis_summary.csv
│   ├── all_horizontal_section_points.ply
│   ├── all_fitted_ellipse_points.ply
│   ├── section_centers_points.ply
│   ├── rotation_axis_edges.ply
│   └── horizontal_sections/
│       ├── horizontal_001_..._intersection_points.ply
│       ├── horizontal_001_..._fitted_ellipse_points.ply
│       └── ...
├── full_sections/
│   ├── section_000_180.csv
│   ├── section_000_180_edges.ply
│   ├── section_000_180_points.ply
│   └── ...
├── radial_half_sections/
│   ├── ray_000.csv
│   ├── ray_000_edges.ply
│   ├── ray_000_points.ply
│   └── ...
└── visualization/
    ├── axis_validation_xz.png
    ├── axis_validation_yz.png
    ├── axis_centers_xy.png
    ├── horizontal_sections_oblique.png
    ├── horizontal_sections_table.png
    ├── axis_summary_table.png
    ├── full_sections_oblique.png
    └── radial_half_sections_oblique.png
```

---

## 9. `horizontal_sections.csv`

各水平断面について主に次を保存します。

- section ID
- Z座標、底部からの高さ、相対器高
- closed contour数
- outer / inner面積
- outer / inner ellipse center
- 長半径 / 短半径
- ellipse angle / eccentricity
- fit RMSE / relative RMSE
- outer-inner center distance
- 選択したaxis surface
- 最終軸に対する `Δx`, `Δy`, `Δr`
- center outlier判定
- 最終軸計算への採否
- 除外理由

---

## 10. `axis_summary.csv`

全体統計として、

- attempted / valid / used sections
- 最終axis X / Y
- X / YのSD、MAD
- Δrのmean / median / RMS / P95 / max
- center outlier threshold
- X/Y center drift per 100 mm
- diagnostic centerline tilt
- inner / outer center offset
- ellipse fit RMSE

等を保存します。

---

## 11. 検証画像

### `axis_validation_xz.png`

0°縦断面上に、各水平断面のellipse centerのX位置と、最終回転軸を重ねます。

### `axis_validation_yz.png`

同様にY方向を確認します。

### `axis_centers_xy.png`

XY平面上で各水平断面中心の分布、外れ値、最終平均中心を確認します。

### `horizontal_sections_oblique.png`

各水平断面を元3Dメッシュ上に重ね、斜め俯瞰で測定位置を確認します。

---

## 12. PLYによる3D監査

次のPLYはすべて入力と同じ座標系・単位です。

- `all_horizontal_section_points.ply`
- `all_fitted_ellipse_points.ply`
- `section_centers_points.ply`
- `rotation_axis_edges.ply`
- 全縦断面 `*_points.ply` / `*_edges.ply`

元モデルと同時にCloudCompare等へ読み込むことで、断面位置、ellipse fit、中心点、最終回転軸を3D上で確認できます。

---

## 13. 0015Jinmen_small.plyでの検証

既定設定：

```bash
python3 pottery_radial_sections.py 0015Jinmen_small.ply --unit m
```

結果：

```text
horizontal sections attempted : 20
valid inner ellipse centers    : 19
used for final axis            : 19
final axis X                   : 138.092372 mm
final axis Y                   : -107.491406 mm
RMS radial center offset       : 2.3259 mm
diagnostic centerline tilt     : 1.2695 deg
```

最上部の1断面では独立したinner closed contourを取得できなかったため、自動的に軸計算から除外されました。

この資料では中心位置にZ方向の系統的変化が見られ、診断上は約1.27°のcenterline tiltとなります。これはモデル姿勢、器形自体の非対称性、製作変形等を含み得るため、v0.3.0では補正せずQA値として記録します。

---

## 14. 現段階での制約

- 回転軸はZ平行。傾き補正はまだ行わない
- outerの装飾除去性能は強装飾土器で未検証
- 水平断面のinner / outer分類は単純な閉曲線面積・包含関係に基づく
- 把手・注口・複雑な突起がある器形では追加の輪郭分類が必要になる可能性がある
- 回転体復元・容量計算は未実装

次段階では、30°放射半断面から内面曲線を抽出し、中心軸からの放射座標 `r(z)` を用いた回転体復元へ進みます。
