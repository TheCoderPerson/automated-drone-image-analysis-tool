# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ReplayWindow.ui'
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
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QSizePolicy, QSpacerItem, QSplitter,
    QVBoxLayout, QWidget)

class Ui_ReplayWindow(object):
    def setupUi(self, ReplayWindow):
        if not ReplayWindow.objectName():
            ReplayWindow.setObjectName(u"ReplayWindow")
        ReplayWindow.resize(1280, 760)
        self.centralwidget = QWidget(ReplayWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.rootLayout = QVBoxLayout(self.centralwidget)
        self.rootLayout.setObjectName(u"rootLayout")
        self.headerLayout = QHBoxLayout()
        self.headerLayout.setObjectName(u"headerLayout")
        self.headerLabel = QLabel(self.centralwidget)
        self.headerLabel.setObjectName(u"headerLabel")
        self.headerLabel.setStyleSheet(u"QLabel { font-weight: bold; }")

        self.headerLayout.addWidget(self.headerLabel)

        self.headerSpacer = QSpacerItem(40, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.headerLayout.addItem(self.headerSpacer)

        self.exportButton = QPushButton(self.centralwidget)
        self.exportButton.setObjectName(u"exportButton")
        self.exportButton.setEnabled(False)

        self.headerLayout.addWidget(self.exportButton)

        self.openFolderButton = QPushButton(self.centralwidget)
        self.openFolderButton.setObjectName(u"openFolderButton")
        self.openFolderButton.setEnabled(False)

        self.headerLayout.addWidget(self.openFolderButton)


        self.rootLayout.addLayout(self.headerLayout)

        self.splitter = QSplitter(self.centralwidget)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.videoPane = QWidget(self.splitter)
        self.videoPane.setObjectName(u"videoPane")
        self.videoLayout = QVBoxLayout(self.videoPane)
        self.videoLayout.setObjectName(u"videoLayout")
        self.videoLayout.setContentsMargins(0, 0, 0, 0)
        self.videoPlaceholder = QLabel(self.videoPane)
        self.videoPlaceholder.setObjectName(u"videoPlaceholder")

        self.videoLayout.addWidget(self.videoPlaceholder)

        self.playbackPlaceholder = QLabel(self.videoPane)
        self.playbackPlaceholder.setObjectName(u"playbackPlaceholder")

        self.videoLayout.addWidget(self.playbackPlaceholder)

        self.splitter.addWidget(self.videoPane)
        self.sideSplitter = QSplitter(self.splitter)
        self.sideSplitter.setObjectName(u"sideSplitter")
        self.sideSplitter.setOrientation(Qt.Vertical)
        self.galleryPlaceholder = QLabel(self.sideSplitter)
        self.galleryPlaceholder.setObjectName(u"galleryPlaceholder")
        self.sideSplitter.addWidget(self.galleryPlaceholder)
        self.mapPlaceholder = QLabel(self.sideSplitter)
        self.mapPlaceholder.setObjectName(u"mapPlaceholder")
        self.sideSplitter.addWidget(self.mapPlaceholder)
        self.splitter.addWidget(self.sideSplitter)

        self.rootLayout.addWidget(self.splitter)

        ReplayWindow.setCentralWidget(self.centralwidget)

        self.retranslateUi(ReplayWindow)

        QMetaObject.connectSlotsByName(ReplayWindow)
    # setupUi

    def retranslateUi(self, ReplayWindow):
        ReplayWindow.setWindowTitle(QCoreApplication.translate("ReplayWindow", u"Recording Replay", None))
        self.headerLabel.setText(QCoreApplication.translate("ReplayWindow", u"No recording loaded", None))
        self.exportButton.setText(QCoreApplication.translate("ReplayWindow", u"Export\u2026", None))
#if QT_CONFIG(tooltip)
        self.exportButton.setToolTip(QCoreApplication.translate("ReplayWindow", u"Write this recording's shareable files: results for the Image Analysis window, CSV tables, an offline map page and a KML.", None))
#endif // QT_CONFIG(tooltip)
        self.openFolderButton.setText(QCoreApplication.translate("ReplayWindow", u"Open Folder", None))
        self.videoPlaceholder.setText(QCoreApplication.translate("ReplayWindow", u"Video", None))
        self.playbackPlaceholder.setText(QCoreApplication.translate("ReplayWindow", u"Playback", None))
        self.galleryPlaceholder.setText(QCoreApplication.translate("ReplayWindow", u"Detections", None))
        self.mapPlaceholder.setText(QCoreApplication.translate("ReplayWindow", u"Map", None))
    # retranslateUi

