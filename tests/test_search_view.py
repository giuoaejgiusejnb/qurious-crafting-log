from app.ui.search_view import _short_datetime


def test_short_datetime():
    assert _short_datetime("2026-10-01T08:25:07") == "10-01 08:25"
    assert _short_datetime("2026-10-01") == "2026-10-01"   # 時刻の無い値はそのまま
