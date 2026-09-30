from app.ui.import_view import _validate_ocr_params


def test_validate_ocr_params():
    assert _validate_ocr_params("", "") is None   # 空欄は後から入力できるので問題なし
    assert _validate_ocr_params("3", "火事場力:2,災禍転福:2") is None
    assert "数字" in _validate_ocr_params("x", "")
    assert "スキル名:元のLv" in _validate_ocr_params("3", "火事場力")
    assert "存在しない" in _validate_ocr_params("3", "存在しない:1")
