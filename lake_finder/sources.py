"""Remote raster sources (all free, no API key) resampled onto one analysis grid.

* Water (satellite derived):
  - ``gsw``: JRC Global Surface Water, Landsat 1984-2021, 30 m. Band = water
    occurrence in percent. Gives both "usual" water and the maximum extent
    (draw-down / flood zone), which matters when picking a house site.
  - ``worldcover``: ESA WorldCover 2021, Sentinel-1/2, 10 m. Class 80 = water.
* Elevation: Copernicus GLO-90 DEM (TanDEM-X satellite), 3 arc-second COGs.

Results are cached as ``.npy`` files so re-runs with other scoring parameters are instant.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError
from rasterio.vrt import WarpedVRT

from .geo import Grid

log = logging.getLogger(__name__)

GSW_URL = "https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_{lon}_{lat}v1_4_2021.tif"
WORLDCOVER_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
DEM_URL = "https://copernicus-dem-90m.s3.amazonaws.com/{name}/{name}.tif"

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
# Honour the system CA bundle / corporate proxies.
for _var in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
    if os.environ.get(_var):
        os.environ.setdefault("GDAL_CURL_CA_BUNDLE", os.environ[_var])
        break


def _hemi(value: int, pos: str, neg: str) -> str:
    return f"{abs(value)}{pos if value >= 0 else neg}"


def _cells(grid: Grid, size: int, anchor: str):
    """Yield (lat_corner, lon_corner) of size-degree tiles intersecting the grid.

    ``anchor='sw'`` yields south-west corners, ``'nw'`` yields north-west corners."""
    lat0 = math.floor(grid.south / size) * size
    lon0 = math.floor(grid.west / size) * size
    lat = lat0
    while lat < grid.north:
        lon = lon0
        while lon < grid.east:
            yield (lat + size if anchor == "nw" else lat), lon
            lon += size
        lat += size


def gsw_urls(grid: Grid) -> list[str]:
    return [GSW_URL.format(lon=_hemi(lon, "E", "W"), lat=_hemi(lat, "N", "S"))
            for lat, lon in _cells(grid, 10, "nw")]


def worldcover_urls(grid: Grid) -> list[str]:
    return [WORLDCOVER_URL.format(tile=f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}")
            for lat, lon in _cells(grid, 3, "sw")]


def dem_urls(grid: Grid) -> list[str]:
    urls = []
    for lat, lon in _cells(grid, 1, "sw"):
        name = (f"Copernicus_DSM_COG_30_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
                f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM")
        urls.append(DEM_URL.format(name=name))
    return urls


def mosaic(urls: list[str], grid: Grid, resampling: Resampling, fill: float,
           src_nodata=None, dtype="float32") -> np.ndarray:
    """Warp every source onto ``grid``; GDAL only downloads the blocks it needs.

    Missing tiles (e.g. open sea has no DEM tile) are left as ``fill``."""
    out = np.full(grid.shape, fill, dtype=dtype)
    for url in urls:
        path = url if url.startswith(("/", ".")) or "://" not in url else "/vsicurl/" + url
        try:
            with rasterio.open(path) as src:
                vrt_kw = dict(crs="EPSG:4326", transform=grid.transform, width=grid.width,
                              height=grid.height, resampling=resampling, dtype=dtype, nodata=np.nan if dtype.startswith("float") else None)
                if src_nodata is not None:
                    vrt_kw["src_nodata"] = src_nodata
                with WarpedVRT(src, **vrt_kw) as vrt:
                    log.info("reading %s", url)
                    data = vrt.read(1, masked=True)
        except RasterioIOError as exc:
            log.info("skipping unavailable tile %s (%s)", url, exc)
            continue
        valid = ~np.ma.getmaskarray(data)
        if dtype.startswith("float"):
            valid &= ~np.isnan(data.filled(np.nan))
        out[valid] = data.data[valid]
    return out


class DataStore:
    """Fetches and caches the rasters for one grid."""

    def __init__(self, grid: Grid, cache_dir: str | Path = "cache"):
        self.grid = grid
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cached(self, name: str, fn):
        key = hashlib.sha1(repr(self.grid).encode()).hexdigest()[:12]
        path = self.cache_dir / f"{name}_{key}.npy"
        if path.exists():
            return np.load(path)
        arr = fn()
        np.save(path, arr)
        return arr

    def dem(self) -> np.ndarray:
        """Elevation in metres; NaN where no tile exists (sea)."""
        return self._cached("dem", lambda: mosaic(dem_urls(self.grid), self.grid, Resampling.bilinear, np.nan))

    def water_occurrence(self, source: str = "gsw") -> np.ndarray:
        """Percent of time each pixel was water (0-100)."""
        if source == "gsw":
            def fetch():
                # 255 = no observations; treat as land.
                occ = mosaic(gsw_urls(self.grid), self.grid, Resampling.average, 0.0, src_nodata=255)
                return np.clip(np.nan_to_num(occ), 0, 100).astype("float32")
            return self._cached("gsw", fetch)
        if source == "worldcover":
            def fetch():
                lc = mosaic(worldcover_urls(self.grid), self.grid, Resampling.mode, 0, src_nodata=0, dtype="uint8")
                return np.where(lc == 80, 100.0, 0.0).astype("float32")
            return self._cached("worldcover", fetch)
        raise ValueError(f"unknown water source {source!r}")
