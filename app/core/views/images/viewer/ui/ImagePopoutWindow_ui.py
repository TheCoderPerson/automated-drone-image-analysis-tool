# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ImagePopoutWindow.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QSizePolicy, QVBoxLayout, QWidget)

class Ui_ImagePopoutWindow(object):
    def setupUi(self, ImagePopoutWindow):
        if not ImagePopoutWindow.objectName():
            ImagePopoutWindow.setObjectName(u"ImagePopoutWindow")
        ImagePopoutWindow.resize(1400, 900)
        self.hostLayout = QVBoxLayout(ImagePopoutWindow)
        self.hostLayout.setSpacing(2)
        self.hostLayout.setObjectName(u"hostLayout")
        self.hostLayout.setContentsMargins(2, 2, 2, 2)

        self.retranslateUi(ImagePopoutWindow)

        QMetaObject.connectSlotsByName(ImagePopoutWindow)
    # setupUi

    def retranslateUi(self, ImagePopoutWindow):
        ImagePopoutWindow.setWindowTitle(QCoreApplication.translate("ImagePopoutWindow", u"Image View", None))
    # retranslateUi

