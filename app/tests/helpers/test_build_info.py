"""Tests for helpers.BuildInfo - the build stamp that identifies field builds."""

import sys

from helpers import BuildInfo


def _clear_cache():
    BuildInfo._cached_stamp = None


def test_title_version_appends_stamp(monkeypatch):
    monkeypatch.setattr(BuildInfo, 'get_build_stamp', lambda: 'abc1234')
    assert BuildInfo.title_version('2.1.4') == '2.1.4 (abc1234)'


def test_title_version_plain_when_unknown(monkeypatch):
    monkeypatch.setattr(BuildInfo, 'get_build_stamp', lambda: '')
    assert BuildInfo.title_version('2.1.4') == '2.1.4'


def test_baked_stamp_wins_in_frozen_build(tmp_path, monkeypatch):
    (tmp_path / BuildInfo.BUILD_INFO_FILENAME).write_text('f00dcafe+dirty\n')
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    _clear_cache()
    try:
        assert BuildInfo.get_build_stamp() == 'f00dcafe+dirty'
    finally:
        _clear_cache()


def test_dev_checkout_reads_live_git(monkeypatch):
    """In this repo (a git checkout, no _MEIPASS) the stamp is a short hash,
    optionally '+dirty'. Guards the fallback the developers rely on."""
    monkeypatch.delattr(sys, '_MEIPASS', raising=False)
    _clear_cache()
    try:
        stamp = BuildInfo.get_build_stamp()
        assert stamp, "expected a live git stamp in a dev checkout"
        head = stamp.removesuffix('+dirty')
        assert 6 <= len(head) <= 16 and all(c in '0123456789abcdef' for c in head)
    finally:
        _clear_cache()


def test_unknown_everywhere_is_empty(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, '_MEIPASS', raising=False)
    monkeypatch.setattr(BuildInfo, '_read_git_stamp', lambda: '')
    _clear_cache()
    try:
        assert BuildInfo.get_build_stamp() == ''
        assert BuildInfo.title_version('2.1.4') == '2.1.4'
    finally:
        _clear_cache()
