import json

import numpy as np

from app.ocr.kuijin_ocr import DIGIT_SHAPE
from app.ocr.template_sync import MANIFEST_FILE, sync_templates

STEM = "1280x720_glyph"


def _glyph(seed: int) -> np.ndarray:
    """互いに一致しない 1 文字の見本（DIGIT_SHAPE の二値画像を 1 行にしたもの）。"""
    rng = np.random.default_rng(seed)
    return rng.random(DIGIT_SHAPE[0] * DIGIT_SHAPE[1]) < 0.5


def _save(directory, stem, glyphs, labels):
    directory.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(directory / f"{stem}.npz", bits=np.array(glyphs))
    (directory / f"{stem}.json").write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")


def _load(directory, stem):
    bits = np.load(directory / f"{stem}.npz")["bits"]
    return bits, json.loads((directory / f"{stem}.json").read_text(encoding="utf-8"))


def _make_bundled(path, glyphs, labels, props=None):
    _save(path, STEM, glyphs, labels)
    (path / "screens").mkdir(exist_ok=True)
    (path / "screens" / "screen1.png").write_bytes(b"png")
    (path / "skill_props.json").write_text(json.dumps(props or {}, ensure_ascii=False), encoding="utf-8")


def test_first_sync_copies_bundled_and_records_counts(tmp_path):
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    _make_bundled(bundled, [_glyph(1), _glyph(2)], ["1", "2"])
    (bundled / "review").mkdir()

    sync_templates(user, bundled)

    assert _load(user, STEM)[1] == ["1", "2"]
    assert not (user / "review").exists()
    assert json.loads((user / MANIFEST_FILE).read_text(encoding="utf-8")) == {STEM: 2}


def test_bundled_update_keeps_user_labels(tmp_path):
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    a, b, c, d = _glyph(1), _glyph(2), _glyph(3), _glyph(4)
    _make_bundled(bundled, [a, b], ["1", "2"], {"攻撃": {"max": 7}})
    sync_templates(user, bundled)

    # ユーザーがアプリで c（"7"）と、あとで同梱にも入る d を付けた
    _save(user, STEM, [a, b, c, d.copy()], ["1", "2", "7", "4"])
    (user / "skill_props.json").write_text(json.dumps({"攻撃": {"max": 6}, "新スキル": {"max": 3}}, ensure_ascii=False),
                                           encoding="utf-8")
    # アプリの更新: 開発側で a のラベルを直し、d を追加した
    _make_bundled(bundled, [a, b, d], ["0", "2", "8"], {"攻撃": {"max": 7}})

    assert sync_templates(user, bundled) == [STEM]

    bits, labels = _load(user, STEM)
    assert labels == ["0", "2", "8", "7"]   # 同梱（修正後のラベル）+ ユーザーの c。d は同梱と重複するので除く
    assert np.array_equal(bits[3], c)
    props = json.loads((user / "skill_props.json").read_text(encoding="utf-8"))
    assert props == {"攻撃": {"max": 7}, "新スキル": {"max": 3}}   # 同梱の値を優先し、ユーザーの分は残す
    assert json.loads((user / MANIFEST_FILE).read_text(encoding="utf-8")) == {STEM: 3}

    # 同梱が増えていなければ何もしない
    assert sync_templates(user, bundled) == []
    assert _load(user, STEM)[1] == ["0", "2", "8", "7"]


def test_new_bank_and_screens_are_added(tmp_path):
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    _make_bundled(bundled, [_glyph(1)], ["1"])
    sync_templates(user, bundled)
    (user / "screens" / "screen1.png").unlink()
    _save(bundled, "1280x720_slot_base4", [np.zeros(1, dtype=bool)], ["+0"])   # 同梱に新しい初期スロットの見本

    assert sync_templates(user, bundled) == ["1280x720_slot_base4"]
    assert _load(user, "1280x720_slot_base4")[1] == ["+0"]
    assert (user / "screens" / "screen1.png").exists()


def test_copy_made_before_manifest_uses_common_prefix(tmp_path):
    """記録ファイルが無い（この仕組みより前の）複製は、先頭から同梱と同じ見本の数を、複製したときの数とみなす。"""
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    a, b, c = _glyph(1), _glyph(2), _glyph(3)
    _make_bundled(bundled, [a], ["1"])
    sync_templates(user, bundled)
    (user / MANIFEST_FILE).unlink()
    _save(user, STEM, [a, c], ["1", "7"])
    _make_bundled(bundled, [a, b], ["1", "2"])

    sync_templates(user, bundled)

    assert _load(user, STEM)[1] == ["1", "2", "7"]
