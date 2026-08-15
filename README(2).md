# 土器メッシュの内容積をボクセル法で計測する Python スクリプト

`vessel_voxel_volume.py` は、OBJ / PLY 形式の土器3Dメッシュから、**土器の内面を手作業で抽出せずに内容積（容量）を推定する**ための実験用 Python スクリプトです。

Pythonを初めて使う人でも試せるように、このREADMEではインストールから実行、結果の確認まで順番に説明します。

---

## 1. このプログラムでできること

土器全体のメッシュを1 mmなどの小さな立方体（voxel / ボクセル）に変換し、口を仮想的に閉じたうえで、土器内部に閉じ込められた空間の大きさを数えます。

処理の概略は次のとおりです。

```text
OBJ / PLY メッシュ
        ↓
メッシュ全体をボクセル化
        ↓
口縁付近を自動検出
        ↓
口を仮想的に閉じる
        ↓
土器内部の空間を抽出
        ↓
内部ボクセル数 × ボクセル体積
        ↓
内容積を mL / L で出力
```

**内面メッシュだけを別に作る必要はありません。**

---

## 2. 現在の実験対象

このバージョンは、まず単純な土器で方法を検証するためのものです。

### 適している土器

- 口縁に大きな突起がない
- 把手・注口などがない
- 口縁が大きく波打っていない
- 内面形状が滑らか
- 大きな欠損がない
- 土器全体の内面・外面を含むメッシュがある
- 土器をほぼ直立させられる

### 現段階では適していないもの

- 波状口縁
- 大きな突起・把手・注口のある土器
- 大きく欠損した土器
- 内部に複雑な突起や仕切りがある器
- メッシュに多数の穴があるデータ

これらへの対応は今後の拡張課題です。

---

## 3. 入力データの条件

### ファイル形式

次のどちらかを使用できます。

- `PLY`
- `OBJ`

計測用には **PLYを推奨**します。

テクスチャは容量計算には使用しません。

### 単位

**座標単位を mm（ミリメートル）にしてください。**

たとえば高さ30 cmの土器なら、メッシュの高さが約 `300` になる状態です。

高さが `0.30` になっている場合は、単位がメートルの可能性があります。そのまま実行しないでください。

### 姿勢

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

口縁が上、底部が下になるようにします。

---

## 4. CloudCompareで事前確認する場合

CloudCompareを使う場合は、実行前に次の3点を確認してください。

1. 土器がZ軸方向に直立している
2. メッシュの大きさがmm単位になっている
3. 大きな穴や欠損がない

必要ならCloudCompareで回転・移動してから、PLYとして書き出します。

**内面だけを選択・抽出する必要はありません。**

---

# 5. Pythonをインストールする

このスクリプトは **Python 3.10以上**を必要とします。

すでにPythonが入っている場合は、まずバージョンを確認してください。

## macOS

「ターミナル」を開き、次を入力します。

```bash
python3 --version
```

たとえば、

```text
Python 3.12.4
```

のように表示されれば使用できます。

`Python 3.10` 以上であれば構いません。

Pythonが入っていない場合は、Python公式サイトなどからPython 3をインストールしてください。

## Windows

「PowerShell」または「コマンドプロンプト」を開き、

```powershell
py --version
```

と入力します。

---

# 6. GitHubからプログラムを取得する

Pythonを初めて使う場合は、Gitを使う必要はありません。

GitHubのリポジトリ画面で、

**Code → Download ZIP**

を選びます。

ダウンロードしたZIPを展開してください。

展開したフォルダの中に、少なくとも次のファイルがあることを確認します。

```text
repository/
├── README.md
└── vessel_voxel_volume.py
```

---

# 7. 作業フォルダをターミナルで開く

## macOS：簡単な方法

Finderでリポジトリのフォルダを確認します。

ターミナルで、

```bash
cd 
```

と入力したあと、**半角スペースを残したまま**Finderからフォルダをターミナルへドラッグ＆ドロップします。

その後 Enter を押します。

例：

```bash
cd /Users/username/Downloads/vessel-voxel-volume
```

現在のフォルダの内容は、

```bash
ls
```

で確認できます。

`vessel_voxel_volume.py` が表示されれば正しいフォルダです。

## Windows

エクスプローラーでリポジトリのフォルダを開き、アドレスバーに

```text
powershell
```

と入力してEnterを押す方法が簡単です。

---

# 8. Pythonの仮想環境を作る（推奨）

Pythonのライブラリをこの実験専用に分けておくため、仮想環境を作ることを推奨します。

難しく見えますが、最初に1回コマンドを実行するだけです。

## macOS

```bash
python3 -m venv .venv
```

続けて、

```bash
source .venv/bin/activate
```

を実行します。

ターミナルの行頭に、

```text
(.venv)
```

が表示されれば成功です。

## Windows

```powershell
py -m venv .venv
```

続けて、

```powershell
.venv\Scripts\Activate.ps1
```

を実行します。

---

# 9. 必要なライブラリをインストールする

このスクリプトでは次の3つを使用します。

- NumPy
- SciPy
- Trimesh

## macOS

```bash
python3 -m pip install numpy scipy trimesh
```

## Windows

```powershell
py -m pip install numpy scipy trimesh
```

エラーが表示されずインストールが終了すれば準備完了です。

---

# 10. 土器ファイルを作業フォルダに置く

最初の実験では、土器メッシュをPythonスクリプトと同じフォルダに置くと簡単です。

例：

```text
repository/
├── README.md
├── vessel_voxel_volume.py
└── pottery01.ply
```

ファイル名には、最初は日本語や空白を使わず、

```text
pottery01.ply
```

のような単純な名前を推奨します。

---

# 11. まず1 mmボクセルで実行する

## macOS

```bash
python3 vessel_voxel_volume.py pottery01.ply --pitch 1.0
```

## Windows

```powershell
py vessel_voxel_volume.py pottery01.ply --pitch 1.0
```

OBJの場合は、

```bash
python3 vessel_voxel_volume.py pottery01.obj --pitch 1.0
```

とします。

---

# 12. 正常に終了すると表示される情報

処理中に、おおむね次のような情報が表示されます。

```text
=== Input mesh ===
file       : pottery01.ply
vertices   : ...
faces      : ...
watertight : ...
extents mm : X=..., Y=..., Z=...

=== Surface voxelization ===
pitch      : 1.000 mm
...

=== Rim / cap ===
cap Z      : ... mm

=== 3D cavity flood fill ===
...

=== Result ===
cavity voxels : ...
volume        : ... mm^3
volume        : ... mL
volume        : ... L
```

もっとも重要なのは、

```text
volume : XXXX.XXX mL
```

です。

---

# 13. 出力ファイル

たとえば `pottery01.ply` を1 mmで処理すると、次のようなファイルが作られます。

```text
pottery01_voxel_1mm_result.json
pottery01_voxel_1mm_cavity_surface.ply
pottery01_voxel_1mm_cap.ply
```

## `*_result.json`

計測結果を記録したテキスト形式のファイルです。

内容積だけでなく、

- 使用したvoxelサイズ
- メッシュの頂点数
- face数
- メッシュ寸法
- 自動検出されたcapの高さ
- 計算時間

なども記録されます。

研究データとして結果を保存するときは、このJSONも残してください。

## `*_cavity_surface.ply`

プログラムが**土器内部の空間**だと判断した領域を、CloudCompareで確認するためのPLYです。

## `*_cap.ply`

プログラムが口を閉じるために作成した**仮想的な蓋**です。

---

# 14. CloudCompareで結果を必ず確認する

数値だけを採用せず、最初の実験では必ず結果を3D表示して確認してください。

CloudCompareに、

1. 元の土器メッシュ
2. `*_cavity_surface.ply`
3. `*_cap.ply`

を読み込みます。

確認するポイントは次のとおりです。

### cavity

`cavity_surface.ply` が、

- 土器の内部だけに存在している
- 器壁の外へ漏れていない
- 底から口まで連続している

ことを確認します。

### cap

`cap.ply` が、

- 口縁付近にある
- 土器の口をおおむね正しく塞いでいる
- 胴部など誤った場所に作られていない

ことを確認します。

**数値が表示されたことだけをもって計測成功とはしないでください。**

---

# 15. 0.5 mm・1 mm・2 mmを比較する

ボクセル法では、ボクセルの大きさによって結果が少し変わります。

そのため、研究目的で使用する場合は少なくとも、

- 2.0 mm
- 1.0 mm
- 0.5 mm

の3条件を比較することを推奨します。

## 2 mm

```bash
python3 vessel_voxel_volume.py pottery01.ply --pitch 2.0
```

## 1 mm

```bash
python3 vessel_voxel_volume.py pottery01.ply --pitch 1.0
```

## 0.5 mm

```bash
python3 vessel_voxel_volume.py pottery01.ply --pitch 0.5
```

例えば、

| voxel size | 内容積 |
|---:|---:|
| 2.0 mm | 5,420 mL |
| 1.0 mm | 5,470 mL |
| 0.5 mm | 5,492 mL |

のように値が一定値へ近づいていけば、計測が安定していると判断できます。

---

# 16. なぜ複数のボクセルサイズで測るのか

3Dメッシュの表面そのものには厚さがありません。

しかしボクセルに変換すると、

```text
実際の表面
────────────

ボクセル化
████████████
```

のように、1 mmなどの厚さを持つ境界として扱われます。

そのため、内部空間は実際よりわずかに小さく計測される傾向があります。

一般にボクセルを細かくすると、この影響は小さくなります。

したがって、本スクリプトでは**1 mmという値だけを絶対的な真値として扱うのではなく、複数解像度の結果を比較する**ことを推奨します。

---

# 17. 口縁の自動検出に失敗した場合

通常は口縁位置を自動検出します。

うまくいかない場合は、CloudCompareなどで口縁のZ座標を確認して、手動指定できます。

たとえば口縁がおよそ `287.5 mm` の高さなら、

```bash
python3 vessel_voxel_volume.py pottery01.ply --pitch 1.0 --cap-z 287.5
```

とします。

---

# 18. よくあるエラー

## `python3: command not found`

Pythonがインストールされていないか、コマンドが認識されていません。

まず、

```bash
python3 --version
```

を確認してください。

Windowsでは、

```powershell
py --version
```

を使用します。

---

## `ModuleNotFoundError`

例：

```text
ModuleNotFoundError: No module named 'trimesh'
```

必要なライブラリがインストールされていません。

```bash
python3 -m pip install numpy scipy trimesh
```

を実行してください。

---

## `No such file or directory`

指定したPLY / OBJが現在のフォルダにない可能性があります。

macOSでは、

```bash
ls
```

でファイル一覧を確認してください。

ファイル名の綴りも確認します。

---

## `口部を自動検出できませんでした`

主な原因は、

- 土器がZ軸に直立していない
- 口縁付近のメッシュが欠損している
- 単位がmmではない
- 口縁形状が現在の自動検出条件より複雑

などです。

まずCloudCompareで形状と姿勢を確認してください。

必要なら `--cap-z` を使用します。

---

## `内部領域が grid 外周まで漏れました`

内部空間が土器の外側へつながってしまったことを意味します。

考えられる原因は、

- メッシュに穴がある
- voxelサイズが粗すぎる
- capが正しく作られていない
- 土器の姿勢が適切でない

などです。

この場合、プログラムは誤った巨大な容量値を出力せず停止します。

まずメッシュを確認してください。

---

# 19. 主なオプション

通常は `--pitch` だけで実行できます。

```text
--pitch
```

ボクセルの1辺の長さをmmで指定します。

既定値：

```text
1.0 mm
```

例：

```bash
python3 vessel_voxel_volume.py pottery01.ply --pitch 0.5
```

---

```text
--cap-z
```

仮想capのZ座標を手動指定します。

例：

```bash
python3 vessel_voxel_volume.py pottery01.ply --cap-z 287.5
```

---

```text
--no-qc
```

CloudCompare確認用PLYを出力しません。

通常は指定しないことを推奨します。

---

その他の詳細オプションは、

```bash
python3 vessel_voxel_volume.py --help
```

で確認できます。

---

# 20. 最初の実験に推奨する手順

初めて試す場合は、次の順番を推奨します。

1. 比較的単純で完形に近い土器を1個体選ぶ
2. CloudCompareでZ軸方向に直立させる
3. 単位がmmであることを確認する
4. PLYとして保存する
5. `--pitch 1.0` で実行する
6. `cavity_surface.ply` と `cap.ply` をCloudCompareで確認する
7. 問題がなければ `--pitch 2.0` と `--pitch 0.5` でも実行する
8. 3条件の内容積を比較する

最初から大量の土器を一括処理するのではなく、**まず1個体で計算結果と3D形状が妥当か確認してください。**

---

# 21. 研究上の注意

このプログラムは現在、**ボクセル法による土器内容積計測の実験・検証用**です。

特に次の点に注意してください。

- ボクセルサイズによる離散化誤差があります
- 自動生成されたcap位置によって容量が変わる可能性があります
- メッシュの欠損は内部領域抽出に大きく影響します
- `watertight : False` と表示されても処理できる場合がありますが、QCが重要です
- 1 mmの結果だけでなく0.5 / 1 / 2 mmなど複数解像度を比較してください
- 測定値を研究成果として使用する前に、既知容量の容器や単純な幾何形状で精度検証することを推奨します

---

# 22. 使用しているPythonライブラリ

このスクリプトでは主に次を利用しています。

- **NumPy**：数値・3次元配列処理
- **SciPy**：2D / 3D画像処理、Flood Fill相当の処理
- **Trimesh**：OBJ / PLY読み込みとvoxelization

---

# 23. ファイル構成例

```text
vessel-voxel-volume/
├── README.md
├── vessel_voxel_volume.py
├── pottery01.ply
├── pottery01_voxel_1mm_result.json
├── pottery01_voxel_1mm_cavity_surface.ply
└── pottery01_voxel_1mm_cap.ply
```

---

# 24. 開発段階

現在は、単純な土器を対象とした初期実験版です。

今後の検討項目として、たとえば次があります。

- 口縁検出の改善
- 波状口縁への対応
- 複数解像度計算の自動化
- voxel size → 0 への外挿
- CSVによる複数個体の一括処理
- 既知容量・閉メッシュ法との比較検証
- GUI化

---

## 最短の実行例

macOSで、Pythonがすでにインストール済みなら、リポジトリのフォルダで次を順番に実行します。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install numpy scipy trimesh
python3 vessel_voxel_volume.py pottery01.ply --pitch 1.0
```

結果が出たら、CloudCompareで

```text
pottery01.ply
pottery01_voxel_1mm_cavity_surface.ply
pottery01_voxel_1mm_cap.ply
```

の3つを重ねて確認してください。
