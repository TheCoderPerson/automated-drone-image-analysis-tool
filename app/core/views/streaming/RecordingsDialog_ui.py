# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'RecordingsDialog.ui'
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
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
    QSpacerItem, QVBoxLayout, QWidget)

class Ui_RecordingsDialog(object):
    def setupUi(self, RecordingsDialog):
        if not RecordingsDialog.objectName():
            RecordingsDialog.setObjectName(u"RecordingsDialog")
        RecordingsDialog.resize(560, 420)
        self.mainLayout = QVBoxLayout(RecordingsDialog)
        self.mainLayout.setObjectName(u"mainLayout")
        self.headerLabel = QLabel(RecordingsDialog)
        self.headerLabel.setObjectName(u"headerLabel")

        self.mainLayout.addWidget(self.headerLabel)

        self.recordingList = QListWidget(RecordingsDialog)
        self.recordingList.setObjectName(u"recordingList")
        self.recordingList.setAlternatingRowColors(True)

        self.mainLayout.addWidget(self.recordingList)

        self.emptyLabel = QLabel(RecordingsDialog)
        self.emptyLabel.setObjectName(u"emptyLabel")
        self.emptyLabel.setWordWrap(True)

        self.mainLayout.addWidget(self.emptyLabel)

        self.buttonLayout = QHBoxLayout()
        self.buttonLayout.setObjectName(u"buttonLayout")
        self.browseButton = QPushButton(RecordingsDialog)
        self.browseButton.setObjectName(u"browseButton")

        self.buttonLayout.addWidget(self.browseButton)

        self.buttonSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.buttonLayout.addItem(self.buttonSpacer)

        self.openButton = QPushButton(RecordingsDialog)
        self.openButton.setObjectName(u"openButton")
        self.openButton.setEnabled(False)

        self.buttonLayout.addWidget(self.openButton)

        self.cancelButton = QPushButton(RecordingsDialog)
        self.cancelButton.setObjectName(u"cancelButton")

        self.buttonLayout.addWidget(self.cancelButton)


        self.mainLayout.addLayout(self.buttonLayout)


        self.retranslateUi(RecordingsDialog)

        self.openButton.setDefault(True)


        QMetaObject.connectSlotsByName(RecordingsDialog)
    # setupUi

    def retranslateUi(self, RecordingsDialog):
        RecordingsDialog.setWindowTitle(QCoreApplication.translate("RecordingsDialog", u"Recordings", None))
        self.headerLabel.setText(QCoreApplication.translate("RecordingsDialog", u"Choose a recording to replay. Double-click plays it.", None))
        self.emptyLabel.setText(QCoreApplication.translate("RecordingsDialog", u"No recordings yet. Recordings appear here automatically when you stop one, or use Browse to open a recording folder from another machine.", None))
        self.browseButton.setText(QCoreApplication.translate("RecordingsDialog", u"Browse\u2026", None))
#if QT_CONFIG(tooltip)
        self.browseButton.setToolTip(QCoreApplication.translate("RecordingsDialog", u"Open a recording video that is not in this list.", None))
#endif // QT_CONFIG(tooltip)
        self.openButton.setText(QCoreApplication.translate("RecordingsDialog", u"Replay", None))
        self.cancelButton.setText(QCoreApplication.translate("RecordingsDialog", u"Cancel", None))
    # retranslateUi

