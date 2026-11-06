"""Synthetic nadir snow scenes for SnowTrack tests.

Scenes are laid out in centimeters and rendered at a chosen ground sample
distance (GSD), so the same walk can be imaged at 6, 9 or 12 cm/px. Rendering
is supersampled and area-downsampled, then blurred, noised and JPEG
round-tripped, so prints land on sub-pixel positions with realistic softness
instead of as perfect pixel-aligned dots.
"""

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

SUPERSAMPLE = 4


@dataclass
class SnowScene:
    """A snowfield with features placed in ground coordinates (cm)."""

    width_px: int = 480
    height_px: int = 480
    gsd_cm: float = 9.0
    seed: int = 0
    snow_level: float = 222.0
    texture_sigma: float = 2.5
    drift_amplitude: float = 8.0
    noise_sigma: float = 1.5
    jpeg_quality: int = 90
    prints: list = field(default_factory=list)       # (x_cm, y_cm, diameter_cm, contrast)
    grooves: list = field(default_factory=list)      # (x0, y0, x1, y1, width_cm, contrast)
    dark_objects: list = field(default_factory=list)  # (x_cm, y_cm, radius_cm, bgr)

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)

    @property
    def width_cm(self):
        return self.width_px * self.gsd_cm

    @property
    def height_cm(self):
        return self.height_px * self.gsd_cm

    def to_px(self, points_cm):
        """Ground coordinates (cm) to pixel coordinates at this scene's GSD."""
        return np.asarray(points_cm, dtype=np.float64) / self.gsd_cm

    def add_walk(self, start_cm, heading_deg, prints, step_cm=65.0, straddle_cm=22.0,
                 step_jitter=0.05, print_diameter_cm=30.0, contrast=38.0, turn_deg_per_step=0.0):
        """Lay a left/right walking trail and return its print centers in cm.

        Args:
            start_cm: (x, y) of the trail axis at the first print.
            heading_deg: Walking direction (0 = +x, 90 = +y).
            prints: Number of prints.
            step_cm: Mean step (consecutive print) length.
            straddle_cm: Lateral distance between left and right print centers.
            step_jitter: Relative standard deviation of individual steps.
            print_diameter_cm: Posthole diameter.
            contrast: Gray levels by which the posthole center is darker than snow.
            turn_deg_per_step: Gradual heading change per step.
        """
        x, y = float(start_cm[0]), float(start_cm[1])
        heading = math.radians(heading_deg)
        centers = []
        for k in range(prints):
            side = 0.5 if k % 2 == 0 else -0.5
            lateral = side * straddle_cm + self.rng.normal(0.0, 2.0)
            px = x - math.sin(heading) * lateral
            py = y + math.cos(heading) * lateral
            diameter = print_diameter_cm * self.rng.uniform(0.85, 1.15)
            self.prints.append((px, py, diameter, contrast * self.rng.uniform(0.8, 1.1)))
            centers.append((px, py))
            step = step_cm * (1.0 + self.rng.normal(0.0, step_jitter))
            x += math.cos(heading) * step
            y += math.sin(heading) * step
            heading += math.radians(turn_deg_per_step)
        return np.asarray(centers)

    def add_clutter(self, per_square_meter, diameter_cm=(15.0, 40.0), contrast=(20.0, 45.0)):
        """Scatter print-like dark spots (debris, tussocks, animal holes) at random."""
        area_m2 = self.width_cm * self.height_cm / 1e4
        count = self.rng.poisson(per_square_meter * area_m2)
        for _ in range(count):
            self.prints.append((
                self.rng.uniform(0, self.width_cm),
                self.rng.uniform(0, self.height_cm),
                self.rng.uniform(*diameter_cm),
                self.rng.uniform(*contrast),
            ))
        return count

    def add_groove(self, start_cm, end_cm, width_cm, contrast):
        """A continuous furrow (ski track, sled run, snowmobile track, trench)."""
        self.grooves.append((start_cm[0], start_cm[1], end_cm[0], end_cm[1], width_cm, contrast))

    def add_dark_object(self, center_cm, radius_cm, bgr=(40, 70, 45)):
        """A large dark object such as a tree crown or a rock."""
        self.dark_objects.append((center_cm[0], center_cm[1], radius_cm, bgr))

    def render(self):
        """Render the scene as an 8-bit BGR image."""
        rng = self.rng
        ss = SUPERSAMPLE
        h, w = self.height_px * ss, self.width_px * ss
        cm_per_ss_px = self.gsd_cm / ss

        # Snow surface: illumination gradient, wind drifts, grain texture
        yy, xx = np.mgrid[0:self.height_px, 0:self.width_px].astype(np.float32)
        base = self.snow_level + 4.0 * (xx / self.width_px - 0.5)
        drift = cv2.GaussianBlur(rng.normal(0, 1, (self.height_px, self.width_px)).astype(np.float32), (0, 0), 12)
        drift *= self.drift_amplitude / max(float(drift.std()), 1e-6)
        grain = cv2.GaussianBlur(rng.normal(0, 1, (self.height_px, self.width_px)).astype(np.float32), (0, 0), 0.8)
        grain *= self.texture_sigma / max(float(grain.std()), 1e-6)
        surface = cv2.resize(base + drift + grain, (w, h), interpolation=cv2.INTER_LINEAR)

        darkness = np.zeros((h, w), dtype=np.float32)
        for x_cm, y_cm, diameter_cm, contrast in self.prints:
            radius = diameter_cm / 2.0 / cm_per_ss_px
            cx, cy = x_cm / cm_per_ss_px, y_cm / cm_per_ss_px
            x0, x1 = int(max(0, cx - radius - 2)), int(min(w, cx + radius + 3))
            y0, y1 = int(max(0, cy - radius - 2)), int(min(h, cy + radius + 3))
            if x0 >= x1 or y0 >= y1:
                continue
            py, px = np.mgrid[y0:y1, x0:x1].astype(np.float32)
            d2 = ((px - cx) ** 2 + (py - cy) ** 2) / max(radius * radius, 1e-6)
            # Bowl-shaped depression, deeper shadow on the sun-facing (left) wall
            bowl = np.clip(1.0 - d2, 0.0, None)
            shade = 0.75 + 0.25 * np.clip((cx - px) / max(radius, 1e-6), -1.0, 1.0)
            darkness[y0:y1, x0:x1] = np.maximum(darkness[y0:y1, x0:x1], contrast * bowl * shade)

        for x0, y0, x1, y1, width_cm, contrast in self.grooves:
            groove = np.zeros((h, w), dtype=np.float32)
            thickness = max(1, int(round(width_cm / cm_per_ss_px)))
            cv2.line(groove, (int(x0 / cm_per_ss_px), int(y0 / cm_per_ss_px)),
                     (int(x1 / cm_per_ss_px), int(y1 / cm_per_ss_px)), float(contrast), thickness)
            darkness = np.maximum(darkness, cv2.GaussianBlur(groove, (0, 0), thickness / 4.0 + 0.5))

        gray = surface - darkness
        # Snow is slightly blue, and more so inside cavities
        bgr = np.stack([gray + 4.0 + 0.05 * darkness, gray + 1.0, gray - 3.0 - 0.15 * darkness], axis=2)

        for x_cm, y_cm, radius_cm, color in self.dark_objects:
            cv2.circle(bgr, (int(x_cm / cm_per_ss_px), int(y_cm / cm_per_ss_px)),
                       int(radius_cm / cm_per_ss_px), tuple(float(c) for c in color), -1)

        img = cv2.resize(bgr, (self.width_px, self.height_px), interpolation=cv2.INTER_AREA)
        img = cv2.GaussianBlur(img, (0, 0), 0.5)  # optics
        img += rng.normal(0.0, self.noise_sigma, img.shape).astype(np.float32)
        img = np.clip(img, 0, 255).astype(np.uint8)
        ok, encoded = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        assert ok
        return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def matched_fraction(track_points_px, expected_px, tolerance_px):
    """Fraction of expected print centers that have a detected print within tolerance."""
    if len(track_points_px) == 0 or len(expected_px) == 0:
        return 0.0
    detected = np.asarray(track_points_px, dtype=np.float64)
    hits = 0
    for point in np.asarray(expected_px, dtype=np.float64):
        if np.min(np.hypot(detected[:, 0] - point[0], detected[:, 1] - point[1])) <= tolerance_px:
            hits += 1
    return hits / len(expected_px)
