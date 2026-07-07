"""
GPSMapController - Manages GPS map visualization for the image viewer.

This controller handles the GPS map window lifecycle, data extraction,
and coordination between the map and main viewer.
"""

from PySide6.QtCore import QObject, Signal, QTimer, QPointF
from PySide6.QtWidgets import QMenu
from PySide6.QtGui import QCursor, QImage, QPixmap
from helpers.LocationInfo import LocationInfo
from helpers.MetaDataHelper import MetaDataHelper
from core.services.LoggerService import LoggerService
from core.services.image.ImageService import ImageService
from core.services.image.AOIService import AOIService, _get_terrain_service
from core.services.image.AOINeighborService import AOINeighborService
from core.services.waldo import WaldoMetadataService
from core.views.images.viewer.dialogs.GPSMapDialog import GPSMapDialog
import piexif
from datetime import datetime
import math


class GPSMapController(QObject):
    """
    Controller for GPS map functionality.

    Manages GPS data extraction, map window creation, and image selection
    coordination between the map and main viewer.
    """

    # Signal emitted when an image is selected from the map
    image_selected = Signal(int)

    def __init__(self, parent_viewer):
        """
        Initialize the GPS map controller.

        Args:
            parent_viewer: The main Viewer instance
        """
        super().__init__()
        self.parent = parent_viewer
        self.logger = LoggerService()  # Create our own logger
        self.map_dialog = None
        self.gps_data = []
        self._pod_overlay_enabled = False
        self._pod_overlay_mode = 'pod'
        self._limit_labels = None
        self._max_overlay_dim = 2048

    def show_map(self):
        """
        Show the GPS map window.

        Extracts GPS data from images and creates/shows the map dialog.
        """
        # Extract GPS data from all images
        self.extract_gps_data()

        if not self.gps_data:
            self.parent.status_controller.show_toast(self.tr("No GPS data found in images"), 3000, color="#F44336")
            return

        # Create and show the map dialog
        # Find the current image in the GPS data list
        current_gps_index = None
        for i, data in enumerate(self.gps_data):
            if data['index'] == self.parent.current_image:
                current_gps_index = i
                break

        offline_only = self._is_offline_only()

        if self.map_dialog is None:
            self.map_dialog = GPSMapDialog(self.parent, self.gps_data, current_gps_index, offline_only=offline_only)
            self.map_dialog.image_selected.connect(self.on_map_image_selected)
            self.map_dialog.gps_right_clicked.connect(self.on_map_gps_clicked)
            if hasattr(self.map_dialog, 'pod_display_changed'):
                self.map_dialog.pod_display_changed.connect(self.on_pod_display_changed)
            # Connect to dialog close event to update button state
            self.map_dialog.finished.connect(self.on_map_dialog_closed)
        else:
            # Update with latest data if dialog already exists
            self.map_dialog.update_gps_data(self.gps_data, current_gps_index)
            self.map_dialog.set_offline_mode(offline_only)

        # Enable/disable the overlay controls based on whether a POD result exists.
        cache = self._pod_cache()
        if hasattr(self.map_dialog, 'set_pod_available'):
            self.map_dialog.set_pod_available(cache is not None and cache.has_result())

        self.map_dialog.show()
        self.map_dialog.raise_()
        self.map_dialog.activateWindow()

        # Update button state to show map is open
        if hasattr(self.parent, 'gps_map_open'):
            self.parent.gps_map_open = True
            if hasattr(self.parent, 'ui_style_controller'):
                self.parent.ui_style_controller.update_gps_map_button_style()

        # Show current AOI if one is selected
        self.update_aoi_on_map()

        # Send current zoom FOV state to the map
        if hasattr(self.parent, '_on_view_changed'):
            self.parent._on_view_changed()

    def _is_offline_only(self) -> bool:
        """Return whether OfflineOnly preference is enabled."""
        try:
            if hasattr(self.parent, "settings_service"):
                return self.parent.settings_service.get_bool_setting("OfflineOnly", False)
        except Exception:
            pass
        return False

    def extract_gps_data(self):
        """
        Extract GPS coordinates and timestamps from all source-folder images.

        AOI-subset images keep their viewer index so clicks on the map jump to
        the corresponding viewer slot. Source-only captures (in the original
        flight folder but not in the result XML) are appended with index=None
        and is_source_only=True so the renderer can paint them as small grey
        dots and the click handler ignores them.
        """
        self.gps_data = []

        # Index AOI subset by path so we can look up the viewer position for any
        # source-folder entry that did produce a detection.
        aoi_by_path = {img['path']: (idx, img) for idx, img in enumerate(self.parent.images) if img.get('path')}

        # Fall back to AOI-only iteration if source_images wasn't populated
        # (e.g. on legacy code paths or if Viewer.__init__ short-circuited).
        source_iterable = getattr(self.parent, 'source_images', None) or [
            {'path': img['path'], 'name': img.get('name', ''), 'has_aoi': True}
            for img in self.parent.images if img.get('path')
        ]

        for src_entry in source_iterable:
            path = src_entry.get('path')
            if not path:
                continue
            try:
                exif_data = MetaDataHelper.get_exif_data_piexif(path)
                gps_coords = LocationInfo.get_gps(exif_data=exif_data)
                if not gps_coords:
                    continue

                timestamp = self.get_image_timestamp_from_exif(exif_data)
                aoi_match = aoi_by_path.get(path)

                if aoi_match is not None:
                    idx, image = aoi_match
                    aoi_count = len(image.get('areas_of_interest', [])) if 'areas_of_interest' in image else 0
                    has_aoi = aoi_count > 0
                    has_flagged = any(aoi.get('flagged', False) for aoi in image.get('areas_of_interest', []))
                    # WALDO images: the XML's cached bearing was computed by
                    # BearingRecoveryController before WALDO synthesised the XMP,
                    # so it's stale. Force GPSMapView's lazy lookup to read the
                    # authoritative Gimbal Yaw from the now-present XMP.
                    is_waldo = WaldoMetadataService.is_waldo_image(path) is not None
                    cached_bearing = None if is_waldo else image.get('bearing')
                    self.gps_data.append({
                        'index': idx,
                        'latitude': gps_coords['latitude'],
                        'longitude': gps_coords['longitude'],
                        'timestamp': timestamp,
                        'name': image.get('name', src_entry.get('name', f'Image {idx + 1}')),
                        'has_aoi': has_aoi,
                        'aoi_count': aoi_count,
                        'hidden': image.get('hidden', False),
                        'has_flagged': has_flagged,
                        'bearing': cached_bearing,
                        'wingtra_agl_ft': image.get('wingtra_agl_ft'),
                        'fov_alignment': image.get('fov_alignment'),
                        'width': image.get('width'),
                        'height': image.get('height'),
                        'image_path': path,
                        'is_source_only': False,
                    })
                else:
                    # Source-only capture: display-only marker, no click target.
                    self.gps_data.append({
                        'index': None,
                        'latitude': gps_coords['latitude'],
                        'longitude': gps_coords['longitude'],
                        'timestamp': timestamp,
                        'name': src_entry.get('name', ''),
                        'has_aoi': False,
                        'aoi_count': 0,
                        'hidden': False,
                        'has_flagged': False,
                        'bearing': None,
                        'wingtra_agl_ft': None,
                        'image_path': path,
                        'is_source_only': True,
                    })
            except Exception as e:
                self.logger.error(f"Could not extract GPS from {path}: {str(e)}")

        # Sort by timestamp so the path line traces the actual flight order.
        self.gps_data.sort(key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min)

    def get_image_timestamp_from_exif(self, exif_data):
        """
        Extract timestamp from EXIF data.

        Args:
            exif_data: Pre-loaded EXIF data dictionary

        Returns:
            datetime object or None if timestamp not found
        """
        try:

            if exif_data and 'Exif' in exif_data:
                # Try to get DateTimeOriginal
                datetime_original = exif_data['Exif'].get(piexif.ExifIFD.DateTimeOriginal)
                if datetime_original:
                    if isinstance(datetime_original, bytes):
                        datetime_str = datetime_original.decode('utf-8')
                    else:
                        datetime_str = datetime_original
                    return datetime.strptime(datetime_str, '%Y:%m:%d %H:%M:%S')

                # Fallback to DateTime
                datetime_tag = exif_data['Exif'].get(piexif.ExifIFD.DateTime)
                if datetime_tag:
                    datetime_str = datetime_tag.decode('utf-8') if isinstance(datetime_tag, bytes) else datetime_tag
                    return datetime.strptime(datetime_str, '%Y:%m:%d %H:%M:%S')

        except Exception as e:
            self.logger.error(f"Could not extract timestamp: {str(e)}")

        return None

    def get_image_timestamp(self, image_path):
        """
        Extract timestamp from image EXIF data (compatibility method).

        Args:
            image_path: Path to the image file

        Returns:
            datetime object or None if timestamp not found
        """
        exif_data = MetaDataHelper.get_exif_data_piexif(image_path)
        return self.get_image_timestamp_from_exif(exif_data)

    def get_image_bearing(self, image_path, calculated_bearing=None):
        """
        Extract bearing/yaw information from image.

        Args:
            image_path: Path to the image file
            calculated_bearing: Optional calculated bearing from XML (degrees)

        Returns:
            float: Bearing in degrees (0-360), or None if not available
        """
        try:
            image_service = ImageService(image_path, '', calculated_bearing=calculated_bearing)
            # Use get_camera_yaw() which accounts for both Flight Yaw and Gimbal Yaw
            bearing = image_service.get_camera_yaw()
            return bearing
        except Exception as e:
            self.logger.error(f"Could not extract bearing: {str(e)}")
            return None

    def on_map_image_selected(self, image_index):
        """
        Handle image selection from the map.

        Args:
            image_index: Index of the selected image
        """
        if 0 <= image_index < len(self.parent.images):
            self.parent.current_image = image_index
            self.parent._load_image()

    # ---------------- POD coverage overlay ----------------

    def _pod_cache(self):
        return getattr(self.parent, 'pod_result_cache', None)

    def _limit_label(self, code):
        if self._limit_labels is None:
            from core.services.coverage.contracts import (
                LIMIT_NO_LOOKS, LIMIT_TERRAIN, LIMIT_CANOPY, LIMIT_GSD, LIMIT_NONE)
            self._limit_labels = {
                LIMIT_NO_LOOKS: self.tr("Not covered — no looks"),
                LIMIT_TERRAIN: self.tr("Terrain occlusion"),
                LIMIT_CANOPY: self.tr("Canopy"),
                LIMIT_GSD: self.tr("Image resolution (GSD)"),
                LIMIT_NONE: self.tr("None"),
            }
        return self._limit_labels.get(code, self.tr("Unknown"))

    def _build_pod_pixmap(self, result, mode):
        """(QPixmap, transform6) from a CoverageResult, downsampled to a display cap."""
        import numpy as np
        from core.services.coverage.colormap import pod_to_rgba, look_count_to_rgba

        if mode == 'looks':
            rgba = look_count_to_rgba(result.look_count)
        else:
            rgba = pod_to_rgba(result.pod, result.look_count, result.params)

        a, b, c, d, e, f = tuple(result.transform)[:6]
        rows, cols = rgba.shape[:2]
        shrink = max(rows, cols) / float(self._max_overlay_dim)
        if shrink > 1.0:
            import cv2
            new_cols = max(1, int(cols / shrink))
            new_rows = max(1, int(rows / shrink))
            rgba = cv2.resize(rgba, (new_cols, new_rows), interpolation=cv2.INTER_NEAREST)
            a *= cols / new_cols
            e *= rows / new_rows
            rows, cols = new_rows, new_cols

        arr = np.ascontiguousarray(rgba, dtype=np.uint8)
        qimg = QImage(arr.tobytes(), cols, rows, 4 * cols, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg), (a, b, c, d, e, f)

    def enable_pod_overlay(self, mode='pod'):
        """Turn the overlay on from the cached result (called after an export run)."""
        cache = self._pod_cache()
        if cache is None or not cache.has_result() or self.map_dialog is None:
            return
        if hasattr(self.map_dialog, 'set_pod_available'):
            self.map_dialog.set_pod_available(True)
        self.on_pod_display_changed(True, mode, int(self.map_dialog.map_view._pod_opacity * 100)
                                    if hasattr(self.map_dialog, 'map_view') else 70)

    def on_pod_display_changed(self, enabled, mode, opacity):
        """React to the dialog's overlay toggle / mode / opacity controls."""
        cache = self._pod_cache()
        if not enabled or cache is None or not cache.has_result() or self.map_dialog is None:
            self._pod_overlay_enabled = False
            if self.map_dialog is not None and hasattr(self.map_dialog, 'map_view'):
                self.map_dialog.map_view.clear_pod_overlay()
            return
        result = cache.get_result()
        pixmap, transform6 = self._build_pod_pixmap(result, mode)
        self._pod_overlay_enabled = True
        self._pod_overlay_mode = mode
        view = self.map_dialog.map_view
        view.set_pod_overlay(pixmap, transform6)
        view.set_pod_overlay_opacity(opacity / 100.0)

    def _show_pod_inspect_menu(self, sample, lat, lon):
        view = self.map_dialog.map_view if self.map_dialog else None
        menu = QMenu(view)
        hdr = menu.addAction(self.tr("POD: {pod}%   Looks: {looks}").format(
            pod=round(sample['pod'] * 100), looks=sample['looks']))
        hdr.setEnabled(False)
        lim = menu.addAction(self.tr("Limiting factor: {factor}").format(
            factor=self._limit_label(sample['limiting_factor'])))
        lim.setEnabled(False)
        frames = sample.get('frames', [])
        if frames:
            menu.addSeparator()
            for idx in frames[:8]:
                if 0 <= idx < len(self.parent.images):
                    name = self.parent.images[idx].get('name', self.tr("Image {n}").format(n=idx + 1))
                    act = menu.addAction(self.tr("View {name}").format(name=name))
                    act.triggered.connect(lambda checked=False, i=idx: self.on_map_image_selected(i))
        menu.addSeparator()
        locate = menu.addAction(self.tr("Find location in images"))
        locate.triggered.connect(lambda checked=False: self._reverse_locate(lat, lon))
        menu.exec(QCursor.pos())

    def update_current_image(self, image_index):
        """
        Update the map to highlight a new current image.

        Args:
            image_index: Index of the new current image in the viewer's image list
        """
        if self.map_dialog and self.map_dialog.isVisible():
            # Find the gps_data list index for this image
            for i, data in enumerate(self.gps_data):
                if data['index'] == image_index:
                    self.map_dialog.set_current_image(i)
                    break

            # Clear AOI marker when switching images (will be re-added if AOI is selected)
            self.map_dialog.update_aoi_marker(None, None)

    def update_zoom_fov(self, visible_rect):
        """
        Update the zoom FOV box on the GPS map.

        Args:
            visible_rect: QRectF in image pixel coordinates, or None to clear.
        """
        if self.map_dialog and self.map_dialog.isVisible():
            self.map_dialog.update_zoom_fov(visible_rect)

    def on_map_gps_clicked(self, lat, lon):
        """Handle a right-click on the map.

        When the POD overlay is active and the click lands on a covered cell,
        show a cell-inspect menu (POD, look count, limiting factor, contributing
        frames). Otherwise fall back to the reverse image lookup.
        """
        if self._pod_overlay_enabled:
            cache = self._pod_cache()
            result = cache.get_result() if (cache and cache.has_result()) else None
            sample = result.sample(lat, lon) if result is not None else None
            if sample is not None:
                self._show_pod_inspect_menu(sample, lat, lon)
                return
        self._reverse_locate(lat, lon)

    def _reverse_locate(self, lat, lon):
        """
        Find the image containing the coordinate and center the viewer on it.

        Args:
            lat: Clicked latitude
            lon: Clicked longitude
        """
        try:
            neighbor_service = AOINeighborService()
            terrain_service = None
            try:
                terrain_service = _get_terrain_service()
            except Exception:
                pass

            # Try current image first, then search others sorted by distance
            candidates = []
            current_idx = self.parent.current_image
            if 0 <= current_idx < len(self.parent.images):
                candidates.append(current_idx)

            # Sort other images by distance from clicked point
            other_indices = []
            for data in self.gps_data:
                idx = data['index']
                # Skip source-only entries (no AOI subset slot, so no image to open).
                if idx is None or idx == current_idx:
                    continue
                dlat = (data['latitude'] - lat) * 111320
                dlon = (data['longitude'] - lon) * 111320 * math.cos(math.radians(lat))
                dist = math.sqrt(dlat * dlat + dlon * dlon)
                other_indices.append((dist, idx))
            other_indices.sort()
            candidates.extend(idx for _, idx in other_indices[:10])

            for idx in candidates:
                if idx < 0 or idx >= len(self.parent.images):
                    continue
                image = self.parent.images[idx]
                coverage = neighbor_service.get_image_coverage_info(image)
                if not coverage:
                    continue

                # Apply terrain adjustment to altitude
                self._apply_terrain_altitude(coverage, lat, lon, terrain_service)

                pixel = neighbor_service.gps_to_pixel(lat, lon, coverage)
                if pixel is None:
                    continue
                u, v = pixel
                if not neighbor_service.is_point_in_image(u, v, coverage['width'], coverage['height']):
                    continue

                # Found a matching image — center the viewer
                if idx != current_idx:
                    self.parent.current_image = idx
                    self.parent._load_image()
                    # Defer centering until image is loaded
                    QTimer.singleShot(150, lambda px=(u, v): self._center_viewer_on_pixel(px))
                else:
                    self._center_viewer_on_pixel((u, v))
                return

            # No image contains this coordinate
            if hasattr(self.parent, 'status_controller'):
                self.parent.status_controller.show_toast(
                    self.tr("GPS coordinate not in any images"),
                    3000, color="#F44336"
                )

        except Exception as e:
            self.logger.error(f"Error handling GPS map click: {e}")

    def _apply_terrain_altitude(self, coverage, target_lat, target_lon, terrain_service):
        """Adjust coverage altitude with terrain elevation at the target location."""
        if not terrain_service or not terrain_service.enabled:
            return
        try:
            image_service = coverage.get('image_service')
            if not image_service:
                return
            absolute_alt = image_service.get_asl_altitude('m')
            if not absolute_alt:
                return
            geoid = terrain_service.get_geoid_undulation(coverage['center_lat'], coverage['center_lon'])
            drone_ortho = absolute_alt - (geoid or 0)
            click_terrain = terrain_service.get_elevation(target_lat, target_lon)
            if click_terrain.source == 'terrain' and click_terrain.elevation_m is not None:
                effective_agl = max(1.0, drone_ortho - click_terrain.elevation_m)
                coverage['altitude'] = effective_agl
        except Exception:
            pass

    def _center_viewer_on_pixel(self, pixel_xy):
        """Center the main image viewer on a pixel coordinate."""
        try:
            if self.parent.main_image and self.parent.main_image.hasImage():
                current_zoom = self.parent.main_image.getZoom()
                scale = max(current_zoom, 2.0)
                self.parent.main_image.zoomToArea(pixel_xy, scale)
        except Exception as e:
            self.logger.error(f"Error centering viewer: {e}")

    def close_map(self):
        """Close the GPS map window if it's open."""
        if self.map_dialog:
            self.map_dialog.close()
            self.map_dialog = None

    def on_map_dialog_closed(self):
        """Handle map dialog close event."""
        if hasattr(self.parent, 'gps_map_open'):
            self.parent.gps_map_open = False
            if hasattr(self.parent, 'ui_style_controller'):
                self.parent.ui_style_controller.update_gps_map_button_style()

    def get_current_aoi_gps(self):
        """
        Get GPS coordinates for the currently selected AOI.

        Returns:
            Dict with AOI GPS data including coordinates and metadata, or None
        """
        try:
            # Check if we have a selected AOI
            if not hasattr(self.parent, 'aoi_controller') or self.parent.aoi_controller.selected_aoi_index < 0:
                return None

            # Get current image data
            current_image = self.parent.images[self.parent.current_image]

            # Get AOI data
            aoi_index = self.parent.aoi_controller.selected_aoi_index
            if 'areas_of_interest' not in current_image or aoi_index >= len(current_image['areas_of_interest']):
                return None

            aoi = current_image['areas_of_interest'][aoi_index]

            # Use AOIService for GPS calculation with metadata
            aoi_service = AOIService(current_image)

            # Get custom altitude if available
            custom_alt_ft = None
            if (hasattr(self.parent, 'custom_agl_altitude_ft') and
                    self.parent.custom_agl_altitude_ft and
                    self.parent.custom_agl_altitude_ft > 0):
                custom_alt_ft = self.parent.custom_agl_altitude_ft

            # Fall back to per-image AGL from Wingtra CSV data
            if custom_alt_ft is None:
                custom_alt_ft = current_image.get('wingtra_agl_ft')

            # Calculate AOI GPS coordinates with metadata using the convenience method
            aoi_gps = aoi_service.get_aoi_gps_with_metadata(current_image, aoi, aoi_index, custom_alt_ft)

            if not aoi_gps:
                return None

            # Add additional viewer-specific metadata
            aoi_gps['image_index'] = self.parent.current_image
            aoi_gps['image_name'] = current_image.get('name', 'Unknown')

            # Get color/temperature info if available
            if hasattr(self.parent.aoi_controller, 'calculate_aoi_average_info'):
                # Get temperature data from thermal controller if available
                temperature_data = None
                if hasattr(self.parent, 'thermal_controller'):
                    temperature_data = self.parent.thermal_controller.temperature_data

                avg_info, _ = self.parent.aoi_controller.calculate_aoi_average_info(
                    aoi,
                    self.parent.is_thermal,
                    temperature_data,
                    self.parent.temperature_unit
                )
                aoi_gps['avg_info'] = avg_info

            return aoi_gps

        except Exception as e:
            self.logger.error(f"Error getting current AOI GPS: {e}")
            return None

    def calculate_gsd_for_image(self, image_path, custom_altitude_ft=None):
        """
        Calculate GSD for an image if not already available.

        Args:
            image_path: Path to the image file
            custom_altitude_ft: Optional custom altitude in feet

        Returns:
            GSD in cm/px or None if calculation fails
        """
        try:
            image_service = ImageService(image_path, '')

            # Use the existing ImageService method to get average GSD
            avg_gsd = image_service.get_average_gsd(custom_altitude_ft=custom_altitude_ft)
            return avg_gsd

        except Exception:
            return None

    def update_aoi_on_map(self):
        """Update the AOI display on the map if it's open."""
        if self.map_dialog and self.map_dialog.isVisible():
            aoi_gps = self.get_current_aoi_gps()

            # Get the identifier color from settings
            identifier_color = self.parent.settings.get('identifier_color', [255, 255, 0])

            self.map_dialog.update_aoi_marker(aoi_gps, identifier_color)
