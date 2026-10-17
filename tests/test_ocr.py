from pathlib import Path

import pytest

from app.core.parser import parse_result_log_block
from app.ocr.kuijin_ocr import BUNDLED_TEMPLATE_DIR, build_report, parse_minus_skills


def test_parse_minus_skills():
    assert parse_minus_skills("攻撃:2,火事場力:3") == {"攻撃": 2, "火事場力": 3}
    assert parse_minus_skills(" 攻撃:2， 火事場力:3 ") == {"攻撃": 2, "火事場力": 3}
    assert parse_minus_skills("") is None
    with pytest.raises(ValueError):
        parse_minus_skills("攻撃")


def _copy_templates(dst: Path) -> Path:
    """同梱の見本を dst に複製して返す（見本を書き換える・保存するテスト用。確認用の拡大画像は除く）。"""
    import shutil

    shutil.copytree(BUNDLED_TEMPLATE_DIR, dst, ignore=shutil.ignore_patterns("review"))
    return dst


def _values(money_k: str, skill1: str = "攻撃", lv1: str = "+1") -> dict:
    return {
        "defense": "+4", "slot_base": "3", "slot_add": "+1",
        "fire": "-", "water": "+2", "thunder": "-", "ice": "-1", "dragon": "-",
        "skill1": skill1, "lv1": lv1, "skill2": "", "lv2": "", "skill3": "", "lv3": "",
        "cost": "21", "money_k": money_k,
    }


def _record(name: str, values: dict, screen: str = "screen1"):
    return (name, {"screen": screen, "features": {}}, values)


def test_build_report_is_importable(tmp_path):
    """読み取り結果のテキストが、そのまま取込形式としてパースできる。"""
    records = [
        _record("a.jpg", _values("100")),
        _record("b.jpg", _values("96", "見切り", "+1")),
        _record("c.jpg", _values("92"), screen="screen2"),   # 4 つ目以降が写っていない
    ]
    report = build_report(records, 4, tmp_path)

    lines = report.text.splitlines()
    assert lines[0] == "初期ゼニー,104"
    results, errors = parse_result_log_block(report.text)
    assert [(r.zeny_count, r.zeny, r.slot_add, r.total_cost, r.print_resistance) for r in results] == [
        (1, 100, 1, 21, 1),
        (2, 96, 1, 21, 1),
        (3, 92, 1, 21, 1),
    ]
    assert [s.name for s in results[1].skills] == ["見切り"]
    # 結果画面２は、写っていない4つ目以降のスキルを値0の「不明」として持つ
    assert [(s.name, s.value) for s in results[2].skills] == [("攻撃", 1), ("不明", 0)]
    assert errors == []
    assert report.errors == []


def test_build_report_reports_missing_shots(tmp_path):
    records = [_record("a.jpg", _values("100")), _record("b.jpg", _values("88"))]
    report = build_report(records, 4, tmp_path)
    assert any("2回分の画像がありません" in e for e in report.errors)


def test_rows_needing_review_are_not_imported(tmp_path):
    """確認が必要な行は取り込まず、何回目の練成か・ゼニー・画像のパスを残す（履歴タブで画像を見てもらう）。

    確認が必要な行: 読めない値（"?"）がある行と、その画像だけで分かる矛盾のある行。
    """
    from app.core.history import fetch_batch_errors, list_batches
    from app.core.importer import SOURCE_8BIT, import_block
    from app.db.connection import get_connection

    unreadable = _values("92")
    unreadable.update({"water": "+?", "cost": "?"})
    doubtful = _values("88")
    doubtful["fire"] = "+30"   # 耐性の増減としてありえない値（読み間違いの疑い）
    lost = _values("?")        # 所持ゼニーが読めないと、何回目か分からない
    report = build_report([_record("a.jpg", _values("100")), _record("b.jpg", _values("96")), _record("c.jpg", unreadable),
                           _record("d.jpg", doubtful), _record("e.jpg", _values("84")), _record("f.jpg", lost)], 4, tmp_path)
    assert [(line, count, zeny, name) for line, count, zeny, name, _, _ in report.review] == [
        (5, 3, 92, "c.jpg"), (6, 4, 88, "d.jpg"), (8, None, None, "f.jpg")]
    assert "読み取れない値" in report.review[0][4] and "ありえる範囲" in report.review[1][4]
    assert report.text.count("\n") == 8 and report.import_text.count("\n") == 5   # 取り込むのは 3 行だけ
    assert any("d.jpg" in e and "ありえる範囲" in e for e in report.errors)   # CLI 用の一覧には今までどおり出る
    assert report.batch_errors == []

    conn = get_connection(tmp_path / "test.db")
    summary = import_block(conn, report.import_text, "ギルパレ脚", source=SOURCE_8BIT, ocr_issues=report.batch_errors,
                           review_images=[(count, zeny, f"D:/shots/{name}", reason, exact)
                                          for _, count, zeny, name, reason, exact in report.review])
    assert (summary.imported_count, summary.unread_count, summary.errors, summary.skipped_results) == (3, 3, [], [])
    errors = fetch_batch_errors(conn, summary.batch_id)
    assert errors.unread == [(3, 92, "D:/shots/c.jpg", None), (4, 88, "D:/shots/d.jpg", None),
                             (None, None, "D:/shots/f.jpg", None)]
    assert errors.unparsable == [] and errors.skipped == [] and errors.ocr == []
    assert errors.total == list_batches(conn)[0].error_count == summary.error_count == 3
    conn.close()


def test_too_many_images_needing_review_stops_the_import():
    """確認が必要な画像が多すぎるバッチは、取り込まない（入力の違い・対応していない表示などの疑い）。"""
    from app.ocr.image_import import too_many_to_review as stops

    assert not stops(31, 7406)     # 別のユーザーの初めてのバッチ（0.4%）
    assert not stops(5, 9)         # 枚数の少ないフォルダで数枚出ただけでは止めない
    assert stops(780, 7507)        # 対応していない撮り方（10%）
    assert stops(40, 100)


def test_missing_shots_are_counted_once(tmp_path):
    """結果画面を撮れていない回は「飛ばされている練成」として 1 回だけ数え、前後の画像を添える。

    同じことが画像読み取りの矛盾（kind='ocr'）にも保存されるので、そちらは数えない（保存済みの古いバッチも同じ）。
    """
    from app.core.history import fetch_batch_errors, is_missing_shot_issue, list_batches
    from app.core.importer import SOURCE_8BIT, import_block
    from app.db.connection import get_connection

    records = [_record("a.jpg", _values("100")), _record("b.jpg", _values("88")), _record("c.jpg", _values("84"))]
    report = build_report(records, 4, tmp_path)
    gaps = [e for e in report.errors if is_missing_shot_issue(e)]
    assert gaps == ["2回分の画像がありません（撮り忘れの疑い）: a.jpg（100千ゼニー）→ b.jpg（88千ゼニー）"]

    conn = get_connection(tmp_path / "test.db")
    other = "所持ゼニーが増えています（別の記録の画像が混ざっているか、読み間違いの疑い）: x.jpg（1千ゼニー）→ y.jpg（2千ゼニー）"
    summary = import_block(conn, report.text, "ギルパレ脚", source=SOURCE_8BIT, ocr_issues=[*report.errors, other],
                           image_dir="D:/shots")
    assert summary.skipped_results == [(2, 96), (3, 92)] and summary.error_count == 3   # 欠番 2 + ほかの矛盾 1
    errors = fetch_batch_errors(conn, summary.batch_id)
    assert errors.skipped == [(2, 96), (3, 92)] and errors.ocr == [other]
    assert errors.skipped_between == {2: ("a.jpg", "b.jpg"), 3: ("a.jpg", "b.jpg")}
    assert errors.image_dir == "D:/shots"   # 前後の画像の場所を開くのに使う
    assert errors.total == list_batches(conn)[0].error_count == 3
    conn.close()


def test_drop_detached_removes_sparks_away_from_the_value():
    """右寄せの数値の欄で、値の文字から離れた成分（耐性「+4」の火花など）を消す。"""
    import numpy as np

    from app.ocr.kuijin_ocr import VALUE_H, VALUE_W, drop_detached

    def ink(*boxes: tuple[int, int, int, int]) -> np.ndarray:
        out = np.zeros((VALUE_H, VALUE_W), dtype=bool)
        for x, y, w, h in boxes:
            out[y:y + h, x:x + w] = True
        return out

    minus, spark = (61, 10, 5, 2), (22, 4, 5, 7)   # 灰色の "-"（右端）と、左に離れた火花
    assert (drop_detached(ink(minus, spark)) == ink(minus)).all()
    plus, digit = (48, 6, 7, 8), (57, 3, 8, 13)    # "+4" のような、右端の文字の並び（すき間 2 画素）
    assert (drop_detached(ink(plus, digit, spark)) == ink(plus, digit)).all()
    assert (drop_detached(ink(plus, digit, (41, 8, 4, 7))) == ink(plus, digit, (41, 8, 4, 7))).all()   # 近い成分は残す
    # 右端に届く成分が無ければ、値の文字は写っていない（"-" が二値化で消えた）ので、すべて消す
    assert not drop_detached(ink(spark)).any()
    # 符号が消えて数字だけ残ったものは消さない（読めない値として残す）
    assert (drop_detached(ink(digit)) == ink(digit)).all()


def test_matching_is_not_loosened():
    """見本との違いが基準を超えたら、近い見本があっても当てない（読めないものは取り込まずに見てもらう）。

    スキル名とスロット欄でゆるい基準を試したが、取り違えの余地を否定できず、やめた。
    """
    import numpy as np

    from app.ocr.kuijin_ocr import TemplateBank

    slots = TemplateBank(BUNDLED_TEMPLATE_DIR, "1280x720", "slot", "_base3")
    count, index = len(slots.labels), slots.labels.index("+3")
    assert slots.match(slots.bits[index].copy()) == index
    thin = slots.bits[index].copy()
    thin[np.flatnonzero(thin)[::5]] = False   # 全体の違い 0.2（基準は 0.15 未満）
    assert slots.match(thin) == count and slots.labels[count] is None


def test_app_reads_with_bundled_templates_only(tmp_path):
    """アプリ（label_dir あり）は同梱の見本だけで読み、保存もラベルの入力もしない。

    例外は、同梱の見本が無い初期スロットのスロット欄だけ（見本が無いと全部の行が読めないため）。
    """
    import numpy as np

    from app.ocr.kuijin_ocr import OcrSession

    def session(base_slot: int) -> OcrSession:
        return OcrSession([], [], base_slot, 4000, None, BUNDLED_TEMPLATE_DIR, label_dir=tmp_path / "labels")

    known = session(3)
    names, slots = known.bank("1280x720", "name"), known.bank("1280x720", "slot")
    assert not names.saved and not slots.saved and slots.template_dir == BUNDLED_TEMPLATE_DIR
    new_name = names.match(np.ones(names.bits.shape[1], dtype=bool))   # どの見本にも当たらない形
    assert names.labels[new_name] is None and known.pending_labels() == []

    unknown = session(4)   # 初期スロット 4 の見本は同梱していない
    slots = unknown.bank("1280x720", "slot")
    assert slots.saved and slots.template_dir == tmp_path / "labels" and len(slots.labels) == 0
    slots.match(np.ones(slots.bits.shape[1], dtype=bool))
    assert [(p.kind, p.index) for p in unknown.pending_labels()] == [("slot", 0)]
    assert not unknown.bank("1280x720", "glyph").saved

    cli = OcrSession([], [], 3, 4000, None, BUNDLED_TEMPLATE_DIR)   # CLI は今までどおり、すべての見本を保存する
    assert cli.bank("1280x720", "name").saved


def test_template_bank_is_unlabeled(tmp_path):
    from app.ocr.kuijin_ocr import TemplateBank

    names = TemplateBank(tmp_path, "1280x720", "name")
    names.labels = [None, "攻撃", "回復速度?"]   # "?" 付きは以前の自動ラベル付けで候補が僅差だったもの
    assert [names.is_unlabeled(i) for i in range(3)] == [True, False, True]

    slots = TemplateBank(tmp_path, "1280x720", "slot", "_base3")
    slots.labels = ["+1", "?slot#1", None]
    assert [slots.is_unlabeled(i) for i in range(3)] == [False, True, True]

    glyphs = TemplateBank(tmp_path, "1280x720", "glyph")
    glyphs.labels = ["1", "", None]   # "" はノイズとしてラベル付け済み
    assert [glyphs.is_unlabeled(i) for i in range(3)] == [False, False, True]


def test_checked_number_marks_malformed_values():
    """数値の形でない読み取り（文字のラベルの選び間違いなど）は、取込を止めずに読めない値にする。"""
    from app.ocr.kuijin_ocr import checked_number

    assert [checked_number(v) for v in ("-", "+24", "-3", "+?")] == ["-", "+24", "-3", "+?"]
    assert [checked_number(v) for v in ("+1+", "12", "+", "-+2")] == ["+1+?", "12?", "+?", "-+2?"]


def test_label_choices():
    from app.ocr.kuijin_ocr import label_choices

    assert "攻撃" in label_choices("name")
    assert label_choices("slot") == ["+0", "+1", "+2", "+3", "+4", "+5", "+6"]
    assert "" in label_choices("glyph") and "+" in label_choices("glyph")


def _write_jpeg(path, width, height):
    import cv2
    import numpy as np

    ok, buf = cv2.imencode(".jpg", np.zeros((height, width, 3), dtype=np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


def test_unsupported_resolution_stops_before_reading(tmp_path):
    """見本の無い解像度の画像が 1 枚でもあれば、照合の前に止まり、見本も保存しない。"""
    from app.ocr.kuijin_ocr import UnsupportedResolutionError, list_images, start_reading

    images = tmp_path / "images"
    images.mkdir()
    for name in ("1.jpg", "3.jpg"):
        _write_jpeg(images / name, 1280, 720)
    _write_jpeg(images / "2.jpg", 1920, 1080)
    _write_jpeg(images / "4.jpg", 1920, 1080)
    templates = _copy_templates(tmp_path / "templates")
    before = sorted(p.name for p in templates.iterdir())

    with pytest.raises(UnsupportedResolutionError) as exc_info:
        start_reading(list_images([images]), 3, 4000, None, templates, use_processes=False)
    assert [(Path(p).name, size) for p, size in exc_info.value.files] == [("2.jpg", "1920x1080"), ("4.jpg", "1920x1080")]
    assert "1920x1080" in str(exc_info.value) and "1280x720" in str(exc_info.value)
    assert sorted(p.name for p in templates.iterdir()) == before


def test_reading_time_excludes_wait_between_start_and_finish(tmp_path):
    """読み取りの時間に、ラベル入力のダイアログで待っている時間（start と finish の間）を含めない。"""
    import time

    from app.ocr.kuijin_ocr import finish_reading, list_images, start_reading

    images = tmp_path / "images"
    images.mkdir()
    _write_jpeg(images / "1.jpg", 1280, 720)
    begin = time.perf_counter()
    session = start_reading(list_images([images]), 3, 4000, None, _copy_templates(tmp_path / "templates"),
                            use_processes=False)
    time.sleep(1.0)
    run = finish_reading(session)
    assert run.timings["total"] < time.perf_counter() - begin - 0.9


def test_level_change_error_uses_skill_max_level():
    """レベルの増減は、スキルごとの最大レベル（防具が元から持つスキルは元のレベルを引いた分）までを認める。"""
    from app.ocr.kuijin_ocr import level_change_error

    muscle = {"攻撃": 2, "火事場力": 3}
    assert level_change_error("逆恨み", 5, 5, muscle) is None          # 最大レベル 5 のスキルの +5 は正しい
    assert "最大レベル" in level_change_error("逆恨み", 6, 5, muscle)
    assert "最大レベル" in level_change_error("体術", 4, 3, muscle)     # 以前の ±4 では見逃していた
    assert level_change_error("攻撃", 5, 7, muscle) is None            # 元の Lv2 から Lv7 まで
    assert "元のレベル Lv2" in level_change_error("攻撃", 6, 7, muscle)
    assert level_change_error("攻撃", 7, 7, None) is None              # 元から持つスキルが分からなければ最大レベルまで
    assert level_change_error("攻撃", -2, 7, muscle) is None           # マイナスは元のレベルとの比較を別に行う
    assert "多く下がって" in level_change_error("体術", -4, 3, None)


def test_images_and_templates_under_non_ascii_paths(tmp_path):
    """日本語を含むパス（ユーザー名が日本語の PC など）でも、画像と画面判定の見本を読み書きできる。

    cv2.imread / cv2.imwrite は Windows でこうしたパスを開けず、見本が読めないとすべての画像が
    「結果画面以外」になっていた。
    """
    import cv2
    import numpy as np

    from app.ocr.kuijin_ocr import LAYOUTS, _init_worker, _signatures, imread, imwrite, load_image, signature_dir

    base = tmp_path / "日本語ユーザー" / "練成（TV）"
    base.mkdir(parents=True)
    _write_jpeg(base / "画像.jpg", 1280, 720)
    assert load_image(str(base / "画像.jpg"))[1] == "1280x720"
    imwrite(base / "保存.png", np.full((4, 6), 255, dtype=np.uint8))
    assert imread(base / "保存.png", cv2.IMREAD_GRAYSCALE).shape == (4, 6)
    assert imread(base / "無い.png") is None

    templates = _copy_templates(base / "templates")
    assert "日本語" in str(signature_dir(templates))
    _signatures.clear()
    _init_worker(templates)
    assert set(_signatures) == set(LAYOUTS)   # 画面判定の見本が読めている


def test_level_bar_ignores_spots_right_of_the_squares():
    """レベルの増減は、四角の並びの中だけで数える。並びより右の空いた所にある赤い光の粒は数えない。"""
    import numpy as np

    from app.ocr.kuijin_ocr import BAR_PITCH, BAR_X0, BAR_Y, read_level_bar, skill_features

    img = np.full((720, 1280, 3), 20, dtype=np.uint8)
    for i, bgr in enumerate([(230, 120, 40), (230, 120, 40), (40, 40, 190), (60, 60, 60), (60, 60, 60)]):
        x = BAR_X0 + BAR_PITCH * i   # 青・青・赤・灰・灰（火事場力 Lv3 → Lv2、最大 Lv5）
        img[BAR_Y - 3:BAR_Y + 4, x - 5:x + 6] = bgr
    assert read_level_bar(img, 0) == "-1" and skill_features(img, 0)["bar"] == "BBRgg"
    x = BAR_X0 + BAR_PITCH * 6   # 並びの右の空いた所に、赤い光の粒
    img[BAR_Y - 2:BAR_Y + 3, x - 2:x + 3] = (60, 50, 200)
    assert read_level_bar(img, 0) == "-1"


def test_result_rows_keep_their_image(tmp_path):
    """取り込んだ結果ごとに、読み取った画像のファイル名を残す（検索結果や回収の画面から、その画像を見るため）。

    同じ回の重複は残した方の画像、確認が必要で取り込まなかった行は対象外。テキストの取込には画像が無い。
    """
    from app.core.importer import SOURCE_8BIT, import_block
    from app.core.search import ResultImage, SearchParams, fetch_result_images, search_results
    from app.db.connection import get_connection

    unreadable = _money_record("c.jpg", "92017", water="+?", cost="?")
    report = build_report([_money_record("a.jpg", "100017"), _money_record("a2.jpg", "100017"),
                           _money_record("b.jpg", "96017"), unreadable], 4, tmp_path)
    assert report.image_names == {1: "a.jpg", 2: "b.jpg"} and report.money_tail == 17

    conn = get_connection(tmp_path / "test.db")
    image_batch = import_block(conn, report.import_text, "ギルパレ脚", source=SOURCE_8BIT, image_dir="D:/shots",
                               image_names=report.image_names, zeny_tail=report.money_tail)
    # 下 3 桁を保存していなかった頃のバッチ（正確なゼニーは出せない）と、テキストの取込（画像が無い）
    old_batch = import_block(conn, report.import_text, "ギルパレ脚", source=SOURCE_8BIT, image_dir="D:/old",
                             image_names=report.image_names)
    text_batch = import_block(conn, report.import_text, "ギルパレ脚")
    rows = search_results(conn, SearchParams())
    images = fetch_result_images(conn, [row.id for row in rows])
    assert {(row.batch_id, row.zeny_count): images.get(row.id) for row in rows} == {
        (image_batch.batch_id, 1): ResultImage(str(Path("D:/shots") / "a.jpg"), 100017),
        (image_batch.batch_id, 2): ResultImage(str(Path("D:/shots") / "b.jpg"), 96017),
        (old_batch.batch_id, 1): ResultImage(str(Path("D:/old") / "a.jpg"), None),
        (old_batch.batch_id, 2): ResultImage(str(Path("D:/old") / "b.jpg"), None),
        (text_batch.batch_id, 1): None, (text_batch.batch_id, 2): None}
    conn.close()

    # ゼニーの数字を持たない記録（下 3 桁が分からない）では None
    assert build_report([_record("a.jpg", _values("100"))], 4, tmp_path).money_tail is None


def test_missing_sign_is_decided_by_color():
    """符号が読めなかった値（数字だけ）は、数字の色で符号を決める（緑 = プラス、赤 = マイナス）。

    Switch 2 の TV モードでは、雷耐性の行の "-" が暗く描かれて二値化で消える。色が分からなければ読めない値のまま。
    符号が読めている値・数字以外が混ざった値には使わない。
    """
    import numpy as np

    from app.ocr.kuijin_ocr import NO_SIGN, Region, read_number, value_color, with_sign_by_color

    assert with_sign_by_color(NO_SIGN + "2", "red") == "-2" and with_sign_by_color(NO_SIGN + "12", "green") == "+12"
    assert with_sign_by_color(NO_SIGN + "2", "") == "2?"
    assert [with_sign_by_color(v, "red") for v in ("+2", "-", "+1+?", "1?", "+3")] == ["+2", "-", "+1+?", "1?", "+3"]

    class Glyphs:   # どの文字も「2」と読む見本
        labels = ["2"]

        def match(self, glyph, source=None):
            return 0

    bits = np.zeros((22, 72), dtype=bool)
    bits[4:16, 58:64] = True   # 数字 1 文字だけ（符号なし）
    assert read_number(bits, Glyphs()) == NO_SIGN + "2"
    bits[9:11, 50:55] = True   # 左に "-"
    assert read_number(bits, Glyphs()) == "-2"

    region = Region(0, 0, 72, 22, "max", 0.6, min_component=3, right_aligned=True)
    for bgr, color in (((60, 60, 240), "red"), ((40, 230, 40), "green"), ((150, 150, 150), "")):
        img = np.full((22, 72, 3), 20, dtype=np.uint8)
        img[4:16, 58:64] = bgr
        assert value_color(img, region, 0, region.ink(img, 0)) == color


def _money_record(name: str, money: str, **changes):
    from app.ocr.kuijin_ocr import money_thousands

    return _record(name, {**_values(money_thousands(money)), "money": money, **changes})


def test_money_with_different_last_three_digits_needs_review(tmp_path):
    """所持ゼニーの下 3 桁が、記録の中でいちばん多い値と違う画像は、取り込まずに見てもらう（読み間違いか、別の記録の画像）。

    基準は最初の画像ではない（その 1 枚の読み間違いで、ほかの全部が食い違いにならないように）。
    確認が必要な画像には、下 3 桁までの正確なゼニーを残す（見てもらう画面で、ゲームの画面と見比べるため）。
    """
    from app.core.history import fetch_batch_errors
    from app.core.importer import SOURCE_8BIT, import_block
    from app.db.connection import get_connection
    from app.ui.unread_viewer import zeny_text

    doubtful = _money_record("c.jpg", "92017", fire="+30")   # 耐性の増減としてありえない値
    records = [_money_record("a.jpg", "100011"), _money_record("b.jpg", "96017"), doubtful,
               _money_record("d.jpg", "88017"), _money_record("e.jpg", "84917"), _money_record("f.jpg", "80017")]
    report = build_report(records, 4, tmp_path)
    # 1 枚目（下 3 桁 011）と 5 枚目（917）は、何回目かを決めない。初期ゼニーは 2 枚目から求める
    assert report.text.splitlines()[0] == "初期ゼニー,100"
    assert [(count, zeny, name, exact) for _, count, zeny, name, _, exact in report.review] == [
        (None, None, "a.jpg", None), (2, 92, "c.jpg", 92017), (None, None, "e.jpg", None)]
    assert "下 3 桁" in report.review[0][4] and "100011" in report.review[0][4]
    assert [line.split(",")[0] for line in report.import_text.splitlines()[2:]] == ["1", "3", "5"]
    # 食い違う画像のゼニーは、減り方のチェックに使わない（「増えています」などは出ない）。その回は、
    # ゼニーが読めない画像と同じく、撮れていない回として知らせる
    assert report.batch_errors == ["1回分の画像がありません（撮り忘れの疑い）: d.jpg（88千ゼニー）→ f.jpg（80千ゼニー）"]

    conn = get_connection(tmp_path / "test.db")
    summary = import_block(conn, report.import_text, "ギルパレ脚", source=SOURCE_8BIT,
                           review_images=[(count, zeny, f"D:/shots/{name}", reason, exact)
                                          for _, count, zeny, name, reason, exact in report.review])
    unread = fetch_batch_errors(conn, summary.batch_id).unread
    assert unread == [(2, 92, "D:/shots/c.jpg", 92017), (None, None, "D:/shots/a.jpg", None),
                      (None, None, "D:/shots/e.jpg", None)]
    conn.close()
    assert zeny_text(92, 92017) == "92,017" and zeny_text(58836, None) == "58,836千" and zeny_text(None, None) == "不明"


def test_small_money_is_read_by_last_three_digits(tmp_path):
    """4 桁に満たない所持ゼニーは、下 3 桁がほかの画像と同じときだけ 0 千ゼニーと読む（ゼニーが尽きた最後の画像）。"""
    from app.ocr.kuijin_ocr import money_thousands

    record = _money_record

    assert money_thousands("58836017") == "58836" and money_thousands("17") == "?" and money_thousands("?") == "?"

    report = build_report([record("a.jpg", "8017"), record("b.jpg", "4017"), record("c.jpg", "17")], 4, tmp_path)
    assert [line.split(",")[:2] for line in report.text.splitlines()[2:]] == [["1", "8"], ["2", "4"], ["3", "0"]]
    assert report.errors == [] and report.review == []

    # 下 3 桁が違えば、数字が欠けた読み間違いかもしれないので、読めないまま
    report = build_report([record("a.jpg", "8017"), record("b.jpg", "4017"), record("c.jpg", "7")], 4, tmp_path)
    assert report.text.splitlines()[4].split(",")[:2] == ["?", "?"]
    assert [name for _, _, _, name, _, _ in report.review] == ["c.jpg"]

    # 比べる相手（4 桁以上のゼニー）が無ければ、読めないまま
    report = build_report([record("c.jpg", "17")], 4, tmp_path)
    assert report.text.splitlines()[2].split(",")[:2] == ["?", "?"]


def test_detect_screen_with_additional_signature(tmp_path):
    """画面判定の見本は、画面の種類ごとに何枚でも持てる（描かれ方の違う本体・モードの分。{layout}_{名前}.png）。"""
    import numpy as np

    from app.ocr.kuijin_ocr import LAYOUTS, _init_worker, _signatures, detect_screen, imwrite, save_signature

    # 同梱の見本のどれにも似ていない見出し（白い縦の棒）の画像
    img = np.full((720, 1280, 3), 20, dtype=np.uint8)
    region = LAYOUTS["screen1"]["signature"]
    img[region.y0 + 4:region.y1 - 4, region.x0 + 10:region.x0 + 150:12] = 255
    imwrite(tmp_path / "other.png", img)

    templates = _copy_templates(tmp_path / "templates")
    try:
        _signatures.clear()
        _init_worker(templates)
        assert detect_screen(img) is None
        bundled = len(_signatures["screen1"])
        save_signature("screen1_other", str(tmp_path / "other.png"), templates)
        _signatures.clear()
        _init_worker(templates)
        assert len(_signatures["screen1"]) == bundled + 1 and detect_screen(img) == "screen1"
    finally:
        _signatures.clear()


def test_build_report_marks_hidden_minus(tmp_path):
    """結果画面２で写っていないスキルがすべてマイナスと確定したら、印「何らかのマイナススキル」を付け、マイナスを「有」にする。"""
    values = _values("100", "逆恨み", "+1")
    values.update({"defense": "-11", "slot_add": "+0", "fire": "+2", "water": "-", "thunder": "-", "ice": "-",
                   "dragon": "-", "skill2": "火事場力", "lv2": "+1", "skill3": "体力回復量UP", "lv3": "+1", "cost": "24"})
    muscle = {"攻撃": 2, "火事場力": 3}

    with_table = build_report([_record("a.jpg", values, screen="screen2")], 4, tmp_path, muscle, table=5)
    row = with_table.text.splitlines()[2].split(",")
    assert row[4] == "有" and row[12:14] == ["何らかのマイナススキル", ""]
    results, errors = parse_result_log_block(with_table.text)
    assert errors == [] and results[0].has_deficiency == 1
    assert ("何らかのマイナススキル", 0) in [(s.name, s.value) for s in results[0].skills]

    # 抽選テーブルが分からなければ、仕様では確定できないので「不明」のまま
    without_table = build_report([_record("a.jpg", values, screen="screen2")], 4, tmp_path, muscle)
    row = without_table.text.splitlines()[2].split(",")
    assert row[4] == "無" and row[12] == "不明"
