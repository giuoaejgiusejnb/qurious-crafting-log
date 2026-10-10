"""練成画像のフォルダを読み取り、1つの取込バッチ（取込元 8bit）としてDBに保存する。

読み取りは同梱の見本だけで行う。読めない値のある行は取り込まず、画像を見てもらう（履歴タブ）。
同梱の見本が無い初期スロットの防具では、スロット欄の見本のラベルをユーザーに入力してもらってから
結果を作るため、次の2段階で呼ぶ。
  1. start_image_reading   : 画像を切り出して見本と照合する（session.pending_labels() が入力待ち）
  2. finish_image_import   : 入力されたラベルを付けて結果を作り、DBに保存する
"""

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.importer import SOURCE_8BIT, ImportSummary, import_block
from app.ocr.kuijin_ocr import BUNDLED_TEMPLATE_DIR, OcrRun, OcrSession, finish_reading, list_images, start_reading

# 進捗を (段階, 済み, 全体) で渡す。段階は "extract"（画像の切り出し）・"match"（見本との照合）・
# "report"（結果の作成。済み・全体は 0）・"import"（DB への保存）
PhaseProgressCallback = Callable[[str, int, int], None]


@dataclass
class ImageImportResult:
    image_count: int
    run: OcrRun
    summary: ImportSummary


class NoImagesError(Exception):
    pass


def can_use_processes() -> bool:
    """画像の切り出しを別プロセスで並列に行えるか。

    ソースから起動（python.exe）していればプロセスを使う。exe 化したアプリでは
    子プロセスとしてアプリ本体が起動してしまうおそれがあるため、スレッドで行う（約 2 倍遅い）。
    """
    return Path(sys.executable).stem.lower().startswith("python")


def start_image_reading(
    image_dir: Path,
    data_dir: Path,
    base_slot: int,
    zenny_step: int,
    minus_skills: dict[str, int] | None,
    progress_callback: PhaseProgressCallback | None = None,
    table: int | None = None,
) -> OcrSession:
    """image_dir の *.jpg を撮影順に切り出し、見本と照合する。

    見本（テンプレート）は同梱のものだけを使う。読めない値のある行は取り込まず、画像を見てもらう。
    同梱の見本が無い初期スロットのスロット欄だけは、ラベルを選んでもらって data_dir/ocr_templates に保存する
    （OcrSession.bank）。この段階では見本を保存しないので、ここで止めても何も残らない。
    """
    paths = list_images([image_dir])
    if not paths:
        raise NoImagesError(f"{image_dir} の直下に画像（*.jpg）がありません（サブフォルダの中は読み取りません）")
    return start_reading(
        paths,
        base_slot,
        zenny_step,
        minus_skills,
        template_dir=BUNDLED_TEMPLATE_DIR,
        use_processes=can_use_processes(),
        progress_callback=progress_callback,
        table=table,
        label_dir=data_dir / "ocr_templates",
    )


def finish_image_import(
    conn: sqlite3.Connection,
    session: OcrSession,
    label: str | None,
    labels: dict[tuple[str, int], str] | None = None,
    progress_callback: PhaseProgressCallback | None = None,
) -> ImageImportResult:
    """labels（{(見本の名前, 番号): ラベル}）を見本に付けて保存し、読み取り結果を取込形式にして import_block で保存する。

    読めない値（"?"）のある行は取り込まず、画像のパスを kind='unread' として保存する（履歴タブで画像を見てもらう）。
    読み取りの自己チェックで見つかった矛盾は kind='ocr'、抽選の仕様で作れない結果は kind='spec' として、
    バッチのエラーに保存する。
    """
    if labels:
        session.apply_labels(labels)
    if progress_callback:
        progress_callback("report", 0, 0)
    run = finish_reading(session)
    by_name = {Path(path).name: path for path in session.paths}
    summary = import_block(
        conn,
        run.report.text,
        label,
        progress_callback=(lambda d, t: progress_callback("import", d, t)) if progress_callback else None,
        source=SOURCE_8BIT,
        ocr_issues=run.report.errors,
        spec_issues=run.report.spec_errors,
        unread_images={line: (by_name[name], zeny) for line, _, zeny, name in run.report.unread},
        image_dir=str(Path(session.paths[0]).resolve().parent) if session.paths else None,
    )
    return ImageImportResult(len(session.paths), run, summary)


def import_image_folder(
    conn: sqlite3.Connection,
    image_dir: Path,
    data_dir: Path,
    base_slot: int,
    zenny_step: int,
    minus_skills: dict[str, int] | None,
    label: str | None,
    progress_callback: PhaseProgressCallback | None = None,
    table: int | None = None,
) -> ImageImportResult:
    """ラベル入力を挟まずに読み取りから保存までを行う（ラベルが確定していない見本は "?" のまま）。"""
    session = start_image_reading(image_dir, data_dir, base_slot, zenny_step, minus_skills, progress_callback,
                                  table)
    return finish_image_import(conn, session, label, None, progress_callback)
