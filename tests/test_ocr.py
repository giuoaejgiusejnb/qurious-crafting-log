from pathlib import Path

import pytest

from app.core.parser import parse_result_log_block
from app.ocr.kuijin_ocr import BUNDLED_TEMPLATE_DIR, build_report, parse_minus_skills, user_template_dir


def test_parse_minus_skills():
    assert parse_minus_skills("攻撃:2,火事場力:3") == {"攻撃": 2, "火事場力": 3}
    assert parse_minus_skills(" 攻撃:2， 火事場力:3 ") == {"攻撃": 2, "火事場力": 3}
    assert parse_minus_skills("") is None
    with pytest.raises(ValueError):
        parse_minus_skills("攻撃")


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


def test_user_template_dir_copies_bundled_templates(tmp_path):
    dst = user_template_dir(tmp_path)
    assert (dst / "screens" / "screen1.png").exists()
    assert (dst / "1280x720_name.json").exists()
    assert not (dst / "review").exists()   # 確認用の拡大画像は複製しない
    # 2 回目以降は複製し直さない（ユーザーの環境で増えた見本を消さない）
    (dst / "1280x720_name.json").write_text("[]", encoding="utf-8")
    user_template_dir(tmp_path)
    assert (dst / "1280x720_name.json").read_text(encoding="utf-8") == "[]"
    assert (BUNDLED_TEMPLATE_DIR / "1280x720_name.json").read_text(encoding="utf-8") != "[]"


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


def test_jpeg_size_reads_header(tmp_path):
    from app.ocr.kuijin_ocr import jpeg_size

    _write_jpeg(tmp_path / "a.jpg", 1280, 720)
    (tmp_path / "b.jpg").write_bytes(b"not a jpeg")
    assert jpeg_size(str(tmp_path / "a.jpg")) == (1280, 720)
    assert jpeg_size(str(tmp_path / "b.jpg")) is None


def test_unsupported_resolution_stops_before_reading(tmp_path):
    """見本の無い解像度の画像が 1 枚でもあれば、読み取りの前に止まり、見本も保存しない。"""
    from app.ocr.kuijin_ocr import UnsupportedResolutionError, list_images, start_reading

    images = tmp_path / "images"
    images.mkdir()
    for name in ("1.jpg", "3.jpg"):
        _write_jpeg(images / name, 1280, 720)
    _write_jpeg(images / "2.jpg", 1920, 1080)
    _write_jpeg(images / "4.jpg", 1920, 1080)
    templates = user_template_dir(tmp_path / "data")
    before = sorted(p.name for p in templates.iterdir())

    with pytest.raises(UnsupportedResolutionError) as exc_info:
        start_reading(list_images([images]), 3, 4000, None, templates, use_processes=False)
    assert [(Path(p).name, size) for p, size in exc_info.value.files] == [("2.jpg", "1920x1080"), ("4.jpg", "1920x1080")]
    assert "1920x1080" in str(exc_info.value) and "1280x720" in str(exc_info.value)
    assert sorted(p.name for p in templates.iterdir()) == before


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
