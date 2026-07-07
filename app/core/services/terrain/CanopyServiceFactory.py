"""
CanopyServiceFactory - construct a CanopyService from user settings.

Canopy is a separate axis from the terrain elevation provider (both can be
active at once), so it has its own factory and settings keys, mirroring the
Terrain3DEP* pattern. Returns None when unconfigured, which the POD pipeline
treats as "no canopy" (transmittance = 1).
"""

from core.services.LoggerService import LoggerService

CANOPY_KIND_NONE = 'none'
CANOPY_KIND_LANDFIRE = 'landfire'
CANOPY_KIND_META = 'meta'
DEFAULT_CANOPY_KIND = CANOPY_KIND_NONE


class CanopyServiceFactory:
    @staticmethod
    def create_from_settings(settings_service):
        """Build a CanopyService from settings, or None if unconfigured."""
        if settings_service is None:
            return None
        kind = settings_service.get_setting('CanopyKind', DEFAULT_CANOPY_KIND) or DEFAULT_CANOPY_KIND
        if kind == CANOPY_KIND_NONE:
            return None

        manifest = settings_service.get_setting('CanopyManifestPath', '')
        tiles_dir = settings_service.get_setting('CanopyTilesDir', '')
        if not manifest or not tiles_dir:
            LoggerService().warning("CanopyServiceFactory: paths unset; canopy disabled.")
            return None

        try:
            from core.services.terrain.CanopyService import CanopyService
            return CanopyService(manifest, tiles_dir, kind=kind)
        except Exception as e:
            LoggerService().error(f"CanopyServiceFactory: failed ({e}); canopy disabled.")
            return None

    @staticmethod
    def available_kinds():
        """Drives the Preferences combo. [{id, label, requires_paths}]."""
        return [
            {'id': CANOPY_KIND_NONE,
             'label': 'None (no canopy attenuation)', 'requires_paths': False},
            {'id': CANOPY_KIND_LANDFIRE,
             'label': 'LANDFIRE EVH + EVC (local GeoTIFFs, 30 m)', 'requires_paths': True},
            {'id': CANOPY_KIND_META,
             'label': 'Meta/WRI Canopy Height (local GeoTIFFs, 1 m)', 'requires_paths': True},
        ]


def create_canopy_service(settings_service):
    """Module-level alias (the export layer references this name)."""
    return CanopyServiceFactory.create_from_settings(settings_service)
