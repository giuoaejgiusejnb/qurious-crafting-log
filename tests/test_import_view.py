from pathlib import Path

from app.ui.import_view import _existing_dir, _validate_ocr_params


def test_validate_ocr_params():
    assert _validate_ocr_params("", "") is None   # 空欄は後から入力できるので問題なし
    assert _validate_ocr_params("3", "火事場力:2,災禍転福:2") is None
    assert "数字" in _validate_ocr_params("x", "")
    assert "スキル名:元のLv" in _validate_ocr_params("3", "火事場力")
    assert "存在しない" in _validate_ocr_params("3", "存在しない:1")


def test_existing_dir_falls_back_to_parent_or_none(tmp_path):
    """前回のフォルダが無ければ今ある親フォルダに、ドライブごと無ければ None にする（フォルダ選択が開けなくなるため）。"""
    (tmp_path / "album").mkdir()
    assert _existing_dir(str(tmp_path / "album")) == str(tmp_path / "album")
    assert _existing_dir(str(tmp_path / "album" / "2026" / "10")) == str(tmp_path / "album")
    assert _existing_dir(None) is None
    assert _existing_dir("") is None
    missing_drive = next(c for c in "ZYXWVUT" if not Path(f"{c}:/").exists())
    assert _existing_dir(f"{missing_drive}:/Nintendo/Album") is None
