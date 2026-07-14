"""Tests for the in-session CoverageResultCache lifecycle."""

from core.services.coverage.CoverageResultCache import CoverageResultCache


def test_cache_lifecycle():
    cache = CoverageResultCache()
    assert cache.has_result() is False
    assert cache.get_result() is None

    sentinel = object()
    cache.set_result(sentinel)
    assert cache.has_result() is True
    assert cache.get_result() is sentinel

    cache.invalidate()
    assert cache.has_result() is False
    assert cache.get_result() is None
