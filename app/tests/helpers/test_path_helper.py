"""Unit tests for helpers.PathHelper.

These cover the cross-platform path handling that result-file relocation
depends on: a flight analyzed on one platform is routinely reviewed on another,
so filenames must be derived and matched identically everywhere.
"""

import os
import unicodedata

from helpers.PathHelper import (
    cross_platform_basename,
    find_in_index,
    index_folder_by_filename,
    is_absolute_any_platform,
    normalize_filename_key,
)


# --------------------------- cross_platform_basename ----------------------- #

def test_basename_of_windows_path_on_any_platform():
    """The regression: os.path.basename does not split backslashes on POSIX."""
    stored = r"C:\Users\pilot\Flight1\DJI_0042.JPG"
    assert cross_platform_basename(stored) == "DJI_0042.JPG"


def test_basename_of_unc_path():
    assert cross_platform_basename(r"\\nas\flights\day2\DJI_0007.JPG") == "DJI_0007.JPG"


def test_basename_of_posix_path():
    assert cross_platform_basename("/Volumes/SD/Flight1/DJI_0042.JPG") == "DJI_0042.JPG"


def test_basename_of_mixed_separators():
    assert cross_platform_basename("C:/Flight1\\sub/DJI_0042.JPG") == "DJI_0042.JPG"


def test_basename_of_bare_filename():
    assert cross_platform_basename("DJI_0042.JPG") == "DJI_0042.JPG"


def test_basename_of_empty_is_empty():
    assert cross_platform_basename("") == ""
    assert cross_platform_basename(None) == ""


def test_basename_ignores_trailing_separator():
    assert cross_platform_basename("/Volumes/SD/Flight1/") == "Flight1"
    assert cross_platform_basename("C:\\Flight1\\") == "Flight1"


# --------------------------- is_absolute_any_platform ---------------------- #

def test_windows_drive_path_is_absolute():
    assert is_absolute_any_platform(r"C:\Flight1\img.jpg")
    assert is_absolute_any_platform("C:/Flight1/img.jpg")
    assert is_absolute_any_platform(r"z:\img.jpg")


def test_unc_path_is_absolute():
    assert is_absolute_any_platform(r"\\nas\flights\img.jpg")


def test_posix_path_is_absolute():
    assert is_absolute_any_platform("/Volumes/SD/img.jpg")


def test_relative_paths_are_not_absolute():
    assert not is_absolute_any_platform("Flight1/img.jpg")
    assert not is_absolute_any_platform(r"Flight1\img.jpg")
    assert not is_absolute_any_platform("../Flight1/img.jpg")
    assert not is_absolute_any_platform("")
    assert not is_absolute_any_platform(None)


def test_drive_letter_without_separator_is_not_absolute():
    """"C:img.jpg" is a drive-relative path, not an absolute one."""
    assert not is_absolute_any_platform("C:img.jpg")


# --------------------------- normalize_filename_key ----------------------- #

def test_normalization_key_is_case_insensitive():
    assert normalize_filename_key("DJI_0042.JPG") == normalize_filename_key("dji_0042.jpg")


def test_normalization_key_unifies_nfd_and_nfc():
    """macOS stores filenames decomposed; Windows/Linux compose them."""
    composed = unicodedata.normalize("NFC", "Sétx_01.JPG")
    decomposed = unicodedata.normalize("NFD", "Sétx_01.JPG")
    assert composed != decomposed, "test needs a name that differs between forms"
    assert normalize_filename_key(composed) == normalize_filename_key(decomposed)


def test_normalization_key_of_empty():
    assert normalize_filename_key("") == ""
    assert normalize_filename_key(None) == ""


# --------------------------- index_folder_by_filename --------------------- #

def test_index_finds_nested_files(tmp_path):
    """Drone media is normally nested (DCIM/100MEDIA/...)."""
    nested = tmp_path / "DCIM" / "100MEDIA"
    nested.mkdir(parents=True)
    (nested / "DJI_0042.JPG").write_text("x")
    index = index_folder_by_filename(str(tmp_path))
    assert find_in_index(r"C:\elsewhere\DJI_0042.JPG", index) == str(nested / "DJI_0042.JPG")


def test_index_non_recursive_skips_subfolders(tmp_path):
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "a.jpg").write_text("x")
    index = index_folder_by_filename(str(tmp_path), recursive=False)
    assert find_in_index("a.jpg", index) is None


def test_index_matches_case_insensitively(tmp_path):
    (tmp_path / "DJI_0042.jpg").write_text("x")
    index = index_folder_by_filename(str(tmp_path))
    assert find_in_index("DJI_0042.JPG", index) == str(tmp_path / "DJI_0042.jpg")


def test_index_prefers_shallowest_duplicate(tmp_path):
    (tmp_path / "dup.jpg").write_text("x")
    deep = tmp_path / "sub"
    deep.mkdir()
    (deep / "dup.jpg").write_text("x")
    index = index_folder_by_filename(str(tmp_path))
    assert find_in_index("dup.jpg", index) == str(tmp_path / "dup.jpg")


def test_index_of_missing_folder_is_empty():
    assert index_folder_by_filename("/definitely/not/a/folder") == {}
    assert index_folder_by_filename("") == {}


def test_index_respects_max_entries(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.jpg").write_text("x")
    index = index_folder_by_filename(str(tmp_path), max_entries=3)
    assert len(index) == 3


def test_index_is_deterministic(tmp_path):
    for name in ("b.jpg", "a.jpg", "c.jpg"):
        (tmp_path / name).write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.jpg").write_text("x")
    first = index_folder_by_filename(str(tmp_path))
    second = index_folder_by_filename(str(tmp_path))
    assert first == second


def test_find_in_index_miss_returns_none(tmp_path):
    (tmp_path / "a.jpg").write_text("x")
    index = index_folder_by_filename(str(tmp_path))
    assert find_in_index("nope.jpg", index) is None
    assert find_in_index("", index) is None


def test_index_uses_os_sep_paths(tmp_path):
    (tmp_path / "a.jpg").write_text("x")
    index = index_folder_by_filename(str(tmp_path))
    assert os.path.isabs(index[normalize_filename_key("a.jpg")])
