"""
__main__.py - Method Test Lab bootstrap.

Expects the repository's app/ and scripts/ directories to already be on
sys.path (scripts/method_lab.py arranges that).
"""

import argparse
import sys

from PySide6.QtWidgets import QApplication


def main(argv=None):
    """Launch the Method Test Lab window."""
    parser = argparse.ArgumentParser(
        prog='method_lab',
        description='ADIAT Method Test Lab — single-image detection sandbox.'
    )
    parser.add_argument('image', nargs='?', default=None,
                        help='Drone image to load on startup')
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)

    from method_lab.lab_window import MethodLabWindow
    window = MethodLabWindow(args.image)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
