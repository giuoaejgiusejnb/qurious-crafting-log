"""分析スクリプトの共通設定。リポジトリの場所と作業フォルダ（データの置き場所）。

作業フォルダは環境変数 SYNC_ANALYSIS_DIR で変えられる。既定は隣の mhrise-skill-ocr の samples/sync_analysis。
読み込むと作業フォルダに移動する（中間ファイル *.pkl はここに書く）。手順は docs/crafting_sync.md。
"""
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.environ.get("SYNC_ANALYSIS_DIR") or os.path.join(
    os.path.dirname(REPO), "mhrise-skill-ocr", "samples", "sync_analysis")

if REPO not in sys.path:
    sys.path.insert(0, REPO)
os.makedirs(DATA, exist_ok=True)
os.chdir(DATA)
