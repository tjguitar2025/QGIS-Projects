"""Phase 1: Build a QGIS project with the GFS sample GRIB, styled for 2m temperature.

Run with QGIS's bundled Python:
  "C:\\Program Files\\QGIS 3.44.12\\bin\\python-qgis-ltr.bat" build_qgis_project.py
"""
import os
import sys

from qgis.core import (
    QgsApplication, QgsProject, QgsRasterLayer, QgsColorRampShader,
    QgsRasterShader, QgsSingleBandPseudoColorRenderer, QgsStyle,
)
from qgis.PyQt.QtGui import QColor

BASE = os.path.join(os.path.expanduser("~"), "WeatherForecast")
GRIB = os.path.join(BASE, "data", "input", "gfs_sample.grib2")
OUT = os.path.join(BASE, "qgis", "weather_forecast.qgz")

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", ""), True)
app = QgsApplication([], False)
app.initQgis()

project = QgsProject.instance()
project.setTitle("Local Weather Forecast")

layer = QgsRasterLayer(GRIB, "GFS sample")
if not layer.isValid():
    sys.exit(f"Could not load {GRIB}")

# Find the 2m temperature band via GRIB metadata (GRIB_ELEMENT=TMP at 2-HTGL)
from osgeo import gdal

os.environ.setdefault("GDAL_DATA", r"C:\Program Files\QGIS 3.44.12\apps\gdal\share\gdal")
ds = gdal.Open(GRIB)
tmp_band = 1
for b in range(1, ds.RasterCount + 1):
    md = ds.GetRasterBand(b).GetMetadata()
    if md.get("GRIB_ELEMENT") == "TMP" and md.get("GRIB_SHORT_NAME") == "2-HTGL":
        tmp_band = b
        break
ds = None

# Fixed ramp: -40 °C .. +40 °C in Kelvin (estimated band stats are unreliable for GRIB)
mn, mx = 233.15, 313.15

# Blue -> white -> red temperature ramp (values are Kelvin)
shader_fn = QgsColorRampShader(mn, mx)
shader_fn.setColorRampType(QgsColorRampShader.Interpolated)
items = [
    QgsColorRampShader.ColorRampItem(mn, QColor(48, 18, 227), f"{mn - 273.15:.0f} °C"),
    QgsColorRampShader.ColorRampItem(mn + 0.5 * (mx - mn), QColor(240, 240, 240), f"{(mn + 0.5 * (mx - mn)) - 273.15:.0f} °C"),
    QgsColorRampShader.ColorRampItem(mx, QColor(200, 30, 30), f"{mx - 273.15:.0f} °C"),
]
shader_fn.setColorRampItemList(items)
shader = QgsRasterShader()
shader.setRasterShaderFunction(shader_fn)
renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), tmp_band, shader)
layer.setRenderer(renderer)
layer.setName(f"GFS 2m temperature (band {tmp_band})")

project.addMapLayer(layer)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
if not project.write(OUT):
    sys.exit("Failed to write project")
print(f"Project written: {OUT}")
print(f"Temperature band: {tmp_band}, range {mn - 273.15:.1f} to {mx - 273.15:.1f} °C")

app.exitQgis()
