"""PathHelper - cross-platform path utilities for relocated result files.

``ADIAT_Data.xml`` travels between machines: a flight analyzed on a Windows
ground station is routinely reviewed on a Mac, results are shared between
searchers, and folders get moved onto external drives between the analysis and
the review. The stored image and mask paths are whatever the *analyzing*
machine wrote, so any code that re-derives a filename or re-locates a moved
file has to be agnostic about:

* **separators** - ``os.path`` is platform-bound. On POSIX a backslash is an
  ordinary filename character, so ``os.path.basename`` returns a
  Windows-authored path whole instead of its last component.
* **case** - ``DJI_0042.JPG`` vs ``DJI_0042.jpg``.
* **Unicode normalization** - macOS stores filenames decomposed (NFD) while
  Windows and most Linux tooling produce composed (NFC), so the same name can
  differ byte-for-byte across machines.
"""

import os
import unicodedata

_SEPARATORS = ('/', '\\')


def cross_platform_basename(path):
    """Return the last component of *path*, splitting on both / and \\.

    ``os.path.basename`` only recognizes the running platform's separator, so
    on macOS/Linux a Windows-authored path such as
    ``C:\\Flight1\\DJI_0042.JPG`` comes back unchanged. Result files move
    between machines, so filenames must be derived identically everywhere.

    Args:
        path (str): A path written by any platform, absolute or relative.

    Returns:
        str: The final path component, or '' when *path* is empty.
    """
    if not path:
        return ''
    normalized = path
    for sep in _SEPARATORS:
        normalized = normalized.replace(sep, os.sep)
    return os.path.basename(normalized.rstrip(os.sep))


def is_absolute_any_platform(path):
    """True when *path* is absolute on the platform that wrote it.

    ``os.path.isabs`` is platform-bound, so on POSIX it reports a Windows
    drive-letter path (``C:\\Flight1\\img.jpg``) or a UNC path
    (``\\\\nas\\flights\\img.jpg``) as *relative*. Joining such a path onto a
    local directory produces a nonsense path, which then fails to resolve for a
    reason that has nothing to do with where the file actually is.

    Args:
        path (str): A path written by any platform.

    Returns:
        bool: True if the path is absolute under POSIX or Windows rules.
    """
    if not path:
        return False
    if os.path.isabs(path):
        return True
    # UNC share, e.g. \\nas\flights\img.jpg
    if path.startswith('\\\\'):
        return True
    # Windows drive letter, e.g. C:\flights\img.jpg or C:/flights/img.jpg
    if len(path) >= 3 and path[1] == ':' and path[0].isalpha() and path[2] in _SEPARATORS:
        return True
    return False


def normalize_filename_key(filename):
    """Return a case- and Unicode-insensitive matching key for *filename*.

    Args:
        filename (str): A bare filename (not a path).

    Returns:
        str: Key suitable for dictionary lookup, or '' when *filename* is empty.
    """
    if not filename:
        return ''
    return unicodedata.normalize('NFC', filename).casefold()


def index_folder_by_filename(folder, recursive=True, max_entries=200000):
    """Map normalized filename -> full path for every file under *folder*.

    Built once per recovery rather than stat-ing each candidate individually: a
    flight folder holds thousands of captures and the caller has thousands of
    names to resolve against it, so one walk beats N syscalls per name. Nested
    layouts are the norm for drone media (``DCIM/100MEDIA/...``), so the walk
    recurses by default.

    ``os.walk`` is top-down and directory names are sorted, so the traversal is
    deterministic and the shallowest match for a duplicated filename wins.

    Args:
        folder (str): Directory to index.
        recursive (bool): Walk subdirectories. When False, only *folder* itself.
        max_entries (int): Safety bound on files examined, so pointing the
            recovery at a huge tree (a home directory, a whole volume) cannot
            hang the GUI thread indefinitely.

    Returns:
        dict: normalized filename -> absolute path. Empty when *folder* is not
        a readable directory.
    """
    index = {}
    if not folder or not os.path.isdir(folder):
        return index

    examined = 0
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            key = normalize_filename_key(name)
            if key and key not in index:
                index[key] = os.path.join(root, name)
            examined += 1
            if examined >= max_entries:
                return index
        if not recursive:
            break
    return index


def find_in_index(stored_path, index):
    """Resolve *stored_path*'s filename against a pre-built folder *index*.

    Args:
        stored_path (str): The path recorded in the result file, from any
            platform.
        index (dict): Mapping from :func:`index_folder_by_filename`.

    Returns:
        str or None: The located path, or None when the filename is not present.
    """
    return index.get(normalize_filename_key(cross_platform_basename(stored_path)))
