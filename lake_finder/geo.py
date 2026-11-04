"""Small geodesy helpers and the analysis grid definition."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from rasterio.transform import Affine

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km (works with scalars or numpy arrays)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


@dataclass(frozen=True)
class Grid:
    """A regular lat/lon grid (EPSG:4326). Row 0 is the northern edge."""

    west: float
    north: float
    res_deg: float
    width: int
    height: int

    @classmethod
    def around(cls, lat: float, lon: float, radius_km: float, res_arcsec: float = 3.0) -> "Grid":
        res = res_arcsec / 3600.0
        dlat = radius_km / 111.32
        dlon = radius_km / (111.32 * math.cos(math.radians(lat)))
        # Snap to the resolution so tiles line up with the DEM's native 3" grid.
        west = math.floor((lon - dlon) / res) * res
        north = math.ceil((lat + dlat) / res) * res
        east = math.ceil((lon + dlon) / res) * res
        south = math.floor((lat - dlat) / res) * res
        return cls(west, north, res, int(round((east - west) / res)), int(round((north - south) / res)))

    @property
    def east(self) -> float:
        return self.west + self.width * self.res_deg

    @property
    def south(self) -> float:
        return self.north - self.height * self.res_deg

    @property
    def transform(self) -> Affine:
        return Affine(self.res_deg, 0, self.west, 0, -self.res_deg, self.north)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    def lat_of_row(self, row):
        return self.north - (np.asarray(row) + 0.5) * self.res_deg

    def lon_of_col(self, col):
        return self.west + (np.asarray(col) + 0.5) * self.res_deg

    def pixel_size_m(self, lat: float) -> tuple[float, float]:
        """(dy, dx) of one pixel in metres at the given latitude."""
        dy = self.res_deg * 111_320.0
        return dy, dy * math.cos(math.radians(lat))

    def pixel_area_km2(self, rows) -> np.ndarray:
        dy, _ = self.pixel_size_m(0)
        return (dy * dy * np.cos(np.radians(self.lat_of_row(rows)))) / 1e6
