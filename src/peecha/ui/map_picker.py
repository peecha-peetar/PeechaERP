"""طبقِ بازخوردِ کاربر رویِ R220 («ثبتِ مختصات باید رویِ نقشه باشد، نه
تایپِ عدد»): دیالوگِ انتخابِ موقعیتِ مکانی با کلیک/درگ رویِ نقشه.

تصمیمِ سرویسِ نقشه (طبقِ پاسخِ صریحِ کاربر): OpenStreetMap با کتابخانه‌یِ
Leaflet -- رایگان و بدونِ نیاز به ثبت‌نام/کلیدِ API. کتابخانه (JS/CSS/
آیکن‌ها) به‌صورتِ محلی وندور شده (src/peecha/ui/vendor/leaflet/) تا فقط
خودِ کاشی‌هایِ نقشه (تصاویرِ نقشه) نیازمندِ اینترنت باشند، نه کتابخانه.
کاربر توجه داده که این مسیر (دسترسیِ tile.openstreetmap.org از داخلِ
ایران) باید عملاً تست شود -- در صورتِ فیلترینگ، جایگزینیِ آدرسِ کاشی با
یک ارائه‌دهنده‌یِ دیگر (Neshan/Map.ir) در همین یک تابع کافی است."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor" / "leaflet"

# طبقِ نبودِ زیرساختِ نقشه‌یِ داخلیِ ایران در این پروژه: مرکزِ پیش‌فرض
# (وقتی مختصاتِ قبلی موجود نیست) تهران است، نه پیش‌فرضِ جهانیِ Leaflet.
_DEFAULT_LAT = 35.6892
_DEFAULT_LON = 51.3890

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<link rel="stylesheet" href="leaflet.css" />
<style>html, body, #map {{ height: 100%; margin: 0; padding: 0; }}</style>
</head>
<body>
<div id="map"></div>
<script src="leaflet.js"></script>
<script>
  // طبقِ رفتارِ شناخته‌شده‌یِ Leaflet (تشخیصِ خودکارِ مسیرِ آیکن‌ها از
  // رویِ src اسکریپت، که در HTMLِ محلی همیشه درست کار نمی‌کند): مسیر
  // را صریحاً تنظیم می‌کنیم تا نشانگرِ پیش‌فرض قطعاً نمایش داده شود.
  L.Icon.Default.mergeOptions({{ imagePath: 'images/' }});
  var map = L.map('map').setView([{lat}, {lon}], {zoom});
  L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }}).addTo(map);
  var marker = L.marker([{lat}, {lon}], {{draggable: true}}).addTo(map);
  window.currentLatLng = {{lat: {lat}, lng: {lon}}};
  function updatePosition(latlng) {{
    marker.setLatLng(latlng);
    window.currentLatLng = {{lat: latlng.lat, lng: latlng.lng}};
  }}
  marker.on('dragend', function() {{ window.currentLatLng = marker.getLatLng(); }});
  map.on('click', function(e) {{ updatePosition(e.latlng); }});
</script>
</body>
</html>
"""


class MapPickerDialog(QDialog):
    """دیالوگِ مودالِ انتخابِ مختصات؛ بعدِ exec()، نتیجه در
    result_lat/result_lon است (اگر کاربر لغو کند، همان مقادیرِ اولیه)."""

    def __init__(self, parent=None, initial_lat: float | None = None, initial_lon: float | None = None):
        super().__init__(parent)
        self.setWindowTitle("انتخابِ موقعیتِ مکانی رویِ نقشه")
        self.resize(760, 580)
        self.result_lat = initial_lat
        self.result_lon = initial_lon

        lat = initial_lat if initial_lat is not None else _DEFAULT_LAT
        lon = initial_lon if initial_lon is not None else _DEFAULT_LON
        zoom = 15 if initial_lat is not None else 11

        layout = QVBoxLayout(self)
        self.view = QWebEngineView()
        html = _HTML_TEMPLATE.format(lat=lat, lon=lon, zoom=zoom)
        self.view.setHtml(html, QUrl.fromLocalFile(str(_VENDOR_DIR) + "/"))
        layout.addWidget(self.view, stretch=1)

        self.hint_label = QLabel("رویِ نقشه کلیک کنید یا نشانگر را جابه‌جا کنید، سپس «تایید» را بزنید.")
        layout.addWidget(self.hint_label)

        buttons = QHBoxLayout()
        ok_button = QPushButton("تایید")
        ok_button.setObjectName("primaryIconButton")
        ok_button.clicked.connect(self._accept_with_position)
        buttons.addWidget(ok_button)
        cancel_button = QPushButton("انصراف")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

    def _accept_with_position(self) -> None:
        self.view.page().runJavaScript("JSON.stringify(window.currentLatLng)", self._on_position_read)

    def _on_position_read(self, result: str | None) -> None:
        try:
            data = json.loads(result)
            self.result_lat = float(data["lat"])
            self.result_lon = float(data["lng"])
        except (TypeError, ValueError, KeyError):
            pass
        self.accept()
