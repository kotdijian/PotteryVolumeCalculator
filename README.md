# PotteryVolumeCalculator v1.1.0

OBJ / PLY 形式の土器3Dメッシュから、**液体が最初に外へ溢れ出す直前までの最大内容量**をボクセル法で推定する実験用ツールです。

Pythonを初めて使う文系・考古学系研究者でも試せるように、インストールから結果の確認まで順番に説明します。


## v1.1.0の変更点

v1.1では、Trimeshがraw meshで検出するboundary edgeを、容量計算上の単なる「エラー候補」として捨てず、**復元土器の破片接合線・破片位置を再抽出するための考古学的派生データ**として別系統で保存します。

処理は二系統になります。

```text
入力PLY / OBJ
   │
   ├── archaeological系統
   │      raw boundary edge
   │          ↓
   │      線状PLY・統計・connected components
   │          ↓
   │      破片境界候補として保存
   │
   └── volume系統
          PyMeshLab QA
          ↓
          duplicate vertex除去
          ↓
          cleaned mesh
          ↓
          voxelization
          ↓
          spill-level容量計算
```

また、異常に低いspillが検出された場合は、spill経路とraw boundaryとの最近距離を計算し、接合線付近から漏れている可能性を定量的に確認します。

### PyMeshLabのファイルI/Oについて

PyMeshLabにはPLY/OBJを直接読み込ませません。ファイルI/OはTrimesh、QAとduplicate vertex除去はPyMeshLabが担当します。これにより一部環境の`Unknown format for load: ply`を回避します。

---

## 1. v1で何を計算するか

このプログラムでは「土器の容量」を、

> **土器をZ軸方向に直立させた状態で、液体が最初に外へ流出する直前まで保持できる最大内容量**

と定義します。

口縁が完全に水平でなくても構いません。

処理は概ね次の順序です。

```text
OBJ / PLY
   ↓
Trimeshでファイル読込
   ↓
頂点・face配列をPyMeshLabへ渡す
   ↓
PyMeshLabでトポロジー検査
   ↓
完全同一座標の重複頂点だけを整理
   ↓
Trimeshで再検査
   ↓
内部計算用にmmへ変換
   ↓
surface voxelization
   ↓
土器内部のseedを取得
   ↓
高さ制限付き3D Flood Fill
   ↓
最初に外へつながるspill levelを探索
   ↓
spill直前までの内部空間を計数
   ↓
最大保持液量
```

---

## 2. v1の対象

### 適している資料

- 単純な単口縁
- 口縁に大きな突起がない
- 把手・注口がない
- 内面が滑らか
- 大きな欠損がない
- 土器全体の内外面を含む三角形メッシュ
- 土器をZ軸方向に直立させられる

### 現段階では注意が必要な資料

- 大きな波状口縁
- 把手・注口
- 内部突起
- 大きな欠損
- 接合されていない復元片を多数含むモデル
- 多数の自己交差やnon-manifold部分を含むモデル

---

## 3. PyMeshLabを導入した理由

v1では、Trimeshだけでなく**PyMeshLabを独立したQA検査器**として使用します。

**ファイルの読み書きはTrimesh、QAと限定的な前処理はPyMeshLab**という役割分担です。

これは、MeshLab GUIとTrimeshでトポロジー判定が異なる場合を切り分けるためです。

PyMeshLabでは、

- Boundary Edges
- Connected Components
- 2-manifoldかどうか
- non-2-manifold edges / vertices
- holes
- genus

などを記録します。

その後、

- `Remove Duplicate Vertices`
- `Remove Unreferenced Vertices`

だけを実行します。

### v1では自動実行しない処理

次の処理は形状やトポロジーそのものを変える可能性があるため、自動では行いません。

- Close Holes
- Merge Close Vertices
- Repair non-manifold edges
- Repair non-manifold vertices

したがって、入力データの問題をプログラムが勝手に「修復」して容量を変えてしまうことを避けています。

---

# 4. 入力メッシュの条件

## ファイル形式

- PLY
- OBJ

を使用できます。

容量計算ではテクスチャを使用しないため、計測用にはPLYを推奨します。

## 上下方向

**Z軸を上下方向**にしてください。

```text
       +Z
        ↑
      ______
     /      \
    /        \
   |          |
   |          |
    \________/
```

口縁が上、底が下です。

## 単位

入力座標は次の3種類に対応しています。

```text
mm
cm
m
```

実行時に明示します。

例：

```bash
--unit mm
```

または、

```bash
--unit m
```

### 単位は自動判定しません

高さ30 cmの土器なら、

```text
mmデータ   約300
cmデータ   約30
mデータ    約0.30
```

です。

小型・大型資料では数値だけから単位を確実に推定できないため、必ず指定してください。

---

# 5. 内部計算と出力単位

計算精度と実装を統一するため、**内部ではすべてmmに変換して計算**します。

ただし、最終出力は入力単位へ戻します。

例えば入力がmの場合、

```bash
python3 vessel_voxel_volume.py pottery.ply --unit m --pitch 1.0
```

なら、

- 入力メッシュ：m
- 内部計算：mm
- voxel pitch：1 mm
- QC用PLY座標：m
- spill level：m
- 主たる容量表示：m³
- 参考表示：L / mL

となります。

### 容積の単位について

長さの単位がmなら、容積はmではなく**m³**です。

同様に、

```text
入力 mm → 主容量 mm³
入力 cm → 主容量 cm³
入力 m  → 主容量 m³
```

として出力します。

L / mLも常に併記します。

---

# 6. 出力フォルダ

v1では結果を入力ファイルと同じ階層へ直接ばらまきません。

例えば、

```text
0015jinmen_small.ply
```

を実行すると、自動的に、

```text
0015jinmen_small_PotteryVolume_v1/
```

を作成します。

1 mm計算の場合の例です。

```text
0015jinmen_small_PotteryVolume_v1/
├── archaeological/
│   ├── raw_boundary_vertices.ply
│   ├── raw_boundaries_sampled.ply
│   ├── raw_boundary_stats.json
│   ├── raw_components.csv
│   ├── raw_components.json
│   ├── raw_components_colored.ply
│   ├── after_duplicate_removal_boundaries_sampled.ply
│   └── boundary_before_after_comparison.json
│
├── processed/
│   └── 0015jinmen_small_pymeshlab_cleaned.ply
│
├── qa/
│   ├── pymeshlab_before.json
│   └── pymeshlab_after.json
│
└── pitch_1mm/
    ├── result.json
    ├── qa/
    │   ├── trimesh_qa.json
    │   └── voxel_qa.json
    │
    └── qc/
        ├── fluid_surface.ply
        ├── seed_point.ply
        ├── spill_level_region.ply
        └── ...
```

0.5 mmを追加実行すると、

```text
pitch_0p5mm/
```

が追加されます。

このため、同じ資料について2 / 1 / 0.5 mmを比較してもファイルが混在しません。

---


# 7. `archaeological/`の意味

`archaeological/`は容量計算の一時ファイルではありません。元メッシュが持つ破片境界情報を、今後の破片再抽出に利用するため保存します。

主なファイルは次のとおりです。

### `raw_boundaries_sampled.ply`

**一切cleaningする前のraw mesh**から得たboundary edgeを、0.5 mm間隔（既定値）で線上サンプリングした点群です。

CloudCompareで表示すると、接合線が連続した線として確認しやすくなります。

### `raw_components_colored.ply`

raw meshのface adjacencyから得たconnected componentを色分けしたPLYです。

復元土器の各破片がトポロジー上独立している場合、componentが実破片に対応する可能性があります。ただし、**プログラムはcomponent＝考古学的破片と自動断定しません**。

### `raw_components.csv`

各componentについて、

- face数
- vertex数
- 表面積
- 重心XYZ
- bounding box

を記録します。入力がmなら座標はm、面積はm²です。

### `after_duplicate_removal_*`

PyMeshLabで完全同一座標のduplicate vertexを統合した後に、同じ解析を行った結果です。

### `boundary_before_after_comparison.json`

rawとduplicate removal後でboundary edge数・component数がどの程度減ったかを比較します。

大幅に減る場合、raw boundaryの相当部分が「同じ位置にあるが別頂点として保存された接合線」だった可能性があります。

---

# 8. spillと破片境界の関係

spillがメッシュ高の上部25%より低い位置で検出された場合、v1.1は追加で、

```text
spill_vs_raw_fragment_boundaries.ply
spill_boundary_proximity.json
```

を出力します。

色付きPLYでは、raw boundary候補とspill付近のfree-spaceを同じ点群に重ねています。CloudCompareで位置関係を直接確認できます。

JSONには、spill付近の点がraw boundaryから、

- 0.5 voxel pitch以内にある割合
- 1 voxel pitch以内にある割合
- 最近距離の中央値

などを記録します。

この割合が高い場合、**破片接合部がvoxel上の漏れ経路になっている可能性を支持します**。ただし、近接だけで因果関係を確定するものではありません。

---

# 9. boundaryサンプリング間隔

容量計算とは独立した設定です。

既定値は、

```text
0.5 mm
```

です。

変更する場合は、

```bash
python3 vessel_voxel_volume.py pottery01.ply \\
  --unit m \\
  --pitch 1.0 \\
  --boundary-sample-mm 0.25
```

とします。

入力がmでも、このオプションは常にmmで指定します。出力PLYの座標自体は入力単位（この例ではm）へ戻されます。

---

# 10. Pythonを確認する

このREADMEではPython 3.10以上を推奨します。

## macOS

「ターミナル」を開いて、

```bash
python3 --version
```

を実行します。

例：

```text
Python 3.12.4
```

## Windows

PowerShellで、

```powershell
py --version
```

を実行します。

---

# 11. GitHubから取得する

Gitを使ったことがない場合は、Gitコマンドを使う必要はありません。

GitHubのリポジトリ画面で、

```text
Code
 ↓
Download ZIP
```

を選択し、ZIPを展開します。

最低限、

```text
PotteryVolumeCalculator/
├── README.md
├── requirements.txt
└── vessel_voxel_volume.py
```

があれば実行できます。

---

# 12. 仮想環境を作る

Pythonライブラリをこのプログラム専用に分離するため、`.venv`を作ることを推奨します。

## macOS

リポジトリのフォルダへ移動して、

```bash
python3 -m venv .venv
```

続いて、

```bash
source .venv/bin/activate
```

とします。

行頭に、

```text
(.venv)
```

が表示されれば有効です。

## Windows

```powershell
py -m venv .venv
```

続いて、

```powershell
.venv\Scripts\Activate.ps1
```

です。

---

# 13. 必要なPythonモジュール

v1では次を使用します。

- NumPy
- SciPy
- Trimesh
- Pillow
- PyMeshLab

### 一括インストール

仮想環境を有効にした状態で、

```bash
python3 -m pip install -r requirements.txt
```

を実行してください。

Windowsで`python3`が使えない場合は、

```powershell
py -m pip install -r requirements.txt
```

です。

### 個別にインストールする場合

```bash
python3 -m pip install numpy scipy trimesh Pillow pymeshlab
```

です。

---

## 14. `PIL`エラーについて

次のエラーが出る場合があります。

```text
No module named 'PIL'
```

この場合、インストールする名前は`PIL`ではありません。

```bash
python3 -m pip install Pillow
```

です。

`Pillow`を入れるとPythonからは`PIL`という名前で読み込まれます。

---

## 15. PyMeshLabのインストールエラー

PyMeshLabが入っていない場合は、

```text
No module named 'pymeshlab'
```

と表示されます。

次を実行します。

```bash
python3 -m pip install pymeshlab
```

または、

```bash
python3 -m pip install -r requirements.txt
```

をもう一度実行してください。

PyMeshLabは64-bit Python環境を前提としています。

---

# 16. バージョン確認

ダウンロードしたファイルが正しいか確認するため、

```bash
python3 vessel_voxel_volume.py --version
```

を実行してください。

v1.1なら、

```text
vessel_voxel_volume.py 1.1.0
```

と表示されます。

---

# 17. 最初の実行

入力ファイルがmmなら、

```bash
python3 vessel_voxel_volume.py pottery01.ply --unit mm --pitch 1.0
```

です。

mなら、

```bash
python3 vessel_voxel_volume.py pottery01.ply --unit m --pitch 1.0
```

です。

`--pitch`は入力単位に関係なく**常にmm**です。

したがって、

```bash
--unit m --pitch 1.0
```

は、

> m単位の入力メッシュを内部でmmに変換し、1 mmボクセルで計算する

という意味です。

---

# 18. 実行時の3段階QA

## Stage A: PyMeshLab

```text
=== Stage A: PyMeshLab QA / preprocessing ===
```

MeshLab系のトポロジー判定を行います。

特に、

```text
boundary edges
components
2-manifold
non-2-manifold edges
```

を確認します。

PyMeshLab処理後の頂点・face配列はTrimeshへ戻し、

```text
processed/
```

にPLYとして保存されます。

このファイルは**入力と同じ座標単位**です。PyMeshLab自身のPLY保存機能は使用しません。

## Stage B: Trimesh

```text
=== Stage B: Trimesh QA ===
```

実際にvoxelizerへ渡すメッシュをTrimesh側でも検証します。

PyMeshLabとTrimeshで数値が違う場合、それ自体が重要なQA情報です。

## Stage C: Voxel

```text
=== Stage C: Surface voxelization ===
```

実際にFlood Fillが障壁として使用するsurface voxelを作ります。

ここで、

```text
components : 6=..., 18=..., 26=...
```

も記録します。

元メッシュが閉じていても、voxel化後の障壁に隙間が生じる可能性があります。

---

# 19. spill level

プログラムは土器内部の液面を低い位置から上げていき、

> 初めて外部へ通じる高さ

を探索します。

例：

```text
safe level : 0.201 m
spill level: 0.202 m
```

なら、

```text
0.201 m < 実際のspill高さ <= 0.202 m
```

という意味です。

1 mm voxelなら、高さ方向の分解能も基本的に1 mmです。

---

# 20. 結果

m単位入力の場合は例えば、

```text
=== Maximum retained liquid volume ===
volume : 0.00549 m^3
volume : 5.49 L
volume : 5490.000000 mL
```

のように表示します。

m入力なら、QC用PLYの座標もmです。

---

# 21. CloudCompareによるQC

`qc/`内のPLYを元メッシュと一緒にCloudCompareで読み込みます。

通常確認するファイルは、

```text
fluid_surface.ply
spill_level_region.ply
seed_point.ply
```

です。

### fluid_surface.ply

プログラムが液体空間と判定した領域の表面です。

- 土器内面に沿っている
- 器壁外へ漏れていない
- 底からspill levelまで連続している

ことを確認します。

### spill_level_region.ply

最初に外部と接続した高さ付近です。

正常なら、単純器形では口縁の低い部分付近に現れるはずです。

### seed_point.ply

内部領域のFlood Fill開始点です。

土器内部にあることを確認します。

---

# 22. spill levelが低すぎる場合

例えば土器高が230 mm程度なのに、

```text
spill level = 27 mm
```

となる場合、正常な口縁流出とは考えにくいため警告します。

このとき自動的に、

```text
surface_voxels.ply
spill_slab_surface.ply
spill_slab_free.ply
```

も出力します。

これをCloudCompareで表示すると、

- 実メッシュに穴がある
- voxel化によって1セル程度の隙間が生じた

のどちらかを検討できます。

---

# 23. エラー時にも診断ファイルを残す

spill探索中にエラーになった場合でも、

```text
surface_voxels_on_error.ply
error.json
voxel_qa.json
```

を出力します。

したがって、単に、

```text
ERROR
```

で終了するのではなく、失敗原因を3Dで確認できます。

---

# 24. 複数解像度で比較する

まず、

```bash
python3 vessel_voxel_volume.py pottery01.ply --unit m --pitch 2.0
python3 vessel_voxel_volume.py pottery01.ply --unit m --pitch 1.0
python3 vessel_voxel_volume.py pottery01.ply --unit m --pitch 0.5
```

の3条件を推奨します。

結果は、

```text
pottery01_PotteryVolume_v1/
├── pitch_2mm/
├── pitch_1mm/
└── pitch_0p5mm/
```

に分かれます。

---

# 25. `--debug-voxels`

通常の計算が成功してもsurface voxel全体を確認したい場合は、

```bash
python3 vessel_voxel_volume.py pottery01.ply \
  --unit m \
  --pitch 1.0 \
  --debug-voxels
```

とします。

---

# 26. 出力先を指定する

既定では入力ファイルと同じ階層に、

```text
<stem>_PotteryVolume_v1/
```

を作ります。

別の場所へ保存したい場合は、

```bash
python3 vessel_voxel_volume.py pottery01.ply \
  --unit m \
  --pitch 1.0 \
  --output-dir results/pottery01
```

とします。

---

# 27. `Unknown format for load: ply`について

v1.0.0ではPyMeshLabの`load_new_mesh()`を使用していたため、一部環境で、

```text
ERROR: Unknown format for load: ply
```

が発生しました。

v1.1ではPyMeshLabにファイルを直接読み込ませないため、このエラーを回避します。

もしv1.1でもこのメッセージが出る場合は、古い`vessel_voxel_volume.py`を実行している可能性があります。

```bash
python3 vessel_voxel_volume.py --version
```

で、

```text
1.0.1
```

になっていることを確認してください。

---

# 28. pipの更新通知

実行時に、

```text
A new release of pip is available
```

と表示されても、このプログラムのエラーではありません。

通常は無視して構いません。

---

# 29. 最短の実行手順（macOS）

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 vessel_voxel_volume.py --version
python3 vessel_voxel_volume.py pottery01.ply --unit m --pitch 1.0
```

結果フォルダ内の、

```text
pitch_1mm/qc/
```

をCloudCompareで確認してください。

---

# 30. 研究上の注意

本ツールは現段階では実験・検証用です。

容量値を研究成果として使用する前に、

1. 既知容量の容器で検証
2. 2 / 1 / 0.5 mmで収束確認
3. PyMeshLab / Trimesh / voxel QAを保存
4. CloudCompareでspill位置を確認

することを推奨します。

特に重要なのは、

> **元メッシュのトポロジーが正常であることと、voxel化後の障壁が閉じていることは別問題**

という点です。

---

# 31. requirements.txt

v1では以下を使用します。

```text
numpy>=1.26
scipy>=1.11
trimesh>=4.0,<6
Pillow>=10
pymeshlab>=2023.12
```

インストールは、

```bash
python3 -m pip install -r requirements.txt
```

で行ってください。


---

## v1.1で保存する破片境界データについて

`archaeological/`以下のraw boundary / componentデータは、**容量算出値そのものには使用しません**。容量計算はPyMeshLabでduplicate vertex等を整理したcleaned meshから行います。

したがって、破片境界情報を保持しながら、容量計算側では不要なトポロジー上の継ぎ目を可能な範囲で除去できます。
