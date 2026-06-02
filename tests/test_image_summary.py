"""Test render bảng tổng kết thành ảnh PNG."""
from image_summary import render_summary_image

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _row(user_id, name, count, total):
    return {"user_id": user_id, "full_name": name, "meal_count": count, "total": total}


class TestRenderSummaryImage:
    def test_returns_png_bytes(self):
        rows = [_row(1, "Hung", 12, 540000), _row(2, "Nam", 9, 405000)]
        data = render_summary_image(rows, paid_ids={1}, year_month="2026-05")
        assert isinstance(data, (bytes, bytearray))
        assert data[:8] == PNG_MAGIC
        assert len(data) > 100

    def test_single_row(self):
        data = render_summary_image([_row(1, "An", 5, 225000)], paid_ids=set(), year_month="2026-05")
        assert data[:8] == PNG_MAGIC

    def test_many_rows(self):
        rows = [_row(i, f"User{i}", i, i * 45000) for i in range(1, 16)]
        data = render_summary_image(rows, paid_ids={2, 4, 6}, year_month="2026-12")
        assert data[:8] == PNG_MAGIC

    def test_vietnamese_names_with_diacritics(self):
        rows = [
            _row(1, "Nguyễn Quang Hưng", 12, 540000),
            _row(2, "Lê Thị Hồng Đào", 9, 405000),
        ]
        data = render_summary_image(rows, paid_ids={1}, year_month="2026-05")
        assert data[:8] == PNG_MAGIC

    def test_long_name_does_not_crash(self):
        rows = [_row(1, "Trần Nguyễn Hoàng Long Phước Vĩnh An Bình", 30, 1350000)]
        data = render_summary_image(rows, paid_ids=set(), year_month="2026-05")
        assert data[:8] == PNG_MAGIC


class TestFontFallback:
    def test_missing_font_falls_back_not_crash(self):
        """Thiếu file font → dùng font mặc định, không raise OSError."""
        from image_summary import _font
        f = _font("Z:/khong-ton-tai-font.ttf", 20)
        assert f is not None
