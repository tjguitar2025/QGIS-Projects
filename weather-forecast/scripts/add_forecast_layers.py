"""Phase 4: Add forecast GeoTIFFs to the QGIS project as time-enabled layers.

Each file  2t_<YYYYMMDDHH>+<step>h.tif  gets a fixed temporal range of
[valid_time, valid_time + 6h) so the Temporal Controller steps through the
forecast like an animation.

Run with QGIS's bundled Python:
  "C:\\Program Files\\QGIS 3.44.12\\bin\\python-qgis-ltr.bat" add_forecast_layers.py
"""
import glob
import os
import re
import sys
from datetime import datetime, timedelta

from qgis.core import (
    QgsApplication, QgsProject, QgsRasterLayer, QgsColorRampShader,
    QgsRasterShader, QgsSingleBandPseudoColorRenderer,
    QgsRasterLayerTemporalProperties, QgsDateTimeRange,
)
from qgis.PyQt.QtCore import QDateTime, Qt
from qgis.PyQt.QtGui import QColor

BASE = os.path.join(os.path.expanduser("~"), "WeatherForecast")
TIFF_DIR = os.path.join(BASE, "data", "geotiffs")
PROJECT = os.path.join(BASE, "qgis", "weather_forecast.qgz")
STEP_HOURS = 6

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", ""), True)
app = QgsApplication([], False)
app.initQgis()

project = QgsProject.instance()
if not project.read(PROJECT):
    sys.exit(f"Cannot read {PROJECT}")

# Per-variable ramps: (min, max, stops, group label, layer label)
VARS = {
    "2t": (233.15, 313.15, [
        (233.15, QColor(48, 18, 227), "-40 °C"),
        (273.15, QColor(240, 240, 240), "0 °C"),
        (313.15, QColor(200, 30, 30), "+40 °C"),
    ], "FourCastNetv2 2m temperature", "2m temp"),
    "wind": (0.0, 30.0, [
        (0.0, QColor(255, 255, 255), "0 m/s"),
        (15.0, QColor(80, 170, 90), "15 m/s"),
        (30.0, QColor(120, 30, 160), "30 m/s"),
    ], "FourCastNetv2 10m wind speed", "10m wind"),
    "msl": (95000.0, 105000.0, [
        (95000.0, QColor(120, 30, 160), "950 hPa"),
        (100000.0, QColor(240, 240, 240), "1000 hPa"),
        (105000.0, QColor(230, 140, 30), "1050 hPa"),
    ], "FourCastNetv2 MSL pressure", "MSL"),
}


def make_renderer(provider, mn, mx, stops):
    fn = QgsColorRampShader(mn, mx)
    fn.setColorRampType(QgsColorRampShader.Interpolated)
    fn.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, c, l) for v, c, l in stops])
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fn)
    return QgsSingleBandPseudoColorRenderer(provider, 1, shader)


added = 0
for var, (mn, mx, stops, group_name, label) in VARS.items():
    files = sorted(glob.glob(os.path.join(TIFF_DIR, f"{var}_*.tif")))
    if not files:
        continue
    group = project.layerTreeRoot().addGroup(group_name)
    group.setItemVisibilityChecked(var == "2t")  # only temperature on by default
    pattern = re.compile(rf"{var}_(\d{{10}})\+(\d{{3}})h\.tif$")

    for path in files:
        m = pattern.search(os.path.basename(path))
        if not m:
            continue
        base = datetime.strptime(m.group(1), "%Y%m%d%H")
        valid = base + timedelta(hours=int(m.group(2)))

        layer = QgsRasterLayer(path, f"{label} {valid:%Y-%m-%d %H:%M}Z")
        if not layer.isValid():
            print(f"skip invalid {path}")
            continue
        layer.setRenderer(make_renderer(layer.dataProvider(), mn, mx, stops))

        tprops = layer.temporalProperties()
        tprops.setIsActive(True)
        tprops.setMode(QgsRasterLayerTemporalProperties.ModeFixedTemporalRange)
        start = QDateTime(valid.year, valid.month, valid.day, valid.hour, 0, 0, 0, Qt.UTC)
        tprops.setFixedTemporalRange(QgsDateTimeRange(start, start.addSecs(STEP_HOURS * 3600)))

        project.addMapLayer(layer, False)
        group.addLayer(layer)
        added += 1

if not project.write(PROJECT):
    sys.exit("Failed to write project")
print(f"Added {added} time-enabled forecast layers to {PROJECT}")
app.exitQgis()
