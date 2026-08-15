# Pottery Volume Calculator

OBJ / PLY 形式の土器3Dメッシュから、**液体が最初に外へ溢れ出す直前までの最大内容量**をボクセル法で推定する実験用Pythonスクリプトです。

このREADMEは、Pythonをほとんど使ったことがない研究者でも実行できることを想定しています。

**Version: 0.3.2**

---

## 1. このプログラムが求める「容積」

このプログラムでは、土器の内容積を次のように定義します。

> 土器を通常の姿勢で置き、液面を水平に保ったまま液体を増やしていったとき、最も低い口縁などから液体が初めて外へ流出する直前までに保持できる最大容量。

したがって、口縁が完全に水平である必要はありません。

波状口縁や多少傾いた口縁の場合も、仮想的な水平の蓋を作るのではなく、**内部空間が外部へ初めてつながる高さ（spill level）**を探索します。

```text
液面を上昇
     ↓
内部空間がまだ外部へつながらない
     ↓
さらに上昇
     ↓
最初に外部へ流出する高さ = spill level
     ↓
その1ボクセル下までの内部空間を容量として計算
```

---

## 2. 現在の対象

まず単純な器形で方法を検証するため、次のような資料を対象とします。

### 適している資料

- 単口縁
- 大きな突起・把手・注口がない
- 内面が比較的滑らか
- 大きな欠損がない
- 土器全体の内外面を含むメッシュがある
- 土器をZ軸方向に直立させられる

### 現段階では慎重に扱う資料

- 大きな波状口縁
- 把手・注口を持つ器
- 複雑な突起を持つ器
- 大きく欠損した資料
- 復元部や穴埋め部を多く含む資料
- 内部に仕切りなどがある器

---

## 3. 入力ファイル

使用できる形式は次の2種類です。

- `PLY`
- `OBJ`

容量計算だけであれば、テクスチャは使用しません。計測用にはPLYを推奨します。

### 座標単位

入力メッシュは次の単位に対応します。

- `mm`
- `cm`
- `m`

実行時に `--unit` で指定します。

```bash
# mm単位
python3 vessel_voxel_volume.py pottery01.ply --unit mm --pitch 1.0

# m単位
python3 vessel_voxel_volume.py pottery01.ply --unit m --pitch 1.0
```

内部ではmmに変換してから計算します。元のPLY / OBJファイルは変更しません。

`--pitch` は入力ファイルの単位に関係なく、常に **mm** です。

---

## 4. メッシュの姿勢

土器の上下方向を **Z軸** に合わせてください。

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

CloudCompareなどで回転してからPLYとして保存すると分かりやすいです。

実行前には最低限、次を確認してください。

1. 口縁が上、底部が下
2. Z軸がおおむね鉛直方向
3. 入力単位が分かっている
4. 明らかな大穴や不要な別メッシュがない

---

# 5. 最初の準備

## 5.1 Pythonの確認

このプログラムはPython 3を使用します。

macOSでは「ターミナル」を開き、次を入力します。

```bash
python3 --version
```

Python 3.10以上を推奨します。

---

## 5.2 GitHubから取得する

Gitを使ったことがなければ、GitHubのリポジトリ画面から、

**Code → Download ZIP**

で取得して構いません。

ZIPを展開すると、少なくとも次の3ファイルがあります。

```text
PotteryVolumeCalculator/
├── vessel_voxel_volume.py
├── README.md
└── requirements.txt
```

---

## 5.3 ターミナルでフォルダを開く

macOSでは、ターミナルに

```bash
cd 
```

と入力し、`cd`の後に半角スペースを残した状態で、Finderからフォルダをターミナルへドラッグできます。

Enterを押したあと、

```bash
ls
```

を実行し、

```text
vessel_voxel_volume.py
README.md
requirements.txt
```

が表示されれば準備できています。

---

# 6. Pythonの仮想環境を作る

ライブラリをこのプログラム専用に分けるため、仮想環境 `.venv` の使用を推奨します。

最初に1回だけ、

```bash
python3 -m venv .venv
```

を実行します。

続けて、

```bash
source .venv/bin/activate
```

を実行します。

成功するとターミナルの行頭に、

```text
(.venv)
```

と表示されます。

次回以降も、このフォルダで作業を始めるときは、

```bash
source .venv/bin/activate
```

を実行してください。

---

# 7. 必要なPythonモジュールをインストールする

このプログラムでは次のライブラリを使用します。

- NumPy
- SciPy
- Trimesh
- Pillow

**推奨方法は `requirements.txt` を使う方法です。**

仮想環境 `(.venv)` が有効になっていることを確認して、

```bash
python3 -m pip install -r requirements.txt
```

を実行してください。

個別にインストールする場合は、

```bash
python3 -m pip install numpy scipy trimesh Pillow
```

です。

## 重要：`PIL` と `Pillow`

エラーに、

```text
No module named 'PIL'
```

と表示されることがあります。

この場合、インストールするパッケージ名は `PIL` ではなく **`Pillow`** です。

```bash
python3 -m pip install Pillow
```

を実行してください。

## pipの更新通知について

次のような表示はエラーではありません。

```text
[notice] A new release of pip is available
```

この通知が出ても、そのままプログラムを実行できます。

pipの更新は任意です。

```bash
python3 -m pip install --upgrade pip
```

---

## 7.1 インストール確認

次を実行してください。

```bash
python3 -c "import numpy, scipy, trimesh, PIL; print('modules OK')"
```

```text
modules OK
```

と表示されれば準備完了です。

---

# 8. プログラムのバージョンを確認する

今回のコードは、以前の版との混同を避けるためバージョン番号を表示できます。

```bash
python3 vessel_voxel_volume.py --version
```

正しい版なら、

```text
vessel_voxel_volume.py 0.3.2
```

と表示されます。

**実験開始前に必ずこの表示を確認することを推奨します。**

---

# 9. まず1個体を1 mmで計測する

土器ファイルを同じフォルダに置きます。

```text
PotteryVolumeCalculator/
├── vessel_voxel_volume.py
├── README.md
├── requirements.txt
└── pottery01.ply
```

入力がmm単位なら、

```bash
python3 vessel_voxel_volume.py pottery01.ply --unit mm --pitch 1.0
```

入力がm単位なら、

```bash
python3 vessel_voxel_volume.py pottery01.ply --unit m --pitch 1.0
```

です。

---

# 10. プログラムが行う処理

```text
OBJ / PLY
   ↓
単位をmmへ統一
   ↓
メッシュQA
   ├─ watertight
   ├─ boundary edge
   ├─ non-manifold edge
   └─ degenerate face
   ↓
メッシュ全体をsurface voxel化
   ↓
器高10〜60%の範囲で内部空隙seedを探索
   ↓
高さ制限付き3D Flood Fill
   ↓
二分探索でspill levelを検出
   ↓
spill直前の液体領域を抽出
   ↓
voxel数 × voxel体積
   ↓
最大内容量 mL / L
```

内面だけを手作業で抽出する工程はありません。

---

# 11. メッシュ検証（Mesh QA）

容量計算の前に、メッシュの状態を表示します。

例：

```text
=== Mesh QA ===
watertight          : False
winding consistent  : True
body count          : 1
boundary edges      : 42
non-manifold edges  : 0
degenerate faces    : 0
```

## watertight

理想的な土器メッシュでは、外面・口縁・内面・底部が連続し、メッシュとして閉じていることが望まれます。

`False` の場合は、どこかに境界edgeや欠損がある可能性があります。

ただし本プログラムは直ちに停止せず、その後のspill判定も試みます。

## boundary edges

1枚の三角形にしか共有されていないedgeです。

0でない場合、次のQCファイルが作成されます。

```text
*_mesh_boundary_points.ply
```

CloudCompareで元メッシュと重ね、境界がどこにあるかを確認してください。

## non-manifold edges

3枚以上のfaceが共有しているedgeです。

存在する場合、

```text
*_mesh_nonmanifold_points.ply
```

が作成されます。

---

# 12. spill levelの検出

このプログラムは、内部の液面を仮想的に上げていきます。

実際には1層ずつすべて試すのではなく、二分探索を使って、

```text
漏れない高さ
漏れる高さ
```

の境界を探します。

例：

```text
safe level : index 149, Z=290.000 mm
spill level: index 150, Z=292.000 mm
```

この場合、

```text
290 mm < 実際の流出高 <= 292 mm
```

という2 mm voxelでの離散化範囲になります。

1 mm voxelなら、この高さ方向の区間は約1 mmになります。

---

# 13. 容量の表示

正常に終了すると、

```text
=== Maximum retained volume ===
fluid voxels : ...
volume       : ... mm^3
volume       : ... mL
volume       : ... L
```

と表示されます。

研究上は `mL` または `L` を使用すると分かりやすいでしょう。

---

# 14. 出力ファイル

1 mmで計算した場合、次のようなファイルが生成されます。

```text
pottery01_voxel_1mm_mesh_qa.json
pottery01_voxel_1mm_result.json
pottery01_voxel_1mm_fluid_surface.ply
pottery01_voxel_1mm_spill_level_region.ply
pottery01_voxel_1mm_seed_point.ply
```

メッシュに問題がある場合はさらに、

```text
pottery01_voxel_1mm_mesh_boundary_points.ply
pottery01_voxel_1mm_mesh_nonmanifold_points.ply
```

が作成されます。

## `*_mesh_qa.json`

容量計算が途中で失敗しても残るメッシュ検証結果です。

## `*_result.json`

容量計算が正常終了した場合の全結果です。

## `*_fluid_surface.ply`

spill直前まで液体が占めると判定された内部領域の表面です。

## `*_spill_level_region.ply`

spill levelで内部と外部がつながった領域を確認するためのQCデータです。

## `*_seed_point.ply`

内部空隙の探索に使用したseed位置です。

---

# 15. CloudCompareで必ずQCする

最初の実験では数値だけを採用せず、CloudCompareで確認してください。

少なくとも、

1. 元の土器メッシュ
2. `*_fluid_surface.ply`
3. `*_spill_level_region.ply`
4. `*_mesh_boundary_points.ply`（存在する場合）

を重ねます。

### 正常と考えられる状態

- `fluid_surface` が土器内部に収まる
- spill levelが口縁付近にある
- spill領域が最も低い口縁付近から外へつながる
- boundary pointsが存在しない、または容量に影響しない位置だと確認できる

### 要注意

- spill levelが胴部中央や底部付近
- boundary pointsが胴部内外面を貫く穴の周囲に集中
- fluid surfaceが器外へ漏れる
- seed pointが器壁の中や器外にある

---

# 16. 自動QCのspill ratio

プログラムは、spill levelが器高のどの位置にあるかを、

```text
spill ratio: 0.93 of mesh height
```

のように表示します。

現在の単純器形向け設定では、上部25%以内、すなわち、

```text
spill ratio >= 0.75
```

なら口縁由来として比較的妥当な可能性が高い、という**簡易的な警告基準**を使っています。

これは判定の保証ではありません。最終判断はCloudCompareで行ってください。

---

# 17. メッシュに穴がある場合

内部seedの高さですでに外部へ漏れている場合、次のようなエラーになります。

```text
内部seedの高さですでに外部へ漏れています。
口縁より低い位置にメッシュ穴がある可能性が高いです。
```

この場合、容量値は出力しません。

まず、

```text
*_mesh_boundary_points.ply
*_mesh_qa.json
```

を確認してください。

この仕様は、メッシュ欠損による誤った小容量を、正常な計測値として採用しないためのものです。

---

# 18. 2 mm / 1 mm / 0.5 mmを比較する

ボクセル法では解像度によって容量が変化します。

まず1 mmを標準的な実験値とし、可能なら次の3条件を比較してください。

```bash
python3 vessel_voxel_volume.py pottery01.ply --unit mm --pitch 2.0
python3 vessel_voxel_volume.py pottery01.ply --unit mm --pitch 1.0
python3 vessel_voxel_volume.py pottery01.ply --unit mm --pitch 0.5
```

例：

| voxel size | volume |
|---:|---:|
| 2.0 mm | 5,420 mL |
| 1.0 mm | 5,470 mL |
| 0.5 mm | 5,492 mL |

解像度を細かくしたときに値が収束するかを確認します。

---

# 19. なぜ解像度で容量が変わるのか

元の三角形メッシュ表面には数学的な厚さはありません。

しかしボクセル化すると、表面が一定の厚さを持つ格子として表現されます。

```text
実際の面
────────────

voxel化した境界
████████████
```

そのため、内部空間がわずかに小さく評価される場合があります。

この影響を確認するため、複数pitchで計測します。

---

# 20. 計算時間とメモリ

1 mm voxelでは、一般的な数十cm程度の土器なら通常のノートPCでも現実的な規模です。

ただし計算時間は、

- 土器の大きさ
- face数
- voxel pitch

に依存します。

特に、

```text
Surface voxelization
```

が最も時間を使うことがあります。

0.5 mmでは各方向の格子数がおおむね2倍になるため、3D格子全体は最大で約8倍になります。

まず1 mmで動作確認してから0.5 mmを試してください。

---

# 21. よくあるエラー

## `No module named 'PIL'`

```bash
python3 -m pip install Pillow
```

または、

```bash
python3 -m pip install -r requirements.txt
```

を実行してください。

---

## `No module named 'trimesh'`

```bash
python3 -m pip install trimesh
```

---

## `No module named 'scipy'`

```bash
python3 -m pip install scipy
```

---

## `unrecognized arguments: --unit`

古いバージョンのスクリプトを実行している可能性があります。

```bash
python3 vessel_voxel_volume.py --version
```

を実行し、

```text
0.3.2
```

であることを確認してください。

---

## spill levelが異常に低い

メッシュに穴がある可能性があります。

CloudCompareで、

```text
*_mesh_boundary_points.ply
*_spill_level_region.ply
```

を確認してください。

---

## 最上部まで行っても外へ漏れない

voxel化の結果、口部が閉じてしまった可能性があります。

まずpitchを細かくしてください。

```bash
python3 vessel_voxel_volume.py pottery01.ply --unit mm --pitch 0.5
```

---

# 22. 主なオプション

全オプションは、

```bash
python3 vessel_voxel_volume.py --help
```

で確認できます。

### `--unit`

```text
mm / cm / m
```

入力メッシュの単位。

### `--pitch`

```text
1.0
```

voxelの1辺。単位はmm。

### `--min-cavity-area`

内部seed候補として認める最小断面積。通常は変更不要です。

### `--seed-min-fraction` / `--seed-max-fraction`

内部seedを探す器高範囲です。

既定値は、

```text
0.10 ～ 0.60
```

です。

底部の陶胎内部を誤ってseedにしないため、底面直上ではなく器高の途中から探索します。

### `--no-qc`

QC用PLYを出力しません。

通常は使用しないことを推奨します。

---

# 23. 推奨する最初の実験

1. 単純な完形土器を1個体選ぶ
2. CloudCompareでZ軸に直立させる
3. 単位を確認する
4. PLYで保存する
5. `--pitch 1.0` で計算する
6. Mesh QAを見る
7. CloudCompareでfluid / spill / boundaryを確認する
8. 問題がなければ2 mmと0.5 mmでも計測する
9. 3解像度の値を比較する
10. 既知容量の容器などでも検証する

---

# 24. 最短実行例（macOS）

Pythonがすでにインストールされている場合、リポジトリのフォルダで順に実行します。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 vessel_voxel_volume.py --version
python3 vessel_voxel_volume.py pottery01.ply --unit mm --pitch 1.0
```

m単位のPLYなら最後の行だけ、

```bash
python3 vessel_voxel_volume.py pottery01.ply --unit m --pitch 1.0
```

にします。

---

# 25. 研究上の位置づけ

本プログラムは現段階では、土器内容量をボクセル法で取得するための**実験・検証用ツール**です。

研究成果として容量値を使用する場合は、少なくとも、

- CloudCompare等によるQC
- 0.5 / 1 / 2 mmなど複数解像度比較
- 既知容量の容器または単純幾何形状による精度検証
- 使用したコードのversion記録
- `*_result.json` と `*_mesh_qa.json` の保存

を推奨します。
