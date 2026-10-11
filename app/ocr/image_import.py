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
from app.ocr.kuijin_ocr import (
    BUNDLED_TEMPLATE_DIR,
    OcrRun,
    OcrSession,
    finish_reading,
    list_images,
    save_templates,
    start_reading,
)

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


# 確認が必要な画像がこれより多いバッチは、取り込まない（枚数と、結果画面に対する割合の両方を超えたとき）。
# 入力の違い（防具・初期スロット・元から持つスキル・抽選テーブル・1回のゼニー）、対応していない撮り方、
# ゲームや Switch の表示の変化などで、ほとんどの画像が確認が必要になる。どれが原因かはアプリには分からないが、
# どの場合も、取り込んだ記録は当てにならない。普通のバッチでは 1% に届かない（別のユーザーの初めてのバッチで 0.4%）
REVIEW_STOP_COUNT = 20
REVIEW_STOP_SHARE = 0.05


def too_many_to_review(review: int, total: int) -> bool:
    """確認が必要な画像が review 枚、結果画面が total 枚のとき、取込をやめるか。"""
    return review >= REVIEW_STOP_COUNT and review > total * REVIEW_STOP_SHARE


class TooManyReviewError(Exception):
    """確認が必要な画像が多すぎる。取込は行わない（DB にも見本にも何も保存しない）。"""

    def __init__(self, review: int, total: int) -> None:
        self.review, self.total = review, total
        super().__init__(f"確認が必要な画像が多すぎるため、取込を中止しました（結果画面 {total}枚 のうち {review}枚）")


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

    確認が必要な行（読めない値 "?" がある・その画像だけで分かる矛盾がある・抽選の仕様で作れない。Report.review）は
    取り込まず、画像のパスを kind='unread' として保存する（履歴タブで画像を見てもらう）。
    1 枚の画像の問題ではない矛盾（ゼニーの減り方など。Report.batch_errors）は、kind='ocr' としてバッチのエラーに保存する。
    確認が必要な行が多すぎるときは、何も保存せずに TooManyReviewError にする。
    """
    if labels:
        session.apply_labels(labels)
    if progress_callback:
        progress_callback("report", 0, 0)
    run = finish_reading(session, save=False)
    review, total = run.report.review, run.report.line_count
    if too_many_to_review(len(review), total):
        raise TooManyReviewError(len(review), total)
    save_templates(session)
    by_name = {Path(path).name: str(Path(path).resolve()) for path in session.paths}
    summary = import_block(
        conn,
        run.report.import_text,
        label,
        progress_callback=(lambda d, t: progress_callback("import", d, t)) if progress_callback else None,
        source=SOURCE_8BIT,
        ocr_issues=run.report.batch_errors,
        review_images=[(count, zeny, by_name[name], reason) for _, count, zeny, name, reason in review],
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
