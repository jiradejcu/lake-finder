"""Find house sites on a lake shore with a view across the water to mountains.

For each candidate shore pixel we cast sight lines in many compass directions
and look at the terrain profile along each one:

    house ── water (foreground) ── far shore ── mountain (skyline)

A direction counts as a *lake-with-mountain view* when

1. the line reaches open water within ``max_shore_gap_m`` (the house faces the lake),
2. at least ``min_water_m`` of the line is over water before the skyline point,
3. the skyline point (the terrain with the highest elevation angle seen from the
   house, i.e. what is visible on the horizon) rises ``min_relief_m`` above the
   lake surface and appears at least ``min_angle_deg`` above the horizontal.

Candidate sites must be buildable: never flooded in the satellite record
(outside the reservoir's maximum extent), gentle slope and not much higher than
the water (so you are actually *at* the water side).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from .analysis import Lake, _pad_slice
from .geo import EARTH_RADIUS_KM, Grid, haversine_km

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(bearing: float) -> str:
    return COMPASS[int((bearing % 360) / 22.5 + 0.5) % 16]


@dataclass
class ViewCriteria:
    view_range_km: float = 15.0
    n_bearings: int = 36
    eye_height_m: float = 5.0          # 2nd-floor balcony
    max_shore_gap_m: float = 300.0
    min_water_m: float = 500.0
    min_relief_m: float = 250.0
    min_angle_deg: float = 1.5
    max_slope_deg: float = 10.0
    max_height_above_water_m: float = 40.0
    max_candidates: int = 600
    sites_per_lake: int = 3
    min_site_separation_km: float = 1.5


@dataclass
class Site:
    lat: float
    lon: float
    elev_m: float
    height_above_water_m: float
    slope_deg: float
    score: float
    view_width_deg: float
    best_bearing_deg: float
    best_direction: str
    water_width_m: float
    mountain_lat: float
    mountain_lon: float
    mountain_elev_m: float
    mountain_dist_km: float
    mountain_angle_deg: float


def slope_deg(z: np.ndarray, dy: float, dx: float) -> np.ndarray:
    gy, gx = np.gradient(np.nan_to_num(z, nan=0.0), dy, dx)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


@dataclass
class Views:
    """Sight-line results for C viewpoints x B bearings."""
    d: np.ndarray
    bearings: np.ndarray
    ri: np.ndarray
    ci: np.ndarray
    sky: np.ndarray
    sky_angle: np.ndarray
    sky_z: np.ndarray
    water_m: np.ndarray
    faces_water: np.ndarray
    good: np.ndarray
    dir_score: np.ndarray
    score: np.ndarray


def cast_views(z: np.ndarray, water: np.ndarray, cr: np.ndarray, cc: np.ndarray, level: float,
               dy: float, dx: float, vc: ViewCriteria) -> Views:
    """Cast sight lines from pixels (cr, cc) of ``z`` and classify each direction.

    ``level`` is the water surface elevation used for the mountain-height test."""
    # --- cast sight lines --------------------------------------------------
    step_m = min(dx, dy)
    d = np.arange(1, int(vc.view_range_km * 1000 / step_m) + 1) * step_m          # (S,)
    bearings = np.arange(vc.n_bearings) * (360.0 / vc.n_bearings)                 # (B,)
    br = np.radians(bearings)
    rr = cr[:, None, None] - (np.cos(br)[None, :, None] * d[None, None, :]) / dy  # (C,B,S)
    cc_ = cc[:, None, None] + (np.sin(br)[None, :, None] * d[None, None, :]) / dx
    ri, ci = np.rint(rr).astype(int), np.rint(cc_).astype(int)
    inside = (ri >= 0) & (ri < z.shape[0]) & (ci >= 0) & (ci < z.shape[1])
    ri, ci = np.clip(ri, 0, z.shape[0] - 1), np.clip(ci, 0, z.shape[1] - 1)

    zr = np.where(inside, z[ri, ci], np.nan)
    wr = inside & water[ri, ci]
    site_z = z[cr, cc][:, None, None]
    eye = site_z + vc.eye_height_m
    curvature = (d ** 2) / (2 * EARTH_RADIUS_KM * 1000) * 0.87                    # with refraction
    angle = np.degrees(np.arctan2(np.nan_to_num(zr, nan=-1e4) - curvature - eye, d))
    sky = np.argmax(angle, axis=2)                                                 # skyline index (C,B)
    sky_angle = np.take_along_axis(angle, sky[..., None], 2)[..., 0]
    sky_z = np.take_along_axis(zr, sky[..., None], 2)[..., 0]

    gap = int(np.ceil(vc.max_shore_gap_m / step_m))
    faces_water = wr[:, :, :gap].any(axis=2)
    before_sky = np.arange(d.size)[None, None, :] < sky[..., None]
    water_m = (wr & before_sky).sum(axis=2) * step_m
    good = (faces_water & (water_m >= vc.min_water_m) & (sky_z - level >= vc.min_relief_m)
            & (sky_angle >= vc.min_angle_deg))

    # Score: angular width of the view, weighted by how tall the mountains look.
    dir_score = np.where(good, np.minimum(sky_angle, 15.0), 0.0)
    score = dir_score.sum(axis=1) * (360.0 / vc.n_bearings) / 10.0
    return Views(d, bearings, ri, ci, sky, sky_angle, sky_z, water_m, faces_water, good, dir_score, score)


def find_sites(lake: Lake, labels: np.ndarray, usual_water: np.ndarray, ever_water: np.ndarray,
               dem: np.ndarray, grid: Grid, vc: ViewCriteria) -> list[Site]:
    sl = lake.slices
    lat_mid = float(grid.lat_of_row((sl[0].start + sl[0].stop) / 2))
    dy, dx = grid.pixel_size_m(lat_mid)
    pad = int(np.ceil(vc.view_range_km * 1000 / min(dx, dy))) + 2
    win = (_pad_slice(sl[0], pad, grid.height), _pad_slice(sl[1], pad, grid.width))
    r0, c0 = win[0].start, win[1].start
    z = dem[win]
    water = usual_water[win]
    lake_mask = labels[win] == lake.id
    level = lake.surface_elev_m

    # --- candidate house sites: dry land right next to this lake ------------
    # The reservoir's maximum extent (draw-down zone included) is never a house site.
    ever = ever_water[win]
    ever_lab, _ = ndimage.label(ever | lake_mask, structure=np.ones((3, 3)))
    extent = np.isin(ever_lab, np.unique(ever_lab[lake_mask]))
    shore = ndimage.binary_dilation(extent, iterations=2) & ~extent
    # A shore pixel belongs to whichever lake is closest.
    others = (labels[win] > 0) & ~lake_mask
    if others.any():
        shore &= (ndimage.distance_transform_edt(~lake_mask, sampling=(dy, dx))
                  <= ndimage.distance_transform_edt(~others, sampling=(dy, dx)))
    slope = slope_deg(z, dy, dx)
    cand = (shore & ~ever & ~np.isnan(z) & (slope <= vc.max_slope_deg)
            & (z - level <= vc.max_height_above_water_m) & (z - level >= 0))
    cr, cc = np.nonzero(cand)
    if cr.size == 0:
        return []
    if cr.size > vc.max_candidates:
        pick = np.linspace(0, cr.size - 1, vc.max_candidates).astype(int)
        cr, cc = cr[pick], cc[pick]

    v = cast_views(z, water, cr, cc, level, dy, dx, vc)
    d, bearings, ri, ci = v.d, v.bearings, v.ri, v.ci
    sky, sky_angle, sky_z, water_m, good, dir_score, score = (
        v.sky, v.sky_angle, v.sky_z, v.water_m, v.good, v.dir_score, v.score)
    order = np.argsort(-score)

    sites: list[Site] = []
    for k in order:
        if score[k] <= 0 or len(sites) >= vc.sites_per_lake:
            break
        lat = float(grid.lat_of_row(r0 + cr[k]))
        lon = float(grid.lon_of_col(c0 + cc[k]))
        if any(haversine_km(lat, lon, s.lat, s.lon) < vc.min_site_separation_km for s in sites):
            continue
        b = int(np.argmax(dir_score[k]))
        s_idx = sky[k, b]
        sites.append(Site(
            lat=round(lat, 5), lon=round(lon, 5),
            elev_m=round(float(z[cr[k], cc[k]]), 1),
            height_above_water_m=round(float(z[cr[k], cc[k]] - level), 1),
            slope_deg=round(float(slope[cr[k], cc[k]]), 1),
            score=round(float(score[k]), 1),
            view_width_deg=float(good[k].sum() * 360.0 / vc.n_bearings),
            best_bearing_deg=float(bearings[b]), best_direction=compass(bearings[b]),
            water_width_m=round(float(water_m[k, b])),
            mountain_lat=round(float(grid.lat_of_row(r0 + ri[k, b, s_idx])), 5),
            mountain_lon=round(float(grid.lon_of_col(c0 + ci[k, b, s_idx])), 5),
            mountain_elev_m=round(float(sky_z[k, b]), 0),
            mountain_dist_km=round(float(d[s_idx]) / 1000, 2),
            mountain_angle_deg=round(float(sky_angle[k, b]), 1),
        ))
    return sites
