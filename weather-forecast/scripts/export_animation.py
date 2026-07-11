"""Render the forecast GeoTIFF series to an animated GIF.

Run with QGIS's bundled Python:
  "C:\\Program Files\\QGIS 3.44.12\\bin\\python-qgis-ltr.bat" export_animation.py [--var 2t]
"""
import argparse
import glob
import os
import re
from datetime import datetime, timedelta

from qgis.core import (
    QgsApplication, QgsRasterLayer, QgsColorRampShader, QgsRasterShader,
    QgsSingleBandPseudoColorRenderer, QgsMapSettings, QgsMapRendererParallelJob,
    QgsRectangle, QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtCore import QSize, QEventLoop
from qgis.PyQt.QtGui import QColor

BASE = os.path.join(os.path.expanduser("~"), "WeatherForecast")

RAMPS = {
    # var: (min, max, [(value, color, label), ...])
    "2t": (233.15, 313.15, [
        (233.15, QColor(48, 18, 227), "-40 °C"),
        (273.15, QColor(240, 240, 240), "0 °C"),
        (313.15, QColor(200, 30, 30), "+40 °C"),
    ]),
    "wind": (0.0, 30.0, [
        (0.0, QColor(255, 255, 255), "0 m/s"),
        (15.0, QColor(80, 170, 90), "15 m/s"),
        (30.0, QColor(120, 30, 160), "30 m/s"),
    ]),
    "msl": (95000.0, 105000.0, [
        (95000.0, QColor(120, 30, 160), "950 hPa"),
        (100000.0, QColor(240, 240, 240), "1000 hPa"),
        (105000.0, QColor(230, 140, 30), "1050 hPa"),
    ]),
}


def render_frame(path: str, size: QSize):
    layer = QgsRasterLayer(path, os.path.basename(path))
    var = os.path.basename(path).split("_")[0]
    mn, mx, stops = RAMPS.get(var, RAMPS["2t"])
    fn = QgsColorRampShader(mn, mx)
    fn.setColorRampType(QgsColorRampShader.Interpolated)
    fn.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, c, l) for v, c, l in stops])
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fn)
    layer.setRenderer(QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader))

    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    settings.setExtent(QgsRectangle(-180, -90, 180, 90))
    settings.setOutputSize(size)
    settings.setBackgroundColor(QColor(255, 255, 255))

    job = QgsMapRendererParallelJob(settings)
    loop = QEventLoop()
    job.finished.connect(loop.quit)
    job.start()
    loop.exec_()
    return job.renderedImage()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--var", default="2t", choices=list(RAMPS))
    p.add_argument("--width", type=int, default=1080)
    args = p.parse_args()

    app = QgsApplication([], False)
    app.initQgis()

    tiffs = sorted(glob.glob(os.path.join(BASE, "data", "geotiffs", f"{args.var}_*.tif")))
    if not tiffs:
        raise SystemExit(f"no {args.var} GeoTIFFs found")

    size = QSize(args.width, args.width // 2)
    pattern = re.compile(rf"{args.var}_(\d{{10}})\+(\d{{3}})h\.tif$")

    frames = []
    for path in tiffs:
        img = render_frame(path, size)
        m = pattern.search(os.path.basename(path))
        if m:
            valid = datetime.strptime(m.group(1), "%Y%m%d%H") + timedelta(hours=int(m.group(2)))
            frame_png = os.path.join(BASE, "data", "geotiffs", f"_frame_{args.var}_{m.group(2)}.png")
        else:
            frame_png = path + ".png"
        img.save(frame_png)
        frames.append(frame_png)
        print(f"rendered {os.path.basename(frame_png)}")

    app.exitQgis()

    # Assemble GIF with Pillow (bundled with QGIS's matplotlib)
    from PIL import Image
    images = [Image.open(f).convert("P", palette=Image.ADAPTIVE) for f in frames]
    out = os.path.join(BASE, "qgis", f"forecast_{args.var}.gif")
    images[0].save(out, save_all=True, append_images=images[1:], duration=350, loop=0)
    for f in frames:
        os.remove(f)
    print(f"wrote {out} ({len(images)} frames)")


if __name__ == "__main__":
    main()
