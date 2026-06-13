#!/usr/bin/env python3
"""
method_lab.py - Launcher for the ADIAT Method Test Lab (dev tool).

Usage:
    python scripts/method_lab.py [image.jpg]

Puts the repository's app/ (for core.* / algorithms.* imports) and
scripts/ (for the method_lab package) on sys.path, then starts the lab.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (os.path.join(_ROOT, 'app'), os.path.join(_ROOT, 'scripts')):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from method_lab.__main__ import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
