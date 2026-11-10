# リポジトリ構成と関連ツール / Repository guide

容量計算の導入と実行手順は [日本語README](../README.md) または [English README](../README_EN.md) を参照してください。以下のコマンド例はリポジトリのルートで実行します。

| スクリプト | 用途と資料 |
|---|---|
| [`vessel_voxel_volume.py`](../vessel_voxel_volume.py) | 3Dメッシュの溢水容量、ピッチ検証、[AOM姿勢別比較](../README.md#aom-pose-comparison) |
| [`pose_comparison.py`](../pose_comparison.py) | 容量計算CLIの姿勢比較を支える内部モジュール |
| [`pottery_radial_sections.py`](../pottery_radial_sections.py) | 3Dメッシュの放射断面と断面法容量。[v0.4.0の操作手順](radial-sections-v0.4.0.md) |
| [`pottery_drawing_capacity.py`](../pottery_drawing_capacity.py) | 2D図面から内面プロファイルを指定して容量を計算するGUI。[v0.5.0の操作手順](drawing-capacity-v0.5.0.md) |
| [`pottery_fragment_boundary.py`](../pottery_fragment_boundary.py) | 接合・破断境界の候補を調べるCLI |
| [表面痕跡解析（MorphPot）](https://github.com/kotdijian/MorphPot/blob/main/README.md#surface-trace) | 表面の多尺度形状解析は今後MorphPotで開発します。[従来のCLI](../pottery_surface_trace.py) と [v0.1.0の検証記録](validation/surface-trace-v0.1.0.md) は既存の手順を再現するために参照できます。 |

放射断面は断面法による容量計算に使うため、このリポジトリにも収録しています。放射断面の形態解析や容量計算を伴わない断面抽出には [MorphPotの放射断面ガイド](https://github.com/kotdijian/MorphPot/blob/main/README.md#radial-sections-guide) を参照してください。

関連ツールの引数は、たとえば `python3 pottery_radial_sections.py --help` で確認できます。図面GUIにはTkinterが必要です。SVG・PDFを開く場合はPyMuPDF、放射断面のPNG図版を生成する場合はMatplotlibを追加してください。

- [0015 Jinmenの入力メッシュ](../0015Jinmen_small.ply)と[放射断面の出力例](../examples/0015Jinmen_small_RadialSections_30deg)
- [ボクセル溢水法の開発・検証レポート v1.3.1](validation/PotteryVolumeCalculator_development_validation_report_v1.3.1.md) / [図版付きPDF](validation/PotteryVolumeCalculator_development_validation_report_v1.3.1.pdf)
- [過去のv0.6.0断面・図面ワークフロー（英語）](archive/section-workflows-v0.6.0.md)
