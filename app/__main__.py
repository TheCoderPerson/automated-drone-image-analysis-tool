import sys
from PyQt5.QtGui import QFontDatabase, QFont, QIcon
from PyQt5.QtCore import QFile, QTextStream, QTranslator, QLocale
from PyQt5.QtWidgets import QApplication
from multiprocessing import freeze_support
from core.controllers.MainWindow import MainWindow
# import faulthandler
import qdarktheme
from core.services.LoggerService import LoggerService
from os import path

version = '1.4.0'


def main():
    """
    Initialize the application, set the theme, icon, and launch the main window.

    The function sets up the QApplication, applies the dark theme, sets the application icon,
    and displays the MainWindow with the specified version. Ends the application on window close.
    """
    app = QApplication(sys.argv)
    qdarktheme.setup_theme()
    app.setWindowIcon(QIcon(path.abspath(path.join(path.dirname(__file__), 'ADIAT.ico'))))
    mw = MainWindow(qdarktheme, version)
    mw.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    # faulthandler.enable()
    freeze_support()
    main()
