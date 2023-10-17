# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'C:\Users\charl\source\repos\crgrove\automated-drone-image-analysis-tool\resources/views\Viewer.ui'
#
# Created by: PyQt5 UI code generator 5.15.9
#
# WARNING: Any manual changes made to this file will be lost when pyuic5 is
# run again.  Do not edit this file unless you know what you are doing.


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_Viewer(object):
    def setupUi(self, Viewer):
        Viewer.setObjectName("Viewer")
        Viewer.resize(1040, 793)
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap("C:\\Users\\charl\\source\\repos\\crgrove\\automated-drone-image-analysis-tool\\resources/views\\../icons/ADIAT.ico"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        Viewer.setWindowIcon(icon)
        self.centralwidget = QtWidgets.QWidget(Viewer)
        self.centralwidget.setObjectName("centralwidget")
        self.verticalLayout = QtWidgets.QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName("verticalLayout")
        self.TitleWidget = QtWidgets.QWidget(self.centralwidget)
        self.TitleWidget.setObjectName("TitleWidget")
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout(self.TitleWidget)
        self.horizontalLayout_2.setContentsMargins(0, 9, 0, -1)
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.fileNameLabel = QtWidgets.QLabel(self.TitleWidget)
        font = QtGui.QFont()
        font.setPointSize(16)
        self.fileNameLabel.setFont(font)
        self.fileNameLabel.setObjectName("fileNameLabel")
        self.horizontalLayout_2.addWidget(self.fileNameLabel)
        self.indexLabel = QtWidgets.QLabel(self.TitleWidget)
        font = QtGui.QFont()
        font.setPointSize(16)
        self.indexLabel.setFont(font)
        self.indexLabel.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.indexLabel.setObjectName("indexLabel")
        self.horizontalLayout_2.addWidget(self.indexLabel)
        self.areaCountLabel = QtWidgets.QLabel(self.TitleWidget)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.areaCountLabel.sizePolicy().hasHeightForWidth())
        self.areaCountLabel.setSizePolicy(sizePolicy)
        self.areaCountLabel.setMinimumSize(QtCore.QSize(250, 0))
        self.areaCountLabel.setMaximumSize(QtCore.QSize(250, 16777215))
        font = QtGui.QFont()
        font.setPointSize(16)
        self.areaCountLabel.setFont(font)
        self.areaCountLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.areaCountLabel.setObjectName("areaCountLabel")
        self.horizontalLayout_2.addWidget(self.areaCountLabel)
        self.verticalLayout.addWidget(self.TitleWidget)
        self.ImageLayout = QtWidgets.QHBoxLayout()
        self.ImageLayout.setObjectName("ImageLayout")
        self.placeholderImage = QtWidgets.QGraphicsView(self.centralwidget)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.MinimumExpanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.placeholderImage.sizePolicy().hasHeightForWidth())
        self.placeholderImage.setSizePolicy(sizePolicy)
        self.placeholderImage.setMinimumSize(QtCore.QSize(0, 650))
        font = QtGui.QFont()
        font.setPointSize(9)
        self.placeholderImage.setFont(font)
        self.placeholderImage.setObjectName("placeholderImage")
        self.ImageLayout.addWidget(self.placeholderImage)
        self.aoiListWidget = QtWidgets.QListWidget(self.centralwidget)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.aoiListWidget.sizePolicy().hasHeightForWidth())
        self.aoiListWidget.setSizePolicy(sizePolicy)
        self.aoiListWidget.setMinimumSize(QtCore.QSize(250, 0))
        self.aoiListWidget.setObjectName("aoiListWidget")
        self.ImageLayout.addWidget(self.aoiListWidget)
        self.verticalLayout.addLayout(self.ImageLayout)
        self.ButtonLayour = QtWidgets.QHBoxLayout()
        self.ButtonLayour.setObjectName("ButtonLayour")
        spacerItem = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.ButtonLayour.addItem(spacerItem)
        self.jumpToLabel = QtWidgets.QLabel(self.centralwidget)
        self.jumpToLabel.setObjectName("jumpToLabel")
        self.ButtonLayour.addWidget(self.jumpToLabel)
        self.jumpToLine = QtWidgets.QLineEdit(self.centralwidget)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.jumpToLine.sizePolicy().hasHeightForWidth())
        self.jumpToLine.setSizePolicy(sizePolicy)
        self.jumpToLine.setMinimumSize(QtCore.QSize(50, 0))
        self.jumpToLine.setMaximumSize(QtCore.QSize(50, 16777215))
        self.jumpToLine.setObjectName("jumpToLine")
        self.ButtonLayour.addWidget(self.jumpToLine)
        self.previousImageButton = QtWidgets.QPushButton(self.centralwidget)
        font = QtGui.QFont()
        font.setPointSize(10)
        self.previousImageButton.setFont(font)
        icon1 = QtGui.QIcon()
        icon1.addPixmap(QtGui.QPixmap(":/icons/previous.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.previousImageButton.setIcon(icon1)
        self.previousImageButton.setObjectName("previousImageButton")
        self.ButtonLayour.addWidget(self.previousImageButton)
        self.nextImageButton = QtWidgets.QPushButton(self.centralwidget)
        font = QtGui.QFont()
        font.setPointSize(10)
        self.nextImageButton.setFont(font)
        self.nextImageButton.setLayoutDirection(QtCore.Qt.RightToLeft)
        icon2 = QtGui.QIcon()
        icon2.addPixmap(QtGui.QPixmap(":/icons/next.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.nextImageButton.setIcon(icon2)
        self.nextImageButton.setObjectName("nextImageButton")
        self.ButtonLayour.addWidget(self.nextImageButton)
        spacerItem1 = QtWidgets.QSpacerItem(140, 0, QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Minimum)
        self.ButtonLayour.addItem(spacerItem1)
        self.KmlButton = QtWidgets.QPushButton(self.centralwidget)
        font = QtGui.QFont()
        font.setPointSize(10)
        self.KmlButton.setFont(font)
        icon3 = QtGui.QIcon()
        icon3.addPixmap(QtGui.QPixmap(":/icons/download.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.KmlButton.setIcon(icon3)
        self.KmlButton.setObjectName("KmlButton")
        self.ButtonLayour.addWidget(self.KmlButton)
        self.verticalLayout.addLayout(self.ButtonLayour)
        Viewer.setCentralWidget(self.centralwidget)
        self.statusbar = QtWidgets.QStatusBar(Viewer)
        self.statusbar.setObjectName("statusbar")
        Viewer.setStatusBar(self.statusbar)
        self.actionOpen = QtWidgets.QAction(Viewer)
        self.actionOpen.setObjectName("actionOpen")

        self.retranslateUi(Viewer)
        QtCore.QMetaObject.connectSlotsByName(Viewer)

    def retranslateUi(self, Viewer):
        _translate = QtCore.QCoreApplication.translate
        Viewer.setWindowTitle(_translate("Viewer", "Automated Drone Image Analysis Tool :: Viewer - Sponsored by TEXSAR"))
        self.fileNameLabel.setText(_translate("Viewer", "TextLabel"))
        self.indexLabel.setText(_translate("Viewer", "TextLabel"))
        self.areaCountLabel.setText(_translate("Viewer", "TextLabel"))
        self.jumpToLabel.setText(_translate("Viewer", "Jump To:"))
        self.previousImageButton.setText(_translate("Viewer", "Previous Image"))
        self.nextImageButton.setText(_translate("Viewer", "Next Image"))
        self.KmlButton.setText(_translate("Viewer", " Generate KML"))
        self.actionOpen.setText(_translate("Viewer", "Open"))
from . import resources_rc
