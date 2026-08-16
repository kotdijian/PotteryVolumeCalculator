# PotteryVolumeCalculator v1.2.0

PLY / OBJ 形式の土器3Dメッシュから、**液体が最初に外へ溢れ出す直前までの最大内容量**を voxel 法で推定する実験用ツールです。

v1.2では、PyMeshLabのプラグインが環境によってロードされない場合でも容量計算を停止しないよう、前処理とQAの基準を **NumPy + Trimesh** に変更しました。PyMeshLabは独立したcross-checkとして残しています。

---

## 1. v1.2の重要な変更

v1.1までの実装では、PyMeshLabのフィルタが使えることを前提としていたため、環境によって次のエラーが起きました。

```text
Unknown format for load: ply
Filter does not exists: get_topological_measures
```

v1.2では、

```text
PLY / OBJ
  ↓
Trimeshで読込（process=False）
  ↓
raw fragment boundary候補を保存
  ↓
NumPyで完全同一座標の頂点だけをweld
  ↓
NumPy + Trimeshで基準トポロジーQA
  │
  ├── PyMeshLabが正常なら独立cross-check
  │     ※計算メッシュには使用しない
  ↓
surface voxelization
  ↓
spill-level探索
  ↓
最大保持液量
```

としました。

**PyMeshLabのプラグインが欠けていても、通常の容量計算は継続します。**

---

## 2. 容量の定義

容量は、

> 土器を+Z方向に直立させた状態で、液体が最初に外部へ流出する直前まで保持できる最大内容量

と定義します。

水平capは使用しません。非水平口縁でも、内部空間が外部へ最初につながるspill levelを3D flood fillで探索します。

---

## 3. 自動前処理

容量計算用コピーに対して自動実行するのは次だけです。

1. faceから参照されていない頂点を除去
2. XYZ座標が**完全に同一**の頂点だけを統合

重要な条件：

```text
coordinate tolerance : 0
vertex movement      : なし
face追加・削除        : なし
```

処理前後で、参照頂点がまったく同じXYZへ対応していることをコード内部で確認します。

```text
geometry preserved : True
```

でなければ計算を停止します。

### 自動実行しない処理

以下は形状・トポロジーを変更し得るため行いません。

- Close Holes
- Merge Close Vertices
- Snap Mismatched Borders
- Repair non-manifold edges
- Repair non-manifold vertices

---

## 4. 破片境界候補を別データとして保存

raw meshのboundary edgeは、容量計算用QAとは別に、復元土器から実際の破片位置・サイズを再抽出するための派生データとして保存します。

```text
<model>_PotteryVolume_v1/
└── archaeological/
    ├── raw_boundary_vertices.ply
    ├── raw_boundaries_sampled.ply
    ├── raw_boundary_stats.json
    ├── raw_components.csv
    ├── raw_components.json
    ├── raw_components_colored.ply
    ├── after_exact_weld_boundary_vertices.ply
    ├── after_exact_weld_boundaries_sampled.ply
    ├── after_exact_weld_components.csv
    └── boundary_before_after_comparison.json
```

`raw_*`はcleaning前なので、元モデルに含まれる接合線情報を保持します。

connected componentは「破片候補」であり、自動的に考古学的な実破片と断定するものではありません。

---

## 5. PyMeshLabの位置づけ

PyMeshLabは**独立cross-check**です。

プログラムは起動時に、対象フィルタが本当にロードされているかを確認します。

対象：

```text
get_topological_measures
meshing_remove_duplicate_vertices
meshing_remove_unreferenced_vertices
```

`apply_filter()`メソッドが存在するだけでは利用可能とは判定しません。

ロード済みフィルタ一覧または実在する生成メソッドで確認できた場合だけ呼び出します。

PyMeshLabが利用不能なら、

```text
cross-check status: plugins_or_required_filters_unavailable
used for calculation mesh: False
```

などと記録し、計算を続けます。

PyMeshLabを必須条件として実行したい場合だけ、

```bash
--require-pymeshlab
```

を指定します。

---

## 6. インストール

### 推奨：PyMeshLabを含む全部入り

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

`requirements.txt`では再現性のため、

```text
pymeshlab==2025.7.post1
```

に固定しています。

### PyMeshLabなしで容量計算だけ行う

```bash
python3 -m pip install -r requirements-core.txt
```

でも動作します。

この場合も、

- exact-coordinate weld
- トポロジーQA
- 破片境界保存
- voxelization
- spill判定
- 容量計算

は実行されます。

### `No module named 'PIL'`

インストール名は `PIL` ではなく、

```bash
python3 -m pip install Pillow
```

です。

---

## 7. まず環境診断

```bash
python3 vessel_voxel_volume.py --diagnose-env
```

を実行してください。

例：

```text
PotteryVolumeCalculator 1.2.0
Python       : 3.13.x
numpy        : ...
trimesh      : ...
pymeshlab    : ...

PyMeshLab
  import available : True
  plugins loaded   : ...
  get_topological_measures: True/False
  meshing_remove_duplicate_vertices: True/False
  meshing_remove_unreferenced_vertices: True/False
```

Falseがあっても通常実行は可能です。

---

## 8. バージョン確認

```bash
python3 vessel_voxel_volume.py --version
```

```text
vessel_voxel_volume.py 1.2.0
```

を確認してください。

---

## 9. 基本実行

入力モデルがm単位、1 mm voxelなら：

```bash
python3 vessel_voxel_volume.py 0015Jinmen_small.ply --unit m --pitch 1.0
```

`--pitch`は入力モデルの単位にかかわらず**常にmm**です。

---

## 10. 出力単位

内部計算はmmに統一します。

入力がmなら、

- processed PLY：m
- QC用PLY：m
- seed / spill height：m
- 主容量：m³
- 参考容量：L / mL

です。

入力がmmなら主容量はmm³、cmならcm³です。

---

## 11. 出力フォルダ

例えば、

```text
0015Jinmen_small.ply
```

なら、

```text
0015Jinmen_small_PotteryVolume_v1/
├── archaeological/
├── processed/
│   └── 0015Jinmen_small_exact_welded.ply
├── qa/
│   ├── topology_before_exact_weld.json
│   ├── topology_after_exact_weld.json
│   ├── exact_weld_report.json
│   ├── pymeshlab_crosscheck.json
│   └── preprocessing_summary.json
└── pitch_1mm/
    ├── result.json
    ├── qa/
    └── qc/
```

となります。

2 / 1 / 0.5 mmを実行すると、

```text
pitch_2mm/
pitch_1mm/
pitch_0p5mm/
```

へ分かれます。

---

## 12. Stage Aで確認する項目

実行時に、

```text
boundary edges before
boundary edges after
components after
2-manifold after
closed 2-manifold
non-2-manifold edges
geometry preserved
```

を表示します。

例えば、

```text
boundary edges before: 17290
boundary edges after : 0
```

なら、raw meshの境界の多くが、**同じ位置に重複した頂点によるトポロジー上のseam**だったことを示します。

afterにも大量に残る場合は、実際の幾何学的隙間または開境界を検討します。

---

## 13. PyMeshLab cross-check

```text
=== Stage A2: PyMeshLab independent cross-check ===
PyMeshLab version : ...
plugins loaded    : ...
cross-check status: ...
used for calculation mesh: False
```

結果は、

```text
qa/pymeshlab_crosscheck.json
```

に保存します。

PyMeshLabのduplicate-removal filterが使える場合は、人工duplicate meshによるsynthetic smoke testも内部で実施します。

---

## 14. spillが低すぎる場合

異常に低いspillを検出すると、

```text
surface_voxels.ply
spill_slab_surface.ply
spill_slab_free.ply
spill_vs_raw_fragment_boundaries.ply
spill_boundary_proximity.json
```

を出力します。

特に、

```text
fraction_within_one_pitch
```

は、spill経路がraw fragment boundary候補から1 voxel以内にある割合です。

高い値は接合線由来の漏れを支持しますが、それだけで原因を断定するものではありません。

---

## 15. voxelの詳細出力

通常計算でもsurface voxel全体を確認したい場合：

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --unit m \
  --pitch 1.0 \
  --debug-voxels
```

---

## 16. 複数解像度の比較

研究用途では、

```bash
python3 vessel_voxel_volume.py pottery.ply --unit m --pitch 2.0
python3 vessel_voxel_volume.py pottery.ply --unit m --pitch 1.0
python3 vessel_voxel_volume.py pottery.ply --unit m --pitch 0.5
```

を推奨します。

surface voxelは厚さを持つため、容量は解像度依存です。

---

## 17. PyMeshLabを必須にする場合

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --unit m \
  --pitch 1.0 \
  --require-pymeshlab
```

この場合のみ、必要フィルタがロードされていない、またはPyMeshLab smoke testが失敗した場合にエラー終了します。

通常は指定しません。

---

## 18. 自己検証

配布版について実施した検証は `SELF_TEST.md` に記録しています。

少なくとも、

- Python構文チェック
- `--version`
- `--help`
- `--diagnose-env`
- PyMeshLabなしでの全工程
- 全faceを分離した人工seamモデルのexact weld
- mm入力とm入力の双方
- m入力時のprocessed/QC PLY座標単位
- `--require-pymeshlab`の意図的エラー

を確認しています。

---

## 19. 研究上の注意

容量値を研究成果として利用する前に、

1. 既知容量容器による精度検証
2. 2 / 1 / 0.5 mmで収束確認
3. raw / exact-weld後boundaryの比較
4. spill位置のCloudCompare確認
5. QA JSONの保存

を推奨します。

特に、

> 元メッシュのトポロジー  
> exact weld後のトポロジー  
> voxel障壁の連続性

は別々の問題として検証してください。
