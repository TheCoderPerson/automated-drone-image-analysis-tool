"""
CoverageResultCache - in-session cache for the last CoveragePodService run.

Mirrors the HeatmapService lifecycle idiom (is-valid / get / invalidate) so the
viewer overlay can re-render the cached POD product without recomputing.
"""


class CoverageResultCache:
    def __init__(self):
        self._result = None

    def set_result(self, result) -> None:
        self._result = result

    def get_result(self):
        return self._result

    def has_result(self) -> bool:
        return self._result is not None

    def invalidate(self) -> None:
        self._result = None
