# PotteryVolumeCalculator v1.4.0

PLY / OBJ形式の土器3Dメッシュから、**液体が最初に外へ溢れ出す直前までの最大内容量**をvoxel法で推定する実験用ツールです。

通常計算、ピッチ収束の検証、AOM出力の姿勢別比較に対応します。

- [AOM出力を使った姿勢別容量比較](#aom-pose-comparison)
- [English README](README_EN.md)
- [関連ツールとリポジトリ構成](docs/README.md)
- [開発・検証レポート v1.3.1（PDF）](docs/validation/PotteryVolumeCalculator_development_validation_report_v1.3.1.pdf)
- [サンプルの放射断面出力](examples/0015Jinmen_small_RadialSections_30deg)

## このプログラムに適した3Dモデル

PotteryVolumeCalculatorは、土器3Dモデルの形状から、**液体を保持できる最大容量**をvoxel法で推定するプログラムです。主として、以下のような資料を対象とします。

- **完形土器・ほぼ完形の土器**  
  底部から口縁までの器形が連続して残るモデルでは、液体が最初に外部へ流出する直前までの最大容量を算出します。

- **底部から上方へ連続した形状が残る残存土器**  
  口縁まで残っていない資料でも、底部から連続して液体を保持できる形状が残っていれば、**現存する形状で液体を保持できる上限までの容量**を算出できます。したがって、この値は本来の完形時容量ではなく、残存部分の保持容量です。

- **接合復元された土器**  
  接合面で頂点が完全に一致している場合は、計算用メッシュ上でそれらを統合して処理します。一方、実際に幾何学的な隙間や欠損が残っている場合、それらは液体の流出経路として扱われます。小さな隙間はvoxel pitchとの関係によって計算上閉じる場合がありますが、**一定サイズ以下の隙間を自動的に穴埋めする機能ではありません**。

- **欠損や開口部のある土器**  
  器壁に大きな欠損や穴がある場合、その位置から液体が流出するため、通常は**その開口部の高さまでに保持できる容量**が算出されます。欠損が大きく、内部空間を安定して検出できない場合には計算を完了できないことがあります。本来の器形に近い容量を求める場合は、必要に応じて計算前にモデルを複製し、欠損部を適切に補完してください。補完した場合は、その処理内容を記録しておくことを推奨します。

### 本プログラムの対象外となる資料

底部や器壁が大きく失われ、**断片的に接合された破片から本来の完形時容量を推定する用途**には、本プログラムは適していません。

このような資料については、残存する縦断面形状から器形を推定し、**回転体として復元した形状から容量を算出する別方式**を開発中です。

---


## 検証用サンプルデータの出典

本READMEおよび開発・検証レポートで使用している`0015Jinmen_small.ply`のサンプルデータは、以下の文化財3Dデータを出典とします。

- **人面墨書土器（奈良時代）**
- 静岡県磐田市御殿・二之宮遺跡出土
- 磐田市埋蔵文化財センター所蔵
- レガシズ3D掲載名：**人面墨書土器2**
- レガシズ3Dよりダウンロード  
  https://lega-shizu.com/legashizu3d/archives/data/117
- レガシズ3D上のモデル識別情報：LS0015

本プログラムの検証結果は、このサンプルモデルを**Z軸が上下方向**になるように配置した状態で算出しています。

---



# 初めてPython・CLIを使う方へ

このプログラムは、**ターミナル（Terminal）からコマンドを入力して実行するCLI（Command Line Interface）プログラム**です。専用のGUIアプリを開くのではなく、Pythonに「どのファイルを、どの設定で処理するか」を文字で指定します。

初めて使う場合は、以下の手順を順番に実行してください。

## 0. 用語

- **ターミナル**：文字でコマンドを入力するアプリです。macOSでは「ターミナル」を使用できます。
- **CLI**：ターミナルからコマンドを入力して操作する方法です。
- **ワーキングディレクトリ（作業ディレクトリ）**：現在ターミナルが作業対象としているフォルダです。
- **Python**：`vessel_voxel_volume.py`を実行するためのプログラムです。
- **仮想環境（venv）**：このプログラム専用のPython環境です。他のPythonプログラムとの依存関係の衝突を避けるため、利用を推奨します。

---

## 1. GitHubからプログラムをダウンロードする

GitHubのPotteryVolumeCalculatorリポジトリを開き、

```text
Code → Download ZIP
```

を選択してダウンロードし、ZIPファイルを展開します。

Gitを利用している場合は`git clone`でも構いませんが、初めて利用する場合はZIPダウンロードで問題ありません。

展開したフォルダには、少なくとも次のファイルが含まれます。

```text
PotteryVolumeCalculator/
├── vessel_voxel_volume.py
├── pose_comparison.py
├── README.md
├── requirements.txt
└── requirements-core.txt
```

---

## 2. ターミナルを開く

macOSでは、

```text
アプリケーション → ユーティリティ → ターミナル
```

から起動できます。

以降のコマンドはターミナルへ入力します。

---

## 3. ダウンロードしたフォルダをワーキングディレクトリにする

例えばDownloadsフォルダへ展開した場合：

```bash
cd ~/Downloads/PotteryVolumeCalculator
```

Documents/GitHub以下に置いた場合：

```bash
cd ~/Documents/GitHub/PotteryVolumeCalculator
```

### 現在の場所を確認する

```bash
pwd
```

### 現在のフォルダにあるファイルを確認する

```bash
ls
```

ここで、

```text
vessel_voxel_volume.py
README.md
requirements.txt
```

などが表示されれば準備できています。

### フォルダ名に空白がある場合

パス全体を引用符で囲みます。

```bash
cd "~/Documents/My Pottery Project"
```

ただし、`~`を引用符内に入れると展開されないシェルもあるため、より確実なのは次のように空白だけをエスケープする方法です。

```bash
cd ~/Documents/My\ Pottery\ Project
```

macOSでは、Finder上のフォルダをターミナルへドラッグ＆ドロップすると、そのパスを入力することもできます。

---

## 4. Pythonが利用できるか確認する

```bash
python3 --version
```

例えば、

```text
Python 3.x.x
```

のように表示されればPython 3を利用できます。

```text
command not found: python3
```

などと表示される場合は、先にPython 3をインストールしてください。

---

## 5. 仮想環境を作成する（推奨）

PotteryVolumeCalculatorフォルダ内で、

```bash
python3 -m venv .venv
```

を実行します。

続いて仮想環境を有効化します。

### macOS / Linux

```bash
source .venv/bin/activate
```

成功すると、ターミナルの行頭に、

```text
(.venv)
```

のような表示が追加されます。

### Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
```

仮想環境は一度作成すれば、毎回作り直す必要はありません。ただし、新しくターミナルを開いたときには再度`activate`してください。

仮想環境を終了する場合：

```bash
deactivate
```

---

## 6. 必要なPythonモジュールをインストールする

PyMeshLabを含む環境：

```bash
python3 -m pip install -r requirements.txt
```

PyMeshLabを使用せず、容量計算の基本機能だけを利用する場合：

```bash
python3 -m pip install -r requirements-core.txt
```

インストールは仮想環境ごとに通常1回だけ必要です。プログラムを実行するたびに再インストールする必要はありません。

---

## 7. プログラムが起動するか確認する

```bash
python3 vessel_voxel_volume.py --version
```

次のように表示されれば起動できます。

```text
vessel_voxel_volume.py 1.3.0
```

環境の詳細を確認する場合：

```bash
python3 vessel_voxel_volume.py --diagnose-env
```

---

## 8. 3Dモデルを準備する

最初は、入力するPLYまたはOBJファイルを`vessel_voxel_volume.py`と同じフォルダへ置くと分かりやすくなります。

例：

```text
PotteryVolumeCalculator/
├── vessel_voxel_volume.py
├── requirements.txt
├── README.md
└── 0015Jinmen_small.ply
```

モデルは**Z軸が上下方向**になるようにしてください。また、`--unit`にはモデル座標の実際の単位を指定してください。

---

## 9. 最初の計算を実行する

モデル座標がm、pitchを1 mmとする場合：

```bash
python3 vessel_voxel_volume.py 0015Jinmen_small.ply \
  --unit m \
  --pitch 1.0
```

詳細検証モードなら：

```bash
python3 vessel_voxel_volume.py 0015Jinmen_small.ply \
  --unit m \
  --validate
```

### `\`は何か

READMEのコマンド末尾にある`\`は、**コマンドが次の行へ続く**ことを示します。

したがって、

```bash
python3 vessel_voxel_volume.py 0015Jinmen_small.ply \
  --unit m \
  --pitch 1.0
```

は、1行で、

```bash
python3 vessel_voxel_volume.py 0015Jinmen_small.ply --unit m --pitch 1.0
```

と入力しても同じです。

---

## 10. 入力ファイルが別のフォルダにある場合

ファイルのフルパスまたは相対パスを指定できます。

例：

```bash
python3 vessel_voxel_volume.py ~/Documents/Pottery/0015Jinmen_small.ply \
  --unit m \
  --pitch 1.0
```

ファイル名やフォルダ名に空白がある場合は、パスを引用符で囲みます。

```bash
python3 vessel_voxel_volume.py "/Users/username/Documents/Pottery Data/sample 01.ply" \
  --unit m \
  --pitch 1.0
```

macOSでは、FinderからPLYファイルをターミナルへドラッグ＆ドロップしてパスを入力する方法も便利です。

---

## 11. 計算結果はどこに保存されるか

`--output-dir`を指定しない場合、入力モデルと同じ場所に、

```text
<入力ファイル名>_PotteryVolume_v1/
```

というフォルダを作成します。

例えば、

```text
0015Jinmen_small.ply
```

なら、

```text
0015Jinmen_small_PotteryVolume_v1/
```

です。

同じ入力ファイル・同じpitchで再実行すると同じ出力フォルダを再利用し、同名の結果ファイルは更新されます。


### 監査・正式検証では新しい出力フォルダを使用する

同じ出力フォルダへ複数回実行すると、現在の実行では生成されなかった過去の`error.json`やdebug用PLYが残る場合があります。`result.json`と`validation_summary.json`は更新されますが、**古い診断ファイルが自動削除されるわけではありません**。

研究用の正式な検証では、既存出力フォルダを退避または削除するか、実行ごとに新しい`--output-dir`を指定してください。

異なる実行結果を保存して比較したい場合は、別の`--output-dir`を指定してください。

例：

```bash
python3 vessel_voxel_volume.py 0015Jinmen_small.ply \
  --unit m \
  --pitch 1.0 \
  --output-dir test_run_01
```

---



## WindowsでのPython・CLI利用

README中のmacOS / Linuxの例では`python3`を使用していますが、Windowsでは環境によって`python3`コマンドが存在しないことがあります。Windowsでは、Python Launcherが利用できる場合は`py -3`、仮想環境を有効化した後は`python`を使用する方法が分かりやすいです。

### 1. PowerShellまたはWindows Terminalを開く

Windows 11では、スタートメニューから**Windows Terminal**または**PowerShell**を起動できます。

### 2. Pythonを確認する

```powershell
py -3 --version
```

または、

```powershell
python --version
```

でPython 3が表示されることを確認します。

### 3. PotteryVolumeCalculatorフォルダへ移動する

例：

```powershell
cd "$HOME\Downloads\PotteryVolumeCalculator"
```

現在の場所は、

```powershell
Get-Location
```

ファイル一覧は、

```powershell
Get-ChildItem
```

で確認できます。

### 4. 仮想環境を作成する

```powershell
py -3 -m venv .venv
```

### 5. 仮想環境を有効化する

PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

PowerShellの実行ポリシーによりactivation scriptを実行できない場合は、Windowsのセキュリティ設定を恒久的に変更する前に、**コマンドプロンプト（cmd.exe）を使う方法**を推奨します。

コマンドプロンプトでは：

```bat
.venv\Scripts\activate.bat
```

仮想環境が有効になると、通常は行頭に、

```text
(.venv)
```

と表示されます。

### 6. 必要なモジュールをインストールする

仮想環境を有効化した状態で：

```powershell
python -m pip install -r requirements.txt
```

PyMeshLabなしの基本環境なら：

```powershell
python -m pip install -r requirements-core.txt
```

### 7. バージョン確認

```powershell
python vessel_voxel_volume.py --version
```

### 8. single-pitch modeを実行する

```powershell
python vessel_voxel_volume.py 0015Jinmen_small.ply --unit m --pitch 1.0
```

### 9. validation modeを実行する

```powershell
python vessel_voxel_volume.py 0015Jinmen_small.ply --unit m --validate
```

Windowsでも、ファイル名やフォルダ名に空白がある場合はパスを引用符で囲んでください。

```powershell
python vessel_voxel_volume.py "C:\Users\username\Documents\Pottery Data\sample 01.ply" --unit m --pitch 1.0
```

---

| 用途 | モード | 実行方法 |
|---|---|---|
| 詳細な精度・収束検証 | multi-pitch validation | `--validate` |
| 大量資料を一定条件で処理 | single-pitch | `--pitch 1.0` など |

---

# 1. 想定するユースケース

## A. 詳細な検証を行いたい

1資料について、

```text
2.0 mm
1.0 mm
0.5 mm
```

の3解像度を一括実行します。

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --unit m \
  --validate
```

各pitchは**独立した全工程**として実行します。

```text
exact-coordinate weld / QA
↓
Trimesh QA
↓
surface voxelization
↓
cavity seed validation
↓
spill-level
↓
volume
```

をpitchごとに再実行するため、詳細検証時には各解像度の結果が独立して再現可能です。

処理時間は単一pitchより長くなります。特に0.5 mmはメモリ使用量と計算時間が大きくなります。

---

## B. 大量の資料を処理したい

pitchを1つ指定して実行します。

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --unit m \
  --pitch 1.0
```

例えば高速性を優先する場合：

```bash
--pitch 2.0
```

精度を優先する場合：

```bash
--pitch 0.5
```

とできます。

`--pitch`を省略し、`--validate`も指定しなかった場合は、

```text
pitch = 1.0 mm
```

で実行します。

このsingle-pitchモードを、次段階で予定している**フォルダ内PLY一括処理**の基本処理として使用します。

---

# 2. `--pitch`と`--validate`は同時に指定できない

次のような指定はエラーになります。

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --pitch 1.0 \
  --validate
```

どちらか一方を選択してください。

---

# 3. 容量の定義

容量は、

> 土器を+Z方向に直立させた状態で、液体が最初に外部へ流出する直前まで保持できる最大内容量

と定義します。

水平capは使用しません。

非水平口縁でも、

```text
safe level
↓
spill level
```

を3D flood fillで探索します。

---

# 4. 入力メッシュの姿勢

**Z軸を上下方向**にしてください。

```text
        +Z
         ↑
       口縁
      ______
     /      \
    |        |
    |        |
     \______/
        底
```

容量計算では重力方向を-Zとみなし、液面をZ方向に上昇させます。

姿勢が誤っていると、spill-levelがまったく異なる値になります。


<a id="aom-pose-comparison"></a>
## AOM出力を使った姿勢別容量比較

[ArtefactsOrthoMaker (AOM)](https://github.com/kotdijian/ArtefactsOrthoMaker#pottery-pose) で同じ土器を Rim・Base・Slice のうち比較したい姿勢に切り替え、各姿勢で **「資料を書き出す」** を実行します。初回の出力は資料フォルダに、以降の出力はその中の `revisions/` に保存されます。

比較には、各姿勢の `item_manifest.json`、`transform.json`、正規化済みの `*_rev.ply` が揃ったフォルダを2つ以上指定します。下記のフォルダ名は例です。実際の出力先に置き換えてください。

```bash
python3 vessel_voxel_volume.py --compare-poses "AOM/output/cup" "AOM/output/cup/revisions/BASE_REV" "AOM/output/cup/revisions/SLICE_REV" --pitch 1.0 --pose-baseline rim --output-dir "cup_PoseComparison"
```

- AOMのマニフェストで元モデルの同一性と座標単位を照合し、PLYとTransformのファイルサイズ・SHA-256を検証します。座標単位はAOM出力から取得し、正規化済みPLYをそのまま計算します。補完したモデルを使う場合は、補完後の**同じモデル**をAOMに入力して各姿勢を書き出してください。
- 比較に使うのは共通の単一ピッチです。`--pitch` の既定値は1.0 mmです。従来の `--validate` は1姿勢に対するピッチ収束の検証で、姿勢比較とは別に実行します。
- Sliceの **採用** は通常の比較に含めます。**参考** は `--include-reference-slice` を付けた場合に試算し、比較表で参考と区別します。**保留**、またはSlice判定が記録されていない旧出力はスキップします。Sliceを保留した後にRimやBaseを書き出した場合は、その出力に記録された保留理由も一覧に反映します。
- 基準姿勢は `--pose-baseline rim|base|slice` で指定します。省略時は、計算に成功した Rim、Base、採用Sliceの順です。角度差は元の座標系での上方向の差です。容量差は「対象の容量 − 基準の容量」、百分率の分母は基準の容量です。
- 新規の出力フォルダに `pose_comparison.json` と `pose_comparison.csv` を保存し、各姿勢の詳細を `rim/`、`base/`、`slice/` に分けます。溢水位は正規化済みモデルのZ座標と、そのモデルの最下点からの高さを併記します。計算できた姿勢が2つ未満、または一部で計算が失敗した場合は、理由を一覧に保存してエラー終了します。


---

# 5. 入力単位

次を指定できます。

```text
mm
cm
m
```

例：

```bash
--unit m
```

単位は自動判定しません。

### 内部処理

内部ではmmへ統一します。

例えばm入力：

```text
input  : m
internal: mm
```

### 出力

m入力なら、

- processed mesh：m
- QC PLY：m
- safe/spill level：m
- 主容量：m³
- 併記：L / mL

となります。

---

# 6. single-pitchモード

## 1 mm

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --unit m \
  --pitch 1.0
```

## 2 mm

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --unit m \
  --pitch 2.0
```

## 0.5 mm

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --unit m \
  --pitch 0.5
```

`--pitch`は入力モデルの単位に関係なく**常にmm**です。

---

# 7. multi-pitch validationモード

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --unit m \
  --validate
```

自動的に、

```text
2.0 mm
1.0 mm
0.5 mm
```

の順に実行します。

実行中は、

```text
### Validation run 1/3 — pitch 2 mm
### Validation run 2/3 — pitch 1 mm
### Validation run 3/3 — pitch 0.5 mm
```

と表示します。

---

# 8. validation結果のまとめ

validationモードでは通常のpitch別結果に加えて、

```text
validation_summary.json
validation_summary.csv
```

を出力フォルダ直下に作成します。

例えば、

```text
pottery_PotteryVolume_v1/
├── validation_summary.json
├── validation_summary.csv
├── pitch_2mm/
├── pitch_1mm/
└── pitch_0p5mm/
```

となります。

---

# 9. validation_summary.csv

主な項目：

```text
status
pitch_mm
safe_level_mm
spill_level_mm
spill_fraction_of_mesh_height
volume_l
volume_ml
delta_from_coarser_l
delta_from_coarser_pct_of_current
total_time_s
result_json
error
```

例：

```text
pitch    volume
2.0 mm   5.802720 L
1.0 mm   5.917481 L
0.5 mm   5.947995 L
```

のような収束状況を1ファイルで比較できます。

---

# 10. validation_summary.jsonの収束診断

3条件すべてが成功すると、次の診断値も保存します。

## finest vs next coarser

0.5 mmと1.0 mmの差です。

```text
finest_vs_next_coarser_difference_l
finest_vs_next_coarser_difference_percent_of_finest
```

実用上、最も分かりやすい収束指標です。

## spill upper-level range

```text
spill_upper_range_mm
```

2 / 1 / 0.5 mm間でspill levelがどの程度変化したかを示します。

## volume monotonicity

```text
volume_monotonic_with_refinement
```

pitchを細かくしたとき、容量値が一方向に収束しているかを示します。

---

# 11. 経験的収束次数と外挿値

2 / 1 / 0.5 mmがすべて成功し、容量変化が同じ方向の場合には、

```text
empirical_order_q
richardson_extrapolated_volume_l
```

も計算します。

モデル：

```text
V(p) = V∞ + a p^q
```

を仮定した**診断値**です。

重要：

> `richardson_extrapolated_volume_l`は測定された容量値ではありません。

研究成果の主値としては、原則として実際に計算した0.5 mm等の値を使用し、外挿値は収束診断の補助情報として扱ってください。

---

# 12. validation中に一部pitchが失敗した場合

例えば2 mmは成功、1 mmは成功、0.5 mmがメモリ不足で失敗した場合でも、それまでの結果を失いません。

プログラムは可能な限り残りのpitchも実行し、

```text
validation_summary.json
validation_summary.csv
```

へ成功・失敗を記録します。

ただし、1条件でも失敗した場合は最終的なコマンド終了コードをエラーとします。

---

# 13. 出力フォルダ

入力：

```text
0015Jinmen_small.ply
```

なら、

```text
0015Jinmen_small_PotteryVolume_v1/
├── archaeological/
│   ├── after_exact_weld_boundary_stats.json
│   ├── after_exact_weld_components.csv
│   ├── after_exact_weld_components.json
│   └── after_exact_weld_components_colored.ply
├── processed/
│   └── 0015Jinmen_small_exact_welded.ply
├── qa/
│   ├── topology_before_exact_weld.json
│   ├── topology_after_exact_weld.json
│   ├── exact_weld_report.json
│   ├── pymeshlab_crosscheck.json
│   └── preprocessing_summary.json
├── pitch_2mm/
│   └── qa/preflight_scale_resource.json
├── pitch_1mm/
│   └── qa/preflight_scale_resource.json
└── pitch_0p5mm/
    └── qa/preflight_scale_resource.json
```

validationモードではさらに、

```text
validation_summary.csv
validation_summary.json
```

が加わります。

---

# 14. `archaeological/raw_*`について

v1.3.1以降では、**pre-weldの`archaeological/raw_*`は生成しません**。

検証用PLYでは、face-corner UVの不連続をTrimeshが処理すると、元の幾何学的境界ではないtexture seamがboundary edgeとして現れることが確認されました。これを接合境界と誤認しないため、raw boundary / raw component / raw-spill近接診断の出力を停止しています。

`archaeological/`に残すのはexact-coordinate weld後のtopology QA用情報だけです。これらも実破片を自動同定した結果ではありません。

接合境界抽出は、容量計算とは独立した`PotteryFragmentBoundaryExtractor`として別途検討します。

---

# 15. PyMeshLab

PyMeshLabは独立cross-checkです。

容量計算の必須依存ではありません。

環境診断：

```bash
python3 vessel_voxel_volume.py --diagnose-env
```

PyMeshLabを含む環境：

```bash
python3 -m pip install -r requirements.txt
```

PyMeshLabなし：

```bash
python3 -m pip install -r requirements-core.txt
```

でも容量計算できます。

---

# 16. PILエラー

```text
No module named 'PIL'
```

の場合は、

```bash
python3 -m pip install Pillow
```

です。

---

# 17. バージョン確認

```bash
python3 vessel_voxel_volume.py --version
```

```text
vessel_voxel_volume.py 1.3.0
```

を確認してください。

---

# 18. QC

各pitchフォルダ内：

```text
qc/
├── fluid_surface.ply
├── spill_level_region.ply
├── seed_point.ply
└── seed_candidates.ply
```

をCloudCompare等で元メッシュと重ねて確認します。

主に、

- fluid surfaceが器内に収まっている
- spillが口縁付近にある
- seedが内容空間にある

ことを確認してください。

---

# 19. 推奨ワークフロー

## 新しい資料・代表資料

最初に、

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --unit m \
  --validate
```

で2 / 1 / 0.5 mmの収束性を検証します。

ここで、

- spill levelが安定
- 1→0.5 mmの容量差が十分小さい
- QC PLYが正常

であることを確認します。

## 同種資料を大量処理

検証結果から実用pitchを決めます。

例えば1 mmで十分と判断したら、

```bash
python3 vessel_voxel_volume.py pottery.ply \
  --unit m \
  --pitch 1.0
```

を使用します。

次段階では、このsingle-pitch処理を**指定フォルダ内のPLYへ順次適用するバッチ処理**へ拡張する予定です。

---

# 20. 計算量とpreflight safety check

voxel pitchを半分にすると、3次元gridのセル数は概ね8倍になります。

```text
2 mm → 高速
1 mm → 標準
0.5 mm → 詳細検証
```

という使い分けを推奨します。

## 20.1 単位・計算量の事前検査

v1.3.2では、実際の`mesh.voxelized()`を開始する前に、指定された`--unit`でmmへ換算した外形寸法と`--pitch`から、dense voxel gridを事前推定します。

表示例：

```text
=== Preflight scale / voxel resource check ===
extents mm      : X=231.424, Y=229.222, Z=283.793
pitch           : 0.5 mm
estimated grid  : 472 x 468 x 577
estimated cells : 127,456,992
working memory  : ~972.42 MiB (preflight indicator)
```

`working memory`は厳密なpeak RAMではなく、複数のboolean arrayを用いる処理を想定した安全側の指標です。Trimesh / SciPyが追加配列を確保するため、実際のpeak RAMはこれを上回る場合があります。

### soft warning

次の場合は処理を継続しますがWARNINGを表示します。

- 指定単位で最大寸法が20 mm未満
- 指定単位で最大寸法が3,000 mm超
- 推定dense gridが200,000,000 cells以上

これは単位指定ミスや、非常に重い処理条件を早期に気づくための警告です。

### hard stop

次のいずれかに該当すると、**surface voxelizationを開始せずエラー終了**します。

- 最大寸法がpitchの4 voxel未満で、極端に低解像度
- 推定gridの1軸が50,000 cells超
- 推定grid総数が500,000,000 cells超

典型的には、実データがmmなのに`--unit m`と指定するとgridが爆発するためhard stopします。逆に、実データがmなのに`--unit mm`と指定した場合も、極端な低解像度としてhard stopします。

事前診断は各pitchの、

```text
pitch_Xmm/qa/preflight_scale_resource.json
```

にも保存されます。

---

# 21. 検証資料

- [ボクセル溢水法の開発・検証レポート v1.3.1（PDF）](docs/validation/PotteryVolumeCalculator_development_validation_report_v1.3.1.pdf) は、0015 Jinmenでのピッチ収束と溢水位を記録しています。
- v1.4.0の確認では、仮想土器でAOM姿勢別比較、Sliceの採否による分岐、ピッチ検証を実行しました。実資料0015 Jinmenでは、2 mmピッチで単一姿勢の計算を確認しました。
- [表面痕跡解析の自己検証記録](docs/validation/surface-trace-v0.1.0.md) は、関連ツールのPotterySurfaceTraceAnalyzerを対象としています。

---

# 22. 初めてCLIを使う場合のFAQ

## Q1. `python`と`python3`はどちらを使いますか？

このREADMEでは、原則として、

```bash
python3
```

を使用します。

環境によって`python`がPython 3を指す場合もありますが、別バージョンを指す可能性があるため、READMEの例では`python3`に統一しています。

---

## Q2. 毎回`pip install`する必要がありますか？

通常は必要ありません。

仮想環境`.venv`を一度作成し、その中へrequirementsをインストールすれば、次回以降は、

```bash
cd <PotteryVolumeCalculatorのフォルダ>
source .venv/bin/activate
```

としてからプログラムを実行します。

---

## Q3. `No module named ...`と表示されます

まず仮想環境が有効か確認してください。

ターミナルの行頭に、

```text
(.venv)
```

が表示されていなければ、

```bash
source .venv/bin/activate
```

を実行します。

その後、

```bash
python3 -m pip install -r requirements.txt
```

または、

```bash
python3 -m pip install -r requirements-core.txt
```

を実行してください。

`No module named 'PIL'`の場合、パッケージ名は`PIL`ではなく`Pillow`です。

---

## Q4. `No such file or directory`と表示されます

主に次を確認してください。

1. `pwd`で現在のワーキングディレクトリを確認する
2. `ls`で入力したファイル名が存在するか確認する
3. ファイル名の大文字・小文字を確認する
4. パスに空白がある場合は引用符で囲む

例：

```bash
python3 vessel_voxel_volume.py "sample data.ply" --unit m --pitch 1.0
```

---

## Q5. `can't open file 'vessel_voxel_volume.py'`と表示されます

`vessel_voxel_volume.py`があるフォルダをワーキングディレクトリにしていない可能性があります。

```bash
pwd
ls
```

で確認し、必要なら、

```bash
cd <PotteryVolumeCalculatorのフォルダ>
```

で移動してください。

---

## Q6. `.py`ファイルをダブルクリックしても動きません

このプログラムはターミナルから、

```bash
python3 vessel_voxel_volume.py ...
```

として実行します。

Finder上で`.py`ファイルをダブルクリックする必要はありません。

---

## Q7. `Permission denied`と表示されます

このREADMEの方法では、

```bash
./vessel_voxel_volume.py
```

ではなく、

```bash
python3 vessel_voxel_volume.py
```

として実行してください。

通常、`.py`ファイル自体へ実行権限を付ける必要はありません。

---

## Q8. PLYファイルはプログラムと同じフォルダに置く必要がありますか？

必須ではありません。

同じフォルダに置くと初心者には分かりやすいですが、別フォルダのファイルもパスを指定して処理できます。

```bash
python3 vessel_voxel_volume.py "/path/to/model.ply" --unit m --pitch 1.0
```

---

## Q9. 計算中に止めたい場合はどうしますか？

ターミナルで、

```text
Control + C
```

を押します。

計算途中の出力ファイルが残る場合があります。中断後に同じ条件で再実行する場合は、出力内容を確認してください。

---

## Q10. 0.5 mmで非常に時間がかかります

正常な場合があります。

voxel pitchを半分にすると、3次元gridのセル数は概ね8倍になります。そのため、

```text
2 mm   → 比較的高速
1 mm   → 標準
0.5 mm → 詳細検証・高負荷
```

という使い分けを想定しています。

大量資料を処理する場合は、代表資料を`--validate`で検証した上で、実用的な単一pitchを決めることを推奨します。

---

## Q11. `Killed`、メモリ不足、または極端に遅くなります

voxel gridが大きすぎる可能性があります。

まず、

```text
0.5 mm → 1.0 mm
```

または、

```text
1.0 mm → 2.0 mm
```

のようにpitchを大きくして確認してください。

他のメモリを大量に使用するアプリケーションを終了することも有効です。

---

## Q12. `--unit`には何を指定しますか？

PLY / OBJ内の**座標値が表している実際の長さ単位**を指定します。

例えば座標値`0.25`が25 cmを意味するモデルなら、

```bash
--unit m
```

です。

指定可能なのは、

```text
mm
cm
m
```

です。

単位を誤ると容量も大きく誤るため、必ず確認してください。

---

## Q13. なぜZ軸を上下方向にする必要がありますか？

このプログラムは、

```text
+Z = 上
-Z = 重力方向
```

として液面を上昇させ、spill levelを探索します。

土器が横倒しになっていると、「容量」の意味が変わってしまいます。計算前に3Dソフトで姿勢を確認してください。

---

## Q14. 計算が成功したら、その容量値をそのまま採用してよいですか？

研究用途では、計算完走だけでなくQCも確認してください。

少なくとも、

- `fluid_surface.ply`が器内に収まっている
- spill levelが妥当な位置にある
- seedが内容空間にある
- 必要に応じて2 / 1 / 0.5 mmで収束性を確認する

ことを推奨します。

詳細検証には、

```bash
--validate
```

を使用してください。

---

## Q15. ターミナルを閉じた後、次回は何をすればよいですか？

仮想環境をすでに作成済みなら、基本的には次の3段階です。

```bash
cd <PotteryVolumeCalculatorのフォルダ>
source .venv/bin/activate
python3 vessel_voxel_volume.py <model.ply> --unit m --pitch 1.0
```

requirementsの再インストールやvenvの再作成は通常不要です。

---

## Q16. コマンドを間違えたか分からなくなりました

利用可能なオプションは、

```bash
python3 vessel_voxel_volume.py --help
```

で確認できます。

環境を確認する場合は、

```bash
python3 vessel_voxel_volume.py --diagnose-env
```

を使用してください。

エラーについて相談する場合は、**エラーメッセージだけでなく、その直前からのターミナル出力も含めて**保存すると原因を特定しやすくなります。

