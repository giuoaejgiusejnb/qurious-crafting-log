"""練成画像のフォルダを読み取り、1つの取込バッチ（取込元 8bit）としてDBに保存する。

アプリでは、ラベルが確定していない見本（新しいスキル名・数字の形など）があれば
ユーザーに正しいラベルを入力してもらってから結果を作るため、次の2段階で呼ぶ。
  1. start_image_reading   : 画像を切り出して見本と照合する（session.pending_labels() が入力待ち）
  2. finish_image_import   : 入力されたラベルを付けて結果を作り、DBに保存する
"""

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.importer import SOURCE_8BIT, ImportSummary, import_block
from app.ocr.kuijin_ocr import OcrRun, OcrSession, finish_reading, list_images, start_reading, user_template_dir

# 画像読み取り（phase="ocr"）と DB 保存（phase="import"）の進捗を (phase, 済み, 全体) で渡す
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

    見本（テンプレート）は data_dir/ocr_templates を使う（初回は同梱の見本を複製する）。
    この段階では見本を保存しないので、ここで止めても何も残らない。
    """
    paths = list_images([image_dir])
    if not paths:
        raise NoImagesError(f"{image_dir} に画像（*.jpg）がありません")
    return start_reading(
        paths,
        base_slot,
        zenny_step,
        minus_skills,
        template_dir=user_template_dir(data_dir),
        use_processes=can_use_processes(),
        progress_callback=(lambda d, t: progress_callback("ocr", d, t)) if progress_callback else None,
        table=table,
    )


def finish_image_import(
    conn: sqlite3.Connection,
    session: OcrSession,
    label: str | None,
    labels: dict[tuple[str, int], str] | None = None,
    progress_callback: PhaseProgressCallback | None = None,
) -> ImageImportResult:
    """labels（{(見本の名前, 番号): ラベル}）を見本に付けて保存し、読み取り結果を取込形式にして import_block で保存する。

    ラベルを付けなかった見本は "?" のまま（その行は「読み込みできなかった行」になる）。
    読み取りの自己チェックで見つかった矛盾は kind='ocr'、抽選の仕様で作れない結果は kind='spec' として、
    バッチのエラーに保存する。
    """
    if labels:
        session.apply_labels(labels)
    run = finish_reading(session)
    summary = import_block(
        conn,
        run.report.text,
        label,
        progress_callback=(lambda d, t: progress_callback("import", d, t)) if progress_callback else None,
        source=SOURCE_8BIT,
        ocr_issues=run.report.errors,
        spec_issues=run.report.spec_errors,
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
