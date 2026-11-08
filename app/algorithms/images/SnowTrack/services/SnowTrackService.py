"""Snow footprint track detection by gait cadence.

At the 6-12 cm/px ground sample distance (GSD) typical of search flights a
posthole is only 2-5 px across: too small to recognize as a footprint on its
own. A person walking through snow, however, leaves a *pattern* that clutter
rarely reproduces - a chain of small depressions one step apart (roughly
35-100 cm), alternating left/right inside a narrow trail, with undisturbed
snow between consecutive prints. This service looks for that pattern rather
than for individual footprints:

1. Resolve the image GSD (from metadata, or a fixed value) so every physical
   parameter - print size, step length, trail width - becomes a pixel size.
2. Build a snow mask (bright, low saturation) so trees, rock and water are
   ignored, and only consider blobs that are surrounded by snow.
3. Detect dark, roughly round, print-sized blobs with a scale-matched
   difference of Gaussians normalized by the local snow texture.
4. Link blobs into trails with a gait predictor: the next print is expected
   at the previous same-foot print plus the last stride, which follows the
   left/right zig-zag naturally. One missed print in a row is tolerated.
5. Keep trails with enough prints, a mean step inside the configured range,
   regular step lengths (cadence), a narrow lateral spread, and untrodden
   snow between consecutive prints - which rejects continuous ski, sled and
   snowmobile tracks.
6. Report each trail, split into reviewable segments, as AOIs.
"""

import math
from dataclasses import dataclass

import cv2
import numpy as np
from scipy.spatial import cKDTree

from algorithms.AlgorithmService import AlgorithmService, AnalysisResult
from core.services.LoggerService import LoggerService
from core.services.image.ImageService import ImageService
from algorithms.images.SnowTrack.services.SnowTrackOptions import (
    GSD_MODE_AUTO,
    GSD_MODE_MANUAL,
    SnowTrackParams,
)

ALGORITHM_NAME = 'SnowTrack'

# Metadata-derived GSD outside this range is treated as unreadable.
METADATA_GSD_RANGE_CM = (0.5, 50.0)

# --- Detection tuning --------------------------------------------------------
MIN_SIGMA_PX = 0.8              # smallest blob filter that is not pure pixel noise
SURROUND_RATIO = 2.0            # DoG surround / center scale ratio
SNOW_MAX_SATURATION = 80        # HSV S (0-255); shaded snow is slightly blue
SNOW_MIN_VALUE = 90             # HSV V (0-255) absolute floor for snow
SNOW_RELATIVE_VALUE = 0.55      # ... and relative to the image's bright snow level
MIN_SNOW_FRACTION = 0.02        # skip images that are essentially snow-free
MIN_LOCAL_SNOW_FRACTION = 0.6   # a print must be surrounded by mostly snow
DOG_NOISE_FLOOR = 0.5           # gray levels; keeps saturated snow from dividing by ~0
MIN_ISOTROPY = 0.15             # Hessian eigenvalue ratio; lines score ~0, round blobs ~1
MAX_CANDIDATES = 250000         # pathological-frame guard on linking cost
TILE_SIZE = 2048                # candidate detection works on tiles of this size (px)
# --- Linking tuning ------------------------------------------------------------
STEP_SLACK = 0.25               # per-step tolerance on the step window (mean is checked strictly)
STEP_RATIO_MAX = 1.5            # max ratio between the two steps of a seed triple
TOL_BASE_PX = 1.5               # prediction tolerance: localization noise at coarse GSD ...
TOL_STEP_FRACTION = 0.25        # ... plus pace variation
MAX_CONSECUTIVE_MISSES = 2      # undetected prints tolerated in a row
MAX_MISSED_FRACTION = 0.34      # undetected prints tolerated per detected print
THIRD_POINT_TRIES = 3           # seed triples traced per seed pair
MAX_CHAIN_POSITIONS = 5000      # hard stop for pathological loops
MIN_GAP_CONTRAST = 0.3          # snow between prints must be this much lighter than the prints
DENSITY_RADIUS_STEPS = 2.0      # local clutter density is measured within this many max steps of a trail
CHANCE_MARGIN = 3.0             # extra log-evidence beyond the look-elsewhere term (~5% false-trail odds)
PRINT_DETECTION_RATE = 0.8      # assumed share of a real trail's prints that are detected
SEGMENT_MAX_PRINTS = 12         # long trails are split into AOIs of at most this many prints
MIN_PRINT_RADIUS_PX = 0.75      # below this the prints are sub-pixel; warn


def snr_threshold_for_sensitivity(sensitivity):
    """Blob contrast threshold, in local-noise standard deviations.

    Args:
        sensitivity: 1 (fewest candidates) to 10 (most candidates).

    Returns:
        float: Threshold from 4.2 (sensitivity 1) through 3.4 (sensitivity 5) down to
        2.4 (sensitivity 10). Low thresholds admit noise candidates, but those raise
        the local clutter density that every trail must beat (see _beats_chance).
    """
    return 3.4 + 0.2 * (5.0 - float(sensitivity))


def _odd(value):
    """Round up to the nearest odd integer >= 1 (OpenCV kernel sizes)."""
    value = max(1, int(math.ceil(value)))
    return value if value % 2 == 1 else value + 1


@dataclass(frozen=True)
class PixelScales:
    """The physical parameters converted to pixels for one image."""

    gsd_cm: float
    print_radius: float
    sigma: float
    step_min: float
    step_max: float
    trail_width: float

    @classmethod
    def build(cls, params, gsd_cm):
        """Convert centimeter parameters to pixels at the given GSD.

        Args:
            params (SnowTrackParams): Algorithm parameters.
            gsd_cm (float): Ground sample distance at processing resolution (cm/px).

        Returns:
            PixelScales: Pixel-space sizes.
        """
        print_radius = params.print_diameter_cm / 2.0 / gsd_cm
        return cls(
            gsd_cm=gsd_cm,
            print_radius=print_radius,
            # Scale-normalized LoG/DoG peaks for a disk of radius r at sigma = r / sqrt(2)
            sigma=max(MIN_SIGMA_PX, print_radius / math.sqrt(2.0)),
            step_min=params.step_min_cm / gsd_cm,
            step_max=params.step_max_cm / gsd_cm,
            trail_width=params.max_trail_width_cm / gsd_cm,
        )


@dataclass(frozen=True)
class _FilterWindows:
    """Kernel sizes of the candidate filters, and the tile overlap that covers them."""

    noise: int
    context: int
    nms: int
    margin: int

    @classmethod
    def build(cls, scales):
        noise = _odd(np.clip(8.0 * scales.step_max, 41, 201))
        context = _odd(max(7.0, 1.5 * scales.step_max))
        nms = _odd(max(3.0, 2.0 * round(scales.print_radius) + 1.0))
        # OpenCV's float Gaussian kernels reach 4 sigma; the coarsest is 4x the print sigma.
        # Box filters reach half their window; the peak test and Hessian add a little more.
        blur_reach = 4.0 * SURROUND_RATIO * SURROUND_RATIO * scales.sigma
        margin = int(math.ceil(max(noise, context) / 2.0 + blur_reach)) + nms + 4
        return cls(noise=noise, context=context, nms=nms, margin=margin)


@dataclass
class PrintCandidates:
    """Print-sized dark blobs found in one image."""

    points: np.ndarray      # (N, 2) float64 x, y; strongest first
    snr: np.ndarray         # (N,) contrast in local-noise standard deviations
    smoothed: np.ndarray    # gray image smoothed at print scale, for gap sampling


@dataclass
class FootTrack:
    """One accepted trail of prints, in walking order."""

    positions: np.ndarray   # (N, 2) float; includes the predicted spot of a missed print
    detected: np.ndarray    # (N,) bool; False where a print was missed
    mean_step_px: float
    step_cv: float
    trail_width_px: float
    gap_contrast: float
    mean_snr: float
    confidence: float

    @property
    def prints(self):
        """(M, 2) positions of the prints that were actually detected."""
        return self.positions[self.detected]


class SnowTrackService(AlgorithmService):
    """Detects human foot-track trails in snow from the spacing, width and cadence of prints."""

    def __init__(self, identifier, min_area, max_area, aoi_radius, combine_aois, options):
        """Initialize the service.

        Args:
            identifier (tuple[int, int, int]): RGB color used to highlight AOIs.
            min_area (int): Minimum detected-pixel area of a reported track segment.
            max_area (int): Maximum detected-pixel area of a reported track segment (0 = no limit).
            aoi_radius (int): Extra radius added around each track segment.
            combine_aois (bool): When True, each trail is reported as one AOI instead of
                being split into segments of at most SEGMENT_MAX_PRINTS prints.
            options (dict): Algorithm options (keys documented in SnowTrackOptions).
        """
        self.logger = LoggerService()
        options = options if isinstance(options, dict) else {}
        super().__init__('SnowTrack', identifier, min_area, max_area, aoi_radius, combine_aois, options)
        self.params = SnowTrackParams.from_options(options)

    # ------------------------------------------------------------------ public

    def process_image(self, img, full_path, input_dir, output_dir):
        """Find foot-track trails in one image.

        Args:
            img (numpy.ndarray): Image at processing resolution (BGR, BGRA or grayscale).
            full_path (str): Path of the image being analyzed.
            input_dir (str): Base input directory.
            output_dir (str): Base output directory.

        Returns:
            AnalysisResult: Mask path and track AOIs, or an error message.
        """
        try:
            original_width = int(round(img.shape[1] / self.scale_factor)) if self.scale_factor else img.shape[1]
            gsd_cm, gsd_source = self.resolve_gsd(full_path, original_width)
            tracks = self.detect_tracks(img, gsd_cm)
            areas_of_interest, mask = self._build_aois(tracks, img.shape, gsd_cm, gsd_source)

            if not areas_of_interest:
                return AnalysisResult(full_path, None, output_dir, None, None)

            output_path = self._construct_output_path(full_path, input_dir, output_dir)
            mask_path = self.store_mask(full_path, output_path, mask)
            return AnalysisResult(full_path, mask_path, output_dir, areas_of_interest, len(areas_of_interest))

        except Exception as e:
            self.logger.error(f"{ALGORITHM_NAME} failed while analyzing {full_path}: {e}")
            return AnalysisResult(full_path, error_message=f"{ALGORITHM_NAME}: {e}")

    def resolve_gsd(self, full_path, original_width=None):
        """Ground sample distance to use for an image, at processing resolution.

        In auto mode the GSD is computed from the image's altitude and camera
        metadata; when that is unavailable (or implausible) the fixed GSD
        option is used instead. Either value describes the original image, so
        it is divided by the processing scale factor: a half-resolution pass
        sees twice as much ground per pixel.

        Args:
            full_path (str): Path of the image.
            original_width (int, optional): Pixel width of the original image,
                used to correct metadata GSD when EXIF dimensions are stale.

        Returns:
            tuple[float, str]: (GSD in cm/px at processing resolution, 'metadata' or 'manual').
        """
        gsd_cm = None
        source = GSD_MODE_MANUAL
        if self.params.gsd_mode == GSD_MODE_AUTO:
            gsd_cm = self._read_metadata_gsd(full_path, original_width)
            if gsd_cm is not None:
                source = 'metadata'
            else:
                self.logger.warning(
                    f"{ALGORITHM_NAME}: no usable GSD in the metadata of {full_path}; "
                    f"using the fixed GSD of {self.params.gsd_cm} cm/px."
                )
        if gsd_cm is None:
            gsd_cm = self.params.gsd_cm
        scale = self.scale_factor if self.scale_factor and self.scale_factor > 0 else 1.0
        return gsd_cm / scale, source

    def detect_tracks(self, img, gsd_cm):
        """Find foot-track trails in an image whose GSD is known.

        Args:
            img (numpy.ndarray): Image (BGR, BGRA or grayscale; 8-bit or wider).
            gsd_cm (float): Ground sample distance of ``img`` in cm/px.

        Returns:
            list[FootTrack]: Accepted trails, strongest seeds first.
        """
        scales = PixelScales.build(self.params, gsd_cm)
        if scales.print_radius < MIN_PRINT_RADIUS_PX:
            self.logger.warning(
                f"{ALGORITHM_NAME}: a {self.params.print_diameter_cm:g} cm print is only "
                f"{2 * scales.print_radius:.1f} px across at {gsd_cm:.1f} cm/px; detection will be unreliable. "
                f"Process at full resolution or fly lower."
            )

        bgr = self._to_bgr8(img)
        val_threshold, snow_fraction = self._snow_survey(bgr)
        if snow_fraction < MIN_SNOW_FRACTION:
            return []

        candidates = self._detect_candidates(bgr, val_threshold, scales)
        if len(candidates.points) < self.params.min_prints:
            return []
        return self._link_tracks(candidates, scales)

    # ------------------------------------------------------------- GSD source

    def _read_metadata_gsd(self, full_path, original_width=None):
        """Average GSD (cm/px) from the image's EXIF/XMP, or None when unavailable."""
        try:
            image_service = ImageService(full_path, defer_load=True)
            gsd_cm = image_service.get_average_gsd()
            exif_width = image_service.exif_data.get('Exif', {}).get(0xA002)  # PixelXDimension
        except Exception as e:
            self.logger.warning(f"{ALGORITHM_NAME}: could not read GSD metadata from {full_path}: {e}")
            return None
        if gsd_cm is None:
            return None
        try:
            gsd_cm = float(gsd_cm)
            # GSD is computed for the EXIF pixel dimensions; a resized copy with stale
            # EXIF covers the same ground with fewer pixels.
            if exif_width and original_width and int(exif_width) != int(original_width):
                gsd_cm *= float(exif_width) / float(original_width)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        lo, hi = METADATA_GSD_RANGE_CM
        if not math.isfinite(gsd_cm) or not lo <= gsd_cm <= hi:
            return None
        return gsd_cm

    # ------------------------------------------------------- print candidates

    @staticmethod
    def _to_bgr8(img):
        """Normalize any loaded image to 8-bit, 3-channel BGR."""
        if img is None or img.size == 0:
            raise ValueError("image is empty")
        if img.dtype != np.uint8:
            if np.issubdtype(img.dtype, np.integer):
                scale = 255.0 / float(np.iinfo(img.dtype).max)
            else:
                peak = float(np.nanmax(img))
                scale = 255.0 if peak <= 1.0 else 255.0 / peak
            img = np.clip(img.astype(np.float32) * scale, 0, 255).astype(np.uint8)
        if img.ndim == 2:
            return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 1:
            return cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 4:
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return img

    @staticmethod
    def _snow_survey(bgr):
        """Snow brightness threshold and snow fraction, estimated on a subsample.

        Snow is the brightest low-saturation surface in a winter scene, so the
        threshold is relative to the image's bright level; an absolute floor
        keeps a dark, snow-free frame from calling its brightest rock "snow".

        Returns:
            tuple[float, float]: (HSV value threshold, fraction of snow pixels).
        """
        hsv = cv2.cvtColor(np.ascontiguousarray(bgr[::4, ::4]), cv2.COLOR_BGR2HSV)
        bright_level = float(np.percentile(hsv[:, :, 2], 95))
        val_threshold = max(SNOW_MIN_VALUE, SNOW_RELATIVE_VALUE * bright_level)
        snow = (hsv[:, :, 2] >= val_threshold) & (hsv[:, :, 1] <= SNOW_MAX_SATURATION)
        return val_threshold, float(snow.mean())

    @staticmethod
    def _snow_mask(bgr, val_threshold):
        """uint8 mask (0/1) of bright, low-saturation pixels."""
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        return ((hsv[:, :, 2] >= val_threshold) & (hsv[:, :, 1] <= SNOW_MAX_SATURATION)).astype(np.uint8)

    def _detect_candidates(self, bgr, val_threshold, scales):
        """Dark, round, print-sized blobs surrounded by snow, found tile by tile.

        Tiles overlap by the full support of every filter, so the result is
        identical to a whole-frame pass while working memory stays bounded by
        the tile size (a whole-frame pass needs ~10 float images, over 1 GB
        on 48 MP imagery in each worker process).

        Args:
            bgr (numpy.ndarray): 8-bit BGR image.
            val_threshold (float): HSV value threshold for snow.
            scales (PixelScales): Pixel sizes for this image.

        Returns:
            PrintCandidates: Candidate print positions, strongest first.
        """
        height, width = bgr.shape[:2]
        windows = _FilterWindows.build(scales)
        smoothed_full = np.empty((height, width), dtype=np.float32)
        threshold = snr_threshold_for_sensitivity(self.params.sensitivity)
        xs_all, ys_all, snr_all = [], [], []

        for top in range(0, height, TILE_SIZE):
            for left in range(0, width, TILE_SIZE):
                bottom, right = min(height, top + TILE_SIZE), min(width, left + TILE_SIZE)
                y0, y1 = max(0, top - windows.margin), min(height, bottom + windows.margin)
                x0, x1 = max(0, left - windows.margin), min(width, right + windows.margin)
                xs, ys, snr, smoothed = self._tile_candidates(
                    bgr[y0:y1, x0:x1], val_threshold, scales, windows, threshold)
                smoothed_full[top:bottom, left:right] = smoothed[top - y0:bottom - y0, left - x0:right - x0]
                # Keep only peaks in this tile's own area; the margin belongs to neighbors
                xs, ys = xs + x0, ys + y0
                own = (xs >= left) & (xs < right) & (ys >= top) & (ys < bottom)
                xs_all.append(xs[own])
                ys_all.append(ys[own])
                snr_all.append(snr[own])

        xs = np.concatenate(xs_all)
        ys = np.concatenate(ys_all)
        strengths = np.concatenate(snr_all).astype(np.float64)
        order = np.argsort(-strengths, kind='stable')
        points = np.stack([xs[order], ys[order]], axis=1).astype(np.float64)
        strengths = strengths[order]

        # Flat-topped peaks pass the dilation test at several adjacent pixels;
        # keep only the strongest within one print radius
        keep = np.ones(len(points), dtype=bool)
        if len(points) > 1:
            pairs = cKDTree(points).query_pairs(r=max(1.0, scales.print_radius), output_type='ndarray')
            for i, j in pairs[np.argsort(pairs[:, 0], kind='stable')]:
                if keep[i]:
                    keep[j] = False
        points, strengths = points[keep], strengths[keep]

        if len(points) > MAX_CANDIDATES:
            self.logger.warning(
                f"{ALGORITHM_NAME}: {len(points)} print candidates on a {width}x{height} frame; keeping the "
                f"{MAX_CANDIDATES} strongest. Lower the sensitivity if snow texture is producing clutter."
            )
            points, strengths = points[:MAX_CANDIDATES], strengths[:MAX_CANDIDATES]
        return PrintCandidates(points=points, snr=strengths, smoothed=smoothed_full)

    def _tile_candidates(self, bgr, val_threshold, scales, windows, threshold):
        """Print candidates within one (margin-padded) tile.

        Returns:
            tuple: (xs, ys, snr) of candidates in tile coordinates, and the
            tile's luminance smoothed at print scale.
        """
        sigma = scales.sigma
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        smoothed = cv2.GaussianBlur(gray, (0, 0), sigma)
        snow = self._snow_mask(bgr, val_threshold)
        empty = np.zeros(0, dtype=np.intp)
        if not snow.any():
            return empty, empty, np.zeros(0, dtype=np.float32), smoothed

        surround = cv2.GaussianBlur(gray, (0, 0), SURROUND_RATIO * sigma)
        # Positive where the center is darker than its surround (a depression's shadow)
        dog = surround - smoothed
        # Same band-pass one octave up: larger dark objects (rocks, trees, shadows)
        # respond more strongly there than at print scale
        coarse = cv2.GaussianBlur(gray, (0, 0), SURROUND_RATIO * SURROUND_RATIO * sigma)
        del gray
        coarse -= surround
        del surround
        print_scale = dog > coarse
        del coarse

        # Normalize by the local texture of the snow itself (wind crust, sastrugi,
        # JPEG noise), estimated over snow pixels only
        snow_f = snow.astype(np.float32)
        del snow
        work = np.multiply(dog, dog)
        work *= snow_f
        noise = cv2.boxFilter(work, -1, (windows.noise, windows.noise))
        weight = cv2.boxFilter(snow_f, -1, (windows.noise, windows.noise))
        np.maximum(weight, 1e-3, out=weight)
        noise /= weight
        np.sqrt(noise, out=noise)
        np.maximum(noise, DOG_NOISE_FLOOR, out=noise)
        snr = np.divide(dog, noise, out=noise)
        del dog, weight

        cv2.boxFilter(snow_f, -1, (windows.context, windows.context), dst=work)
        in_snow = work >= MIN_LOCAL_SNOW_FRACTION
        del snow_f, work

        peaks = snr >= cv2.dilate(snr, np.ones((windows.nms, windows.nms), np.uint8))
        peaks &= snr >= threshold
        peaks &= in_snow
        peaks &= print_scale
        del in_snow, print_scale
        # The Hessian test below samples one pixel around each peak
        peaks[:2, :] = False
        peaks[-2:, :] = False
        peaks[:, :2] = False
        peaks[:, -2:] = False

        ys, xs = np.nonzero(peaks)
        isotropic = self._isotropy(smoothed, xs, ys) >= MIN_ISOTROPY
        xs, ys = xs[isotropic], ys[isotropic]
        return xs, ys, snr[ys, xs], smoothed

    @staticmethod
    def _isotropy(smoothed, xs, ys):
        """Hessian eigenvalue ratio (min/max) at each point; -1 where the point is not a dark minimum."""
        if len(xs) == 0:
            return np.zeros(0, dtype=np.float32)
        c = smoothed[ys, xs]
        dxx = smoothed[ys, xs + 1] + smoothed[ys, xs - 1] - 2.0 * c
        dyy = smoothed[ys + 1, xs] + smoothed[ys - 1, xs] - 2.0 * c
        dxy = (smoothed[ys + 1, xs + 1] - smoothed[ys + 1, xs - 1]
               - smoothed[ys - 1, xs + 1] + smoothed[ys - 1, xs - 1]) / 4.0
        half_trace = (dxx + dyy) / 2.0
        spread = np.sqrt(((dxx - dyy) / 2.0) ** 2 + dxy ** 2)
        lam_max = half_trace + spread
        lam_min = half_trace - spread
        ratio = np.full(len(xs), -1.0, dtype=np.float32)
        positive = lam_max > 1e-6
        ratio[positive] = lam_min[positive] / lam_max[positive]
        return ratio

    # ---------------------------------------------------------------- linking

    def _link_tracks(self, candidates, scales):
        """Chain candidates into gait-consistent trails.

        Args:
            candidates (PrintCandidates): Candidate prints, strongest first.
            scales (PixelScales): Pixel sizes for this image.

        Returns:
            list[FootTrack]: Accepted trails; every candidate is used by at most one.
        """
        points = candidates.points
        count = len(points)
        tree = cKDTree(points)
        step_lo = scales.step_min * (1.0 - STEP_SLACK)
        step_hi = scales.step_max * (1.0 + STEP_SLACK)

        neighbors = []
        for i, found in enumerate(tree.query_ball_point(points, r=step_hi)):
            found = np.asarray(found, dtype=np.intp)
            dist = np.hypot(points[found, 0] - points[i, 0], points[found, 1] - points[i, 1])
            neighbors.append(found[(dist >= step_lo) & (found != i)])

        # Look-elsewhere term for the chance test: every seed pair is a separate try
        seed_pairs = max(1.0, sum(len(n) for n in neighbors) / 2.0)
        context = _LinkContext(points, tree, neighbors, np.zeros(count, dtype=bool), step_lo, step_hi, seed_pairs)
        tracks = []
        # Candidates are sorted strongest first, so seeds are tried in order of evidence
        for i in range(count):
            if context.used[i]:
                continue
            for j in neighbors[i]:
                if j <= i or context.used[j]:
                    continue
                track = self._trace_seed(i, j, candidates, scales, context)
                if track is None:
                    track = self._trace_seed(j, i, candidates, scales, context)
                if track is not None:
                    tracks.append(track)
                    break
        return tracks

    def _trace_seed(self, a, b, candidates, scales, context):
        """Grow and validate the best trail through the seed step a -> b, marking its prints used."""
        best = None
        best_ids = None
        for c in self._seed_third_points(a, b, scales, context)[:THIRD_POINT_TRIES]:
            positions = [context.points[a], context.points[b], context.points[c]]
            ids = [a, b, c]
            self._extend(positions, ids, context)
            positions.reverse()
            ids.reverse()
            self._extend(positions, ids, context)
            track = self._evaluate(np.asarray(positions), np.asarray(ids), candidates, scales, context)
            if track is not None and (best is None or len(track.prints) > len(best.prints)):
                best, best_ids = track, ids
        if best is not None:
            used_ids = np.asarray([i for i in best_ids if i >= 0], dtype=np.intp)
            context.used[used_ids] = True
        return best

    def _seed_third_points(self, a, b, scales, context):
        """Third prints c that make (a, b, c) a plausible left/right/left (or right/left/right) triple.

        A walker's middle print sits beside the line joining the prints before
        and after it, roughly half way along, at a lateral offset no larger
        than the trail width, and the two steps are of similar length.

        Returns:
            list[int]: Candidate indices, most gait-like first.
        """
        cs = context.neighbors[b]
        cs = cs[(cs != a) & ~context.used[cs]]
        if len(cs) == 0:
            return []
        pa = context.points[a]
        pb = context.points[b]
        pc = context.points[cs]
        ab = pb - pa
        ac = pc - pa
        len_ab = float(np.hypot(*ab))
        len_bc = np.hypot(pc[:, 0] - pb[0], pc[:, 1] - pb[1])
        len_ac = np.hypot(ac[:, 0], ac[:, 1])
        valid = (len_ac > 1e-6) & (len_ab > 1e-6)
        len_ac_safe = np.where(valid, len_ac, 1.0)
        ratio = len_bc / max(len_ab, 1e-6)
        straddle = np.abs(ac[:, 0] * ab[1] - ac[:, 1] * ab[0]) / len_ac_safe
        along = (ab[0] * ac[:, 0] + ab[1] * ac[:, 1]) / (len_ac_safe ** 2)
        valid &= (ratio >= 1.0 / STEP_RATIO_MAX) & (ratio <= STEP_RATIO_MAX)
        valid &= straddle <= scales.trail_width + TOL_BASE_PX
        valid &= (along >= 0.25) & (along <= 0.75)
        if not valid.any():
            return []
        score = straddle / max(scales.trail_width, 1.0) + np.abs(np.log(np.maximum(ratio, 1e-6)))
        order = np.argsort(score[valid], kind='stable')
        return cs[valid][order].tolist()

    @staticmethod
    def _extend(positions, ids, context):
        """Extend a chain forward with the gait predictor, in place.

        The next print is expected at the previous same-foot print plus the
        last stride: ``p[k+1] ~ p[k-1] + (p[k] - p[k-2])``. A missed print is
        bridged by its predicted position (id -1) at most
        MAX_CONSECUTIVE_MISSES times in a row; trailing misses are trimmed.
        """
        in_chain = set(i for i in ids if i >= 0)
        misses = 0
        while len(positions) < MAX_CHAIN_POSITIONS:
            p3, p2, p1 = positions[-3], positions[-2], positions[-1]
            predicted = p2 + (p1 - p3)
            recent = np.diff(np.asarray(positions[-5:]), axis=0)
            step_estimate = float(np.mean(np.hypot(recent[:, 0], recent[:, 1])))
            tolerance = TOL_BASE_PX + TOL_STEP_FRACTION * step_estimate

            found = np.asarray(context.tree.query_ball_point(predicted, r=tolerance), dtype=np.intp)
            best = None
            if len(found):
                found = found[~context.used[found]]
                found = np.asarray([i for i in found if i not in in_chain], dtype=np.intp)
            if len(found):
                step = np.hypot(context.points[found, 0] - p1[0], context.points[found, 1] - p1[1])
                found = found[(step >= context.step_lo) & (step <= context.step_hi)]
            if len(found):
                miss = np.hypot(context.points[found, 0] - predicted[0], context.points[found, 1] - predicted[1])
                best = int(found[int(np.argmin(miss))])

            if best is not None:
                positions.append(context.points[best])
                ids.append(best)
                in_chain.add(best)
                misses = 0
            elif misses < MAX_CONSECUTIVE_MISSES:
                positions.append(predicted)
                ids.append(-1)
                misses += 1
            else:
                break
        while ids and ids[-1] < 0:
            ids.pop()
            positions.pop()

    def _evaluate(self, positions, ids, candidates, scales, context):
        """Accept or reject a traced chain against the gait criteria.

        Returns:
            FootTrack or None: The track with its statistics and confidence, or None if rejected.
        """
        detected = ids >= 0
        detected_count = int(detected.sum())
        if detected_count < self.params.min_prints:
            return None
        if int((~detected).sum()) > MAX_MISSED_FRACTION * detected_count:
            return None

        steps = np.hypot(*np.diff(positions, axis=0).T)
        mean_step = float(steps.mean())
        if not scales.step_min <= mean_step <= scales.step_max:
            return None
        step_cv = float(steps.std() / mean_step)
        if step_cv > self.params.max_step_variation:
            return None

        # Straddle: each print's offset from the line joining its neighbors
        before, middle, after = positions[:-2], positions[1:-1], positions[2:]
        span = after - before
        span_len = np.maximum(np.hypot(span[:, 0], span[:, 1]), 1e-6)
        offsets = np.abs(span[:, 0] * (middle - before)[:, 1] - span[:, 1] * (middle - before)[:, 0]) / span_len
        trail_width = float(np.median(offsets))
        if trail_width > scales.trail_width:
            return None

        gap_contrast = self._gap_contrast(positions, detected, candidates.smoothed, scales, mean_step, trail_width)
        if gap_contrast < MIN_GAP_CONTRAST:
            return None

        if not self._beats_chance(positions, ids, detected, mean_step, scales, context):
            return None

        mean_snr = float(np.mean(candidates.snr[ids[detected]]))
        threshold = snr_threshold_for_sensitivity(self.params.sensitivity)
        length_score = min(1.0, detected_count / (3.0 * self.params.min_prints))
        regularity_score = max(0.0, 1.0 - step_cv / self.params.max_step_variation)
        gap_score = min(1.0, gap_contrast)
        contrast_score = min(1.0, mean_snr / (3.0 * threshold))
        confidence = 100.0 * (0.30 * length_score + 0.25 * regularity_score
                              + 0.25 * gap_score + 0.20 * contrast_score)

        return FootTrack(
            positions=positions,
            detected=detected,
            mean_step_px=mean_step,
            step_cv=step_cv,
            trail_width_px=trail_width,
            gap_contrast=gap_contrast,
            mean_snr=mean_snr,
            confidence=round(confidence, 1),
        )

    @staticmethod
    def _beats_chance(positions, ids, detected, mean_step, scales, context):
        """Whether the chain is too unlikely to have been assembled from random clutter.

        Each print after the seed triple was found inside a prediction window
        of radius ``tol``. If candidates around the trail were scattered at
        random with local density ``rho``, a window would contain one by
        chance with probability ``p = 1 - exp(-rho * pi * tol^2)``, whereas a
        real trail fills it with probability ``q`` (PRINT_DETECTION_RATE). The
        log-likelihood ratio - ``ln(q/p)`` per found print, ``ln((1-q)/(1-p))``
        per bridged miss - must exceed the look-elsewhere term
        ``ln(number of seeds tried)`` plus a margin. In clean snow ``p`` is tiny and a handful of prints is
        decisive; in a dense debris field the same chain is unremarkable and
        needs many more regular prints. Noise candidates raised by a high
        sensitivity raise ``rho`` too, so the test tightens on its own.

        Returns:
            bool: True when the chain is significant.
        """
        prints = positions[detected]
        chain_ids = set(int(i) for i in ids[detected])
        radius = DENSITY_RADIUS_STEPS * scales.step_max
        nearby = set()
        for found in context.tree.query_ball_point(prints, r=radius):
            nearby.update(found)
        clutter = len(nearby - chain_ids)
        path_length = float(np.sum(np.hypot(*np.diff(positions, axis=0).T)))
        # Area of the band around the trail where clutter was counted
        band_area = math.pi * radius * radius + 2.0 * radius * path_length
        density = clutter / band_area

        tolerance = TOL_BASE_PX + TOL_STEP_FRACTION * mean_step
        chance = -math.expm1(-density * math.pi * tolerance * tolerance)  # 1 - exp(-lambda)
        if chance <= 0.0:
            return True
        chance = min(chance, PRINT_DETECTION_RATE)
        # Log-likelihood ratio, trail vs. clutter: a found print favors a trail by
        # q/p, a bridged miss favors clutter by (1-p)/(1-q)
        found = len(prints) - 3
        missed = int((~detected).sum())
        evidence = (found * math.log(PRINT_DETECTION_RATE / chance)
                    + missed * math.log((1.0 - PRINT_DETECTION_RATE) / (1.0 - chance)))
        return evidence >= math.log(context.seed_pairs) + CHANCE_MARGIN

    @staticmethod
    def _gap_contrast(positions, detected, smoothed, scales, mean_step, trail_width):
        """How much lighter the snow between consecutive prints is than the prints.

        For each pair of consecutive detected prints, compares the brightness
        half way between them with the prints themselves and with untrodden
        snow beside the trail: ``(mid - prints) / (beside - prints)``. Discrete
        prints score near 1; a continuous furrow (ski, sled, snowmobile, or a
        trench) scores near 0.

        Returns:
            float: Median ratio over all consecutive detected pairs (0 when none).
        """
        pair = detected[:-1] & detected[1:]
        if not pair.any():
            return 0.0
        side = max(2.0 * scales.print_radius, 0.5 * mean_step) + 0.5 * trail_width
        first = positions[:-1][pair]
        second = positions[1:][pair]
        mid = (first + second) / 2.0
        normal = _unit_normals(second - first)
        print_level = (_sample(smoothed, first) + _sample(smoothed, second)) / 2.0
        mid_level = _sample(smoothed, mid)
        snow_level = (_sample(smoothed, mid + normal * side) + _sample(smoothed, mid - normal * side)) / 2.0
        depth = snow_level - print_level
        ratio = np.where(depth > 1e-3, (mid_level - print_level) / np.maximum(depth, 1e-3), 0.0)
        return float(np.median(ratio))

    # ------------------------------------------------------------------- AOIs

    def _build_aois(self, tracks, shape, gsd_cm, gsd_source):
        """Turn accepted trails into AOI dictionaries and a detection mask.

        Long trails are split into segments of at most SEGMENT_MAX_PRINTS
        prints so each AOI frames a reviewable stretch of trail (unless
        combine_aois is set). Each segment's detected pixels are the print
        disks; the contour is their convex hull.

        Returns:
            tuple[list | None, numpy.ndarray]: (AOIs at processing resolution or None, uint8 mask).
        """
        height, width = int(shape[0]), int(shape[1])
        mask = np.zeros((height, width), dtype=np.uint8)
        if not tracks:
            return None, mask

        scales = PixelScales.build(self.params, gsd_cm)
        disk_radius = max(1, int(round(scales.print_radius)))
        dy, dx = np.mgrid[-disk_radius:disk_radius + 1, -disk_radius:disk_radius + 1]
        inside = dx * dx + dy * dy <= disk_radius * disk_radius
        disk = np.stack([dx[inside], dy[inside]], axis=1)
        original_gsd = gsd_cm * (self.scale_factor or 1.0)

        areas_of_interest = []
        for track in tracks:
            prints = track.prints
            segment_count = 1 if self.combine_aois else int(math.ceil(len(prints) / SEGMENT_MAX_PRINTS))
            track_info = {
                'prints': int(len(prints)),
                'missed_prints': int((~track.detected).sum()),
                'mean_step_cm': round(track.mean_step_px * gsd_cm, 1),
                'step_variation_pct': round(track.step_cv * 100.0, 1),
                'trail_width_cm': round(track.trail_width_px * gsd_cm, 1),
                'gap_contrast': round(track.gap_contrast, 2),
                'gsd_cm': round(original_gsd, 2),
                'gsd_source': gsd_source,
            }
            for segment in np.array_split(prints, segment_count):
                pixels = (np.rint(segment).astype(np.int32)[:, None, :] + disk[None, :, :]).reshape(-1, 2)
                in_frame = (pixels[:, 0] >= 0) & (pixels[:, 0] < width) & (pixels[:, 1] >= 0) & (pixels[:, 1] < height)
                pixels = np.unique(pixels[in_frame], axis=0)
                area = int(len(pixels))
                if area == 0 or area < self.min_area or (self.max_area > 0 and area > self.max_area):
                    continue

                (cx, cy), enclosing = cv2.minEnclosingCircle(segment.astype(np.float32).reshape(-1, 1, 2))
                hull = cv2.convexHull(pixels.reshape(-1, 1, 2)).reshape(-1, 2)
                mask[pixels[:, 1], pixels[:, 0]] = 255
                areas_of_interest.append({
                    'center': (int(round(cx)), int(round(cy))),
                    'radius': int(math.ceil(enclosing)) + disk_radius + self.aoi_radius,
                    'area': area,
                    'contour': hull.tolist(),
                    'detected_pixels': pixels.tolist(),
                    'confidence': track.confidence,
                    'score_type': 'track_cadence',
                    'raw_score': track_info['mean_step_cm'],
                    'score_method': 'mean_step_cm',
                    'track': dict(track_info, segment_prints=int(len(segment))),
                })

        if not areas_of_interest:
            return None, mask
        areas_of_interest.sort(key=lambda item: (item['center'][1], item['center'][0]))
        return areas_of_interest, mask


@dataclass
class _LinkContext:
    """Shared state while linking one image's candidates."""

    points: np.ndarray
    tree: cKDTree
    neighbors: list
    used: np.ndarray
    step_lo: float
    step_hi: float
    seed_pairs: float


def _unit_normals(vectors):
    """Unit vectors perpendicular to each (dx, dy) row."""
    length = np.maximum(np.hypot(vectors[:, 0], vectors[:, 1]), 1e-6)
    return np.stack([-vectors[:, 1] / length, vectors[:, 0] / length], axis=1)


def _sample(image, points):
    """Bilinear samples of a 2-D float image at (x, y) points, clamped to the frame."""
    height, width = image.shape
    x = np.clip(points[:, 0], 0, width - 1.001)
    y = np.clip(points[:, 1], 0, height - 1.001)
    x0 = np.floor(x).astype(np.intp)
    y0 = np.floor(y).astype(np.intp)
    fx = x - x0
    fy = y - y0
    top = image[y0, x0] * (1 - fx) + image[y0, x0 + 1] * fx
    bottom = image[y0 + 1, x0] * (1 - fx) + image[y0 + 1, x0 + 1] * fx
    return top * (1 - fy) + bottom * fy
