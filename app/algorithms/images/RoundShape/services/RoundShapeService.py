"""
RoundShapeService.py - detects round and oval objects, and arcs of them, of a known physical size.

Flags hats, helmets, buckets, life rings, tires, umbrellas and dome tents by
geometry rather than colour: a curved outline of the right physical
diameter, whole (a circle or an oval) or partly hidden (an arc), scored on
size, edge support, ring contrast, roundness and how far its edge stands
above the ground's texture. Per-image GSD turns the physical size range
into pixels, which bounds the radii searched and is what makes the search
tractable.

A whole outline must be supported most of the way round; a partly hidden
one (a tire half under brush, a tent cut by the frame edge) is reported
when one unbroken arc of at least ``min_arc_degrees`` shows. Both must
really curve: straight edges an ellipse happens to graze, as along a
suitcase or a trail, are rejected (see RoundGeometry.outline_support).

The curved counterpart of RectilinearShapeService. The geometry lives in
algorithms.Shared.services.RoundGeometry; this service only orchestrates it.
"""

import math
import os
from pathlib import Path

import cv2
import numpy as np

from algorithms.AlgorithmService import AlgorithmService, AnalysisResult
from algorithms.Shared.services import RoundGeometry as geometry
from algorithms.images.RoundShape.services.RoundPresets import normalize_options
from core.services.LoggerService import LoggerService


# Gaussian sigma for the pre-blur. Suppresses JPEG 8x8 block edges and
# single-pixel noise before edges are traced.
_PRE_BLUR_SIGMA = 0.8

# Symmetry-map peak threshold (see RoundGeometry.radial_symmetry_map: about 1
# for a full circle at the reference contrast) and the cap on peaks fitted.
_MIN_SYMMETRY = 0.25
_MAX_PEAKS = 400

# Symmetry grid: the decimated map keeps at least this many cells across
# the smallest expected radius.
_SYMMETRY_CELLS_PER_MIN_RADIUS = 4

# A closed outline may have no unsupported stretch longer than this
# (degrees of the outline); anything more broken must qualify as an arc.
_MAX_CLOSED_GAP_DEG = 60.0

# Roundness gates: the supported outline must curve with the model
# (curvature agreement, 1 = fully) and must not be a box's four sides.
_MIN_CURVATURE = 0.6
_MAX_BOXINESS = 0.45

# Suppression: IoU, and the share of the smaller ellipse lying inside the
# larger, above which the weaker of two hypotheses is dropped.
_NMS_IOU = 0.3
_NMS_CONTAINMENT = 0.8

# Ring width around a hypothesis for the contrast test, as a fraction of its minor axis.
_RING_FRACTION = 0.3

# Delta E at which the contrast score reaches 0.9 (saturating curve).
_CONTRAST_DELTA_E_AT_0_9 = 15.0

# Fused-confidence exponents (initial values; to be tuned with field data).
_EXP_SIZE = 0.35
_EXP_EDGE = 0.35
_EXP_CONTRAST = 0.15
_EXP_ROUNDNESS = 0.15
_EXP_SALIENCE = 0.25

# Floor on the roundness and salience terms, so one weak term damps a
# hypothesis rather than vetoing it.
_TERM_FLOOR = 0.05

# Hypotheses whose size score falls below this are not scored further.
_MIN_SIZE_SCORE = 0.05

# Camera tilt from nadir above which GSD varies enough across the frame that
# the size tolerance is widened by the top/bottom GSD ratio.
_OBLIQUE_TILT_DEG = 10.0

# Outline kinds.
_CLOSED = 'closed'
_ARC = 'arc'


class RoundShapeService(AlgorithmService):
    """Image algorithm that detects round and oval objects, and arcs of them, of a known physical size.

    Attributes:
        settings (dict): Normalised options (every key in DEFAULT_OPTIONS).
        batch_min_area (int): Global minimum AOI area from the batch, kept
            only to report when it disagrees with the size gate.
        batch_max_area (int): Global maximum AOI area from the batch, likewise.
    """

    def __init__(self, identifier, min_area, max_area, aoi_radius, combine_aois, options):
        """Initialize the service.

        Args:
            identifier: RGB values for the color to highlight areas of interest.
            min_area: Batch minimum AOI area in pixels (diagnostic only, see below).
            max_area: Batch maximum AOI area in pixels (diagnostic only, see below).
            aoi_radius: Radius added to the minimum enclosing circle around an AOI.
            combine_aois: If True, overlapping AOIs are combined.
            options: Algorithm options; missing keys take their defaults.
        """
        self.logger = LoggerService()
        super().__init__('RoundShape', identifier, min_area, max_area, aoi_radius, combine_aois, options)
        self.settings = normalize_options(options)
        # The physical-size gate is this algorithm's size filter, as in
        # RectilinearShape: the batch limits from the guide's Target Size
        # page cannot express a preset, so they are kept for diagnostics
        # and identify_areas_of_interest is run unbounded.
        self.batch_min_area = min_area
        self.batch_max_area = max_area
        self.min_area = 0
        self.max_area = 0

    def process_image(self, img, full_path, input_dir, output_dir):
        """Detect round, oval and arc targets in one image.

        Args:
            img (np.ndarray): BGR image at processing resolution.
            full_path (str): Path to the image being analysed.
            input_dir (str): Base input folder.
            output_dir (str): Base output folder.

        Returns:
            AnalysisResult: AOIs carry ``confidence`` (0-100) and
            ``score_type = 'shape'``; ``error_message`` is set when the image
            has no usable GSD or processing failed.
        """
        try:
            bgr = self._to_bgr8(img)
            gsd_cm, gsd_service = self._resolve_gsd_cm(bgr, full_path)
            if gsd_cm is None or gsd_cm <= 0:
                message = (
                    f"RoundShape: no ground sample distance for {full_path} "
                    "(missing altitude or camera metadata) and no fallback GSD is set"
                )
                self.logger.warning(message)
                return AnalysisResult(full_path, error_message=message)

            settings = self.settings
            tolerance = self._effective_tolerance(settings['size_tolerance'], gsd_service, full_path)
            long_min_px = settings['long_diameter_cm_min'] / gsd_cm
            long_max_px = settings['long_diameter_cm_max'] / gsd_cm
            short_min_px = settings['short_diameter_cm_min'] / gsd_cm
            short_max_px = settings['short_diameter_cm_max'] / gsd_cm
            self.logger.debug(
                f"RoundShape: {full_path} effective GSD {gsd_cm:.2f} cm/px, "
                f"short diameter {short_min_px:.1f}-{short_max_px:.1f} px, "
                f"long diameter {long_min_px:.1f}-{long_max_px:.1f} px"
            )
            if short_min_px < settings['min_diameter_px']:
                self.logger.warning(
                    f"RoundShape: skipped {full_path} - the smallest target diameter is "
                    f"{short_min_px:.1f} px at {gsd_cm:.2f} cm/px (processing scale {self.scale_factor:.2f}), "
                    f"below the {settings['min_diameter_px']} px floor. Raise the processing resolution."
                )
                return self._empty_result(full_path, output_dir)

            ellipses, scores, debug_layers = self._detect(bgr, gsd_cm, tolerance, (short_min_px, long_max_px))

            contours = [self._contour_in_frame(e, bgr.shape) for e in ellipses]
            areas_of_interest, base_contour_count = self.identify_areas_of_interest(bgr.shape, contours)
            if areas_of_interest:
                self._attach_scores(areas_of_interest, ellipses, scores)
                self._report_batch_area_disagreement(areas_of_interest, full_path)

            if settings['debug_output']:
                self._write_debug_overlay(bgr, full_path, output_dir, debug_layers, ellipses, scores)

            mask_path = None
            if areas_of_interest:
                mask = np.zeros(bgr.shape[:2], dtype=np.uint8)
                for contour in contours:
                    cv2.fillPoly(mask, [contour], 255)
                output_path = self._construct_output_path(full_path, input_dir, output_dir)
                mask_path = self.store_mask(full_path, output_path, mask)

            return AnalysisResult(full_path, mask_path, output_dir, areas_of_interest, base_contour_count)

        except Exception as e:
            # LoggerService.error appends the traceback itself inside an except block.
            self.logger.error(f"RoundShape failed for {full_path}: {e}")
            return AnalysisResult(full_path, error_message=f"RoundShape failed for {full_path}: {e}")

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    @staticmethod
    def _to_bgr8(img):
        """Normalise the decoded frame to 3-channel uint8 BGR.

        AnalyzeService decodes with IMREAD_UNCHANGED, so the frame may carry
        alpha, be 16-bit, or be single-channel.
        """
        frame = img
        if frame.dtype != np.uint8:
            peak = float(frame.max()) if frame.size else 0.0
            scale = 255.0 / peak if peak > 0 else 1.0
            frame = np.clip(frame.astype(np.float32) * scale, 0, 255).astype(np.uint8)
        if frame.ndim == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        if frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        return frame

    def _resolve_gsd_cm(self, img, full_path):
        """Ground sample distance at processing resolution, in cm/px.

        Terrain-aware from cached DEM tiles only - a pool worker must never
        block on a download - falling back to the takeoff-relative altitude
        inside ImageService, then to the operator's ``fallback_gsd_cm``.

        Returns:
            tuple: (gsd_cm or None, GSDService or None). The GSD service is
            returned so the oblique-tolerance check can reuse it.
        """
        native_gsd = None
        exif_width = None
        gsd_service = None
        try:
            # Imported here: ImageService pulls in pandas and the metadata
            # stack, which pool workers should not pay for at import time.
            from core.services.image.ImageService import ImageService
            scale = self.scale_factor if self.scale_factor > 0 else 1.0
            frame_size = (int(round(img.shape[1] / scale)), int(round(img.shape[0] / scale)))
            image_service = ImageService(full_path, defer_load=True)
            gsd_service = image_service.get_gsd_service(use_terrain=True, offline_only=True, frame_size=frame_size)
            if gsd_service is not None:
                native_gsd = gsd_service.compute_average_gsd()
                exif_width = gsd_service.image[0]
        except Exception as e:
            self.logger.debug(f"RoundShape: GSD lookup failed for {full_path}: {e}")
            gsd_service = None
            native_gsd = None

        if native_gsd is not None and native_gsd > 0 and exif_width:
            # GSD is per EXIF pixel; rescale to the pixels actually being processed.
            return native_gsd * float(exif_width) / float(img.shape[1]), gsd_service

        fallback = self.settings['fallback_gsd_cm']
        if fallback:
            scale = self.scale_factor if self.scale_factor > 0 else 1.0
            self.logger.info(f"RoundShape: using fallback GSD {fallback} cm/px for {full_path}")
            return fallback / scale, None
        return None, None

    def _effective_tolerance(self, tolerance, gsd_service, full_path):
        """Widen the size tolerance for oblique frames.

        One GSD is used per image; on an oblique frame the near and far edges
        differ, so the tolerance grows by the bottom/top GSD ratio.
        """
        if gsd_service is None:
            return tolerance
        try:
            tilt = float(getattr(gsd_service, 'title_angle', 0.0) or 0.0)
            if tilt <= _OBLIQUE_TILT_DEG:
                return tolerance
            width, height = gsd_service.image
            centre_col = width / 2.0
            top = gsd_service.compute_gsd(0, centre_col)
            bottom = gsd_service.compute_gsd(height - 1, centre_col)
            if not top or not bottom or top <= 0 or bottom <= 0:
                return tolerance
            ratio = max(top, bottom) / min(top, bottom)
            widened = (1.0 + tolerance) * ratio - 1.0
            self.logger.debug(
                f"RoundShape: {full_path} tilt {tilt:.0f} deg, size tolerance widened to {widened:.2f}"
            )
            return widened
        except Exception as e:
            self.logger.debug(f"RoundShape: oblique GSD check failed for {full_path}: {e}")
            return tolerance

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _detect(self, bgr, gsd_cm, tolerance, diameter_range_px):
        """Run edges -> symmetry peaks -> fits -> gates -> scoring -> suppression.

        Args:
            bgr (np.ndarray): Frame at processing resolution.
            gsd_cm (float): Ground sample distance at processing resolution.
            tolerance (float): Effective size tolerance.
            diameter_range_px (tuple): (smallest short diameter, largest long diameter) in px.

        Returns:
            tuple: (ellipses, confidences, debug_layers) for the kept
            hypotheses, highest confidence first.
        """
        settings = self.settings
        angle_tol = settings['angle_tolerance_deg']
        short_min_px, long_max_px = diameter_range_px
        radius_range = (0.5 * (1.0 - tolerance) * short_min_px, 0.5 * (1.0 + tolerance) * long_max_px)
        radius_range = (max(2.0, radius_range[0]), max(3.0, radius_range[1]))

        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        working = cv2.GaussianBlur(lab[:, :, 0], (0, 0), _PRE_BLUR_SIGMA)
        mag, ang = geometry.compute_gradients(working)
        floor = geometry.noise_floor(mag)
        edges = geometry.edge_map(working, mag, settings['min_edge_contrast'])
        # Edge support counts pixels at half the contrast setting: the Sobel
        # peak of a blurred step is lower than the step itself.
        contrast_floor = 0.5 * settings['min_edge_contrast']

        cell = max(1, int(radius_range[0] // _SYMMETRY_CELLS_PER_MIN_RADIUS))
        symmetry, voting_radius = geometry.radial_symmetry_map(edges, mag, ang, radius_range, cell, contrast_floor)
        peaks = geometry.symmetry_peaks(symmetry, voting_radius, _MIN_SYMMETRY, radius_range[0], cell, _MAX_PEAKS)

        ranges_cm = (
            settings['long_diameter_cm_min'], settings['long_diameter_cm_max'],
            settings['short_diameter_cm_min'], settings['short_diameter_cm_max'],
        )
        candidates = []      # (ellipse, evidence, kind)
        accepted_closed = []  # size-plausible closed outlines; peaks inside them are not refitted
        for cx, cy, _, _ in peaks:
            if any(self._inside(cx, cy, e) for e in accepted_closed):
                continue
            for ellipse in geometry.fit_round(edges, mag, ang, cx, cy, radius_range, angle_tol, floor):
                evidence = geometry.outline_support(ellipse, mag, ang, angle_tol, contrast_floor)
                kind = self._outline_kind(evidence)
                if kind is None:
                    continue
                candidates.append((ellipse, evidence, kind))
                if kind == _CLOSED and self._size_score(ellipse, gsd_cm, ranges_cm, tolerance) >= _MIN_SIZE_SCORE:
                    accepted_closed.append(ellipse)

        # An arc overlapping a closed outline that explains at least as much
        # edge is part of that outline (the end of an oval fits a circle
        # well), whatever size the outline is. The comparison matters the
        # other way too: half a disk under ground-coloured cover is a "D", and
        # an ellipse hugging the D is closed but explains less edge than the
        # arc of the whole disk.
        closed = [(e, ev) for e, ev, kind in candidates if kind == _CLOSED]
        candidates = [
            (ellipse, evidence, kind) for ellipse, evidence, kind in candidates
            if kind == _CLOSED or not any(
                self._overlaps(ellipse, other) and self._explained(other_evidence, other) >= self._explained(evidence, ellipse)
                for other, other_evidence in closed
            )
        ]

        scored = []
        scored_ellipses = []
        for ellipse, evidence, _ in candidates:
            s_size = self._size_score(ellipse, gsd_cm, ranges_cm, tolerance)
            if s_size < _MIN_SIZE_SCORE:
                continue
            delta_e = geometry.ring_contrast_lab(lab, ellipse, _RING_FRACTION)
            s_ctr = self._contrast_score(delta_e)
            s_round = evidence.curvature * (1.0 - evidence.boxiness)
            s_salience = self._salience_score(evidence.strength, floor, contrast_floor)
            confidence = 100.0 * (
                s_size ** _EXP_SIZE
                * evidence.support ** _EXP_EDGE
                * s_ctr ** _EXP_CONTRAST
                * max(s_round, _TERM_FLOOR) ** _EXP_ROUNDNESS
                * max(s_salience, _TERM_FLOOR) ** _EXP_SALIENCE
            )
            # Suppression only ever removes a hypothesis in favour of a
            # stronger one, so thresholding first gives the same survivors
            # and keeps the O(n^2) NMS small.
            if confidence < settings['min_confidence']:
                continue
            scored_ellipses.append(ellipse)
            scored.append(confidence)

        kept = geometry.ellipse_nms(scored_ellipses, scored, _NMS_IOU, _NMS_CONTAINMENT)
        kept = kept[:max(0, settings['max_detections_per_image'])]
        debug_layers = {'edges': edges, 'symmetry': symmetry}
        return [scored_ellipses[k] for k in kept], [scored[k] for k in kept], debug_layers

    def _outline_kind(self, evidence):
        """'closed', 'arc' or None (rejected) for one hypothesis' outline evidence.

        Both kinds must be curves: the supported outline has to bend with
        the model and must not be the four sides of a box. A closed outline
        is supported over at least ``min_edge_support`` of its length with
        no long break; an arc (when enabled) is one unbroken stretch of at
        least ``min_arc_degrees``.
        """
        if evidence.curvature < _MIN_CURVATURE or evidence.boxiness > _MAX_BOXINESS:
            return None
        settings = self.settings
        if evidence.support >= settings['min_edge_support'] and evidence.gap_deg <= _MAX_CLOSED_GAP_DEG:
            return _CLOSED
        if settings['detect_arcs'] and evidence.arc_deg >= settings['min_arc_degrees']:
            return _ARC
        return None

    @staticmethod
    def _size_score(ellipse, gsd_cm, ranges_cm, tolerance):
        """Physical-size score of an ellipse's two diameters."""
        return geometry.size_score(ellipse.major * gsd_cm, ellipse.minor * gsd_cm, ranges_cm, tolerance)

    @staticmethod
    def _inside(x, y, ellipse):
        """True when (x, y) lies inside ``ellipse``."""
        theta = math.radians(ellipse.angle_deg)
        dx = x - ellipse.cx
        dy = y - ellipse.cy
        along = dx * math.cos(theta) + dy * math.sin(theta)
        across = -dx * math.sin(theta) + dy * math.cos(theta)
        a = max(ellipse.major * 0.5, 1e-6)
        b = max(ellipse.minor * 0.5, 1e-6)
        return (along / a) ** 2 + (across / b) ** 2 <= 1.0

    @staticmethod
    def _explained(evidence, ellipse):
        """Edge length (px) an outline accounts for: its support times its perimeter."""
        return evidence.support * geometry.ellipse_perimeter(ellipse)

    @staticmethod
    def _overlaps(first, second):
        """True when two ellipses would suppress each other (see geometry.ellipse_nms)."""
        return len(geometry.ellipse_nms([first, second], [0.0, 1.0], _NMS_IOU, _NMS_CONTAINMENT)) == 1

    @staticmethod
    def _salience_score(strength, floor, contrast_floor):
        """How far the outline's edge stands above the ground's texture, in [0, 1].

        Natural blobs (mottled vegetation, soft shading) are round too, but
        their outlines barely clear the texture around them; a placed
        object's edge stands well above it. 0 at the texture level, 1 once
        the edge clears it by another contrast floor (or by the texture
        level itself on busy ground, whichever is larger).
        """
        return min(1.0, max(0.0, (strength - floor) / max(floor, contrast_floor, 1e-6)))

    @staticmethod
    def _contrast_score(delta_e):
        """Saturating map of Delta E to [0, 1]: 0 -> 0, ~15 -> 0.9."""
        k = _CONTRAST_DELTA_E_AT_0_9 / math.log(10.0)
        return 1.0 - math.exp(-max(0.0, delta_e) / k)

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    @staticmethod
    def _contour_in_frame(ellipse, shape):
        """Integer contour of ``ellipse``, clipped to the frame.

        A target cut by the frame edge yields an outline that runs outside
        the image; AOI pixel lists must stay inside it.
        """
        points = np.rint(geometry.ellipse_polygon(ellipse)).astype(np.int32)
        points[:, 0] = np.clip(points[:, 0], 0, shape[1] - 1)
        points[:, 1] = np.clip(points[:, 1], 0, shape[0] - 1)
        return points.reshape(-1, 1, 2)

    @staticmethod
    def _attach_scores(areas_of_interest, ellipses, scores):
        """Give each AOI the confidence of the hypothesis whose centre is nearest.

        identify_areas_of_interest re-sorts AOIs by position, so they are
        matched back to hypotheses geometrically.
        """
        centres = np.array([(e.cx, e.cy) for e in ellipses], dtype=np.float32)
        for aoi in areas_of_interest:
            cx, cy = aoi['center']
            nearest = int(np.argmin(np.hypot(centres[:, 0] - cx, centres[:, 1] - cy)))
            aoi['confidence'] = round(float(scores[nearest]), 1)
            aoi['score_type'] = 'shape'

    def _report_batch_area_disagreement(self, areas_of_interest, full_path):
        """Log AOIs the batch min/max area would have dropped.

        The service gates on physical size instead (see __init__); this keeps
        the disagreement visible when someone compares against the guide's
        target size.
        """
        outside = 0
        for aoi in areas_of_interest:
            area = aoi.get('area', 0)
            too_small = bool(self.batch_min_area) and area < self.batch_min_area
            too_large = bool(self.batch_max_area) and area > self.batch_max_area
            if too_small or too_large:
                outside += 1
        if outside:
            self.logger.info(
                f"RoundShape: {outside} detection(s) in {full_path} fall outside the batch "
                f"area limits ({self.batch_min_area}-{self.batch_max_area} px) and were kept; "
                "the target size preset governs this algorithm"
            )

    def _empty_result(self, full_path, output_dir):
        """A successful result with no detections."""
        return AnalysisResult(full_path, None, output_dir, None, None)

    def _write_debug_overlay(self, bgr, full_path, output_dir, layers, ellipses, scores):
        """Write the tuning overlay: symmetry heatmap, traced edges, kept outlines.

        Saved as <output_dir>/round_debug/<image>_debug.jpg. A failure here
        must never fail the analysis, so it is logged and swallowed.
        """
        try:
            overlay = bgr.copy()
            symmetry = layers.get('symmetry')
            if symmetry is not None and symmetry.size:
                heat = cv2.resize(
                    np.clip(symmetry * 255.0, 0, 255).astype(np.uint8),
                    (bgr.shape[1], bgr.shape[0]),
                    interpolation=cv2.INTER_LINEAR,
                )
                overlay = cv2.addWeighted(overlay, 0.6, cv2.applyColorMap(heat, cv2.COLORMAP_JET), 0.4, 0)
            edges = layers.get('edges')
            if edges is not None:
                overlay[edges > 0] = (160, 160, 160)
            for ellipse, score in zip(ellipses, scores):
                # Red at the emission threshold up to green at 100.
                fraction = min(1.0, max(0.0, score / 100.0))
                colour = (0, int(255 * fraction), int(255 * (1.0 - fraction)))
                points = np.rint(geometry.ellipse_polygon(ellipse)).astype(np.int32)
                cv2.polylines(overlay, [points], True, colour, 2)
                cv2.putText(
                    overlay, f"{score:.0f}", (int(ellipse.cx), int(ellipse.cy)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA,
                )
            debug_dir = Path(output_dir) / 'round_debug'
            debug_dir.mkdir(parents=True, exist_ok=True)
            target = debug_dir / f"{Path(full_path).stem}_debug.jpg"
            ok, encoded = cv2.imencode('.jpg', overlay)
            if ok:
                encoded.tofile(os.fspath(target))
        except Exception as e:
            self.logger.warning(f"RoundShape: debug overlay failed for {full_path}: {e}")
