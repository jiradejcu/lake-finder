"""Detect water bodies and measure the terrain around them."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from .geo import Grid, haversine_km


@dataclass
class Criteria:
    city_lat: float = 13.7563
    city_lon: float = 100.5018
    max_distance_km: float = 250.0     # straight-line from the city
    water_threshold: float = 50.0      # % of time water (GSW occurrence) to count as "usual" water
    min_area_km2: float = 0.3          # smallest lake/reservoir to keep
    max_area_km2: float = 3000.0       # anything larger is sea / estuary
    river_filter_px: int = 1           # morphological opening radius: removes channels ~ (2r+1) px wide
    min_relief_m: float = 250.0        # mountain must rise this much above the water surface
    mountain_search_km: float = 10.0   # look for mountains within this distance of the shore
    max_mountain_dist_km: float = 6.0  # nearest mountain-height terrain must be this close to the shore


@dataclass
class Lake:
    id: int
    area_km2: float
    lat: float
    lon: float
    distance_km: float
    surface_elev_m: float
    max_elev_m: float
    relief_m: float
    peak_lat: float
    peak_lon: float
    mountain_dist_km: float
    slices: tuple = field(repr=False, default=None)
    sites: list = field(default_factory=list)


def water_masks(occurrence: np.ndarray, dem: np.ndarray, crit: Criteria):
    """Return (usual_water, ever_water) boolean masks; sea / no-DEM pixels are removed."""
    land_or_inland = ~np.isnan(dem)
    usual = (occurrence >= crit.water_threshold) & land_or_inland
    ever = (occurrence > 0) & land_or_inland
    return usual, ever


def label_lakes(usual: np.ndarray, crit: Criteria):
    """Connected water bodies, after cutting away thin rivers and canals."""
    mask = usual
    if crit.river_filter_px > 0:
        struct = ndimage.generate_binary_structure(2, 1)
        mask = ndimage.binary_opening(usual, structure=struct, iterations=crit.river_filter_px)
    # Arms of one reservoir split by the opening are re-joined through the
    # original water mask, so each water body is reported once.
    body, _ = ndimage.label(usual, structure=np.ones((3, 3)))
    body = np.where(mask, body, 0)
    uniq, inv = np.unique(body, return_inverse=True)
    labels = inv.reshape(body.shape).astype(np.int32)
    if uniq[0] != 0:          # no background present
        labels += 1
    return labels, int(len(uniq) - (1 if uniq[0] == 0 else 0))


def find_lakes(occurrence: np.ndarray, dem: np.ndarray, grid: Grid, crit: Criteria) -> tuple[list[Lake], np.ndarray, np.ndarray]:
    """Find water bodies near the city that have mountains next to them.

    Returns (lakes, labels, usual_water_mask)."""
    usual, _ = water_masks(occurrence, dem, crit)
    labels, n = label_lakes(usual, crit)
    if n == 0:
        return [], labels, usual
    idx = np.arange(1, n + 1)
    rows_all = np.arange(grid.height)
    area_per_row = grid.pixel_area_km2(rows_all)
    area = ndimage.sum(area_per_row[:, None] * np.ones((1, grid.width)), labels, idx)
    cy, cx = np.array(ndimage.center_of_mass(labels > 0, labels, idx)).T
    clat, clon = grid.lat_of_row(cy), grid.lon_of_col(cx)
    dist = haversine_km(crit.city_lat, crit.city_lon, clat, clon)
    keep = (area >= crit.min_area_km2) & (area <= crit.max_area_km2) & (dist <= crit.max_distance_km)

    slices = ndimage.find_objects(labels)
    lakes: list[Lake] = []
    for i in np.flatnonzero(keep):
        lab = i + 1
        lake = _terrain_around(lab, slices[i], labels, dem, grid, crit)
        if lake is None:
            continue
        lake.area_km2 = float(area[i])
        lake.lat, lake.lon, lake.distance_km = float(clat[i]), float(clon[i]), float(dist[i])
        lakes.append(lake)
    return lakes, labels, usual


def _pad_slice(sl, pad, size):
    return slice(max(sl.start - pad, 0), min(sl.stop + pad, size))


def _terrain_around(lab, sl, labels, dem, grid: Grid, crit: Criteria):
    lat_mid = float(grid.lat_of_row((sl[0].start + sl[0].stop) / 2))
    dy, dx = grid.pixel_size_m(lat_mid)
    pad = int(np.ceil(crit.mountain_search_km * 1000 / dx)) + 1
    win = (_pad_slice(sl[0], pad, grid.height), _pad_slice(sl[1], pad, grid.width))
    lake = labels[win] == lab
    z = dem[win]
    lake_z = z[lake & ~np.isnan(z)]
    if lake_z.size == 0:
        return None
    # DEM over water is noisy; a low percentile tracks the water surface well.
    surface = float(np.percentile(lake_z, 25))
    if surface < 3:      # sea level -> coastal lagoon / salt pans / estuary
        return None
    dist_m = ndimage.distance_transform_edt(~lake, sampling=(dy, dx))
    near = (dist_m <= crit.mountain_search_km * 1000) & ~np.isnan(z)
    if not near.any():
        return None
    zn = np.where(near, z, -np.inf)
    pr, pc = np.unravel_index(np.argmax(zn), zn.shape)
    max_elev = float(zn[pr, pc])
    relief = max_elev - surface
    if relief < crit.min_relief_m:
        return None
    high = near & (z >= surface + crit.min_relief_m)
    mountain_dist = float(dist_m[high].min()) / 1000.0
    if mountain_dist > crit.max_mountain_dist_km:
        return None
    return Lake(
        id=int(lab), area_km2=0.0, lat=0.0, lon=0.0, distance_km=0.0,
        surface_elev_m=round(surface, 1), max_elev_m=round(max_elev, 1), relief_m=round(relief, 1),
        peak_lat=float(grid.lat_of_row(win[0].start + pr)), peak_lon=float(grid.lon_of_col(win[1].start + pc)),
        mountain_dist_km=round(mountain_dist, 2), slices=sl, sites=[],
    )
