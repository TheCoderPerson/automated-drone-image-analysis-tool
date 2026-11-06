# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'SnowTrackWizard.ui'
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
from PySide6.QtWidgets import (QApplication, QDoubleSpinBox, QHBoxLayout, QLabel,
    QRadioButton, QSizePolicy, QSpacerItem, QVBoxLayout,
    QWidget)

class Ui_SnowTrackWizard(object):
    def setupUi(self, SnowTrackWizard):
        if not SnowTrackWizard.objectName():
            SnowTrackWizard.setObjectName(u"SnowTrackWizard")
        self.verticalLayout_root = QVBoxLayout(SnowTrackWizard)
        self.verticalLayout_root.setObjectName(u"verticalLayout_root")
        self.verticalLayout_root.setContentsMargins(0, 5, 0, 0)
        self.widgetTrackType = QWidget(SnowTrackWizard)
        self.widgetTrackType.setObjectName(u"widgetTrackType")
        self.verticalLayout_trackType = QVBoxLayout(self.widgetTrackType)
        self.verticalLayout_trackType.setObjectName(u"verticalLayout_trackType")
        self.labelTrackType = QLabel(self.widgetTrackType)
        self.labelTrackType.setObjectName(u"labelTrackType")
        font = QFont()
        font.setPointSize(12)
        self.labelTrackType.setFont(font)
        self.labelTrackType.setWordWrap(True)

        self.verticalLayout_trackType.addWidget(self.labelTrackType)

        self.horizontalLayout_trackType = QHBoxLayout()
        self.horizontalLayout_trackType.setSpacing(20)
        self.horizontalLayout_trackType.setObjectName(u"horizontalLayout_trackType")
        self.radioPosthole = QRadioButton(self.widgetTrackType)
        self.radioPosthole.setObjectName(u"radioPosthole")
        font1 = QFont()
        font1.setPointSize(11)
        self.radioPosthole.setFont(font1)
        self.radioPosthole.setChecked(True)

        self.horizontalLayout_trackType.addWidget(self.radioPosthole)

        self.radioBoot = QRadioButton(self.widgetTrackType)
        self.radioBoot.setObjectName(u"radioBoot")
        self.radioBoot.setFont(font1)

        self.horizontalLayout_trackType.addWidget(self.radioBoot)

        self.horizontalSpacer_trackType = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_trackType.addItem(self.horizontalSpacer_trackType)


        self.verticalLayout_trackType.addLayout(self.horizontalLayout_trackType)


        self.verticalLayout_root.addWidget(self.widgetTrackType)

        self.widgetGsd = QWidget(SnowTrackWizard)
        self.widgetGsd.setObjectName(u"widgetGsd")
        self.verticalLayout_gsd = QVBoxLayout(self.widgetGsd)
        self.verticalLayout_gsd.setObjectName(u"verticalLayout_gsd")
        self.labelGsd = QLabel(self.widgetGsd)
        self.labelGsd.setObjectName(u"labelGsd")
        self.labelGsd.setFont(font)
        self.labelGsd.setWordWrap(True)

        self.verticalLayout_gsd.addWidget(self.labelGsd)

        self.horizontalLayout_gsdMode = QHBoxLayout()
        self.horizontalLayout_gsdMode.setSpacing(20)
        self.horizontalLayout_gsdMode.setObjectName(u"horizontalLayout_gsdMode")
        self.radioGsdAuto = QRadioButton(self.widgetGsd)
        self.radioGsdAuto.setObjectName(u"radioGsdAuto")
        self.radioGsdAuto.setFont(font1)
        self.radioGsdAuto.setChecked(True)

        self.horizontalLayout_gsdMode.addWidget(self.radioGsdAuto)

        self.radioGsdManual = QRadioButton(self.widgetGsd)
        self.radioGsdManual.setObjectName(u"radioGsdManual")
        self.radioGsdManual.setFont(font1)

        self.horizontalLayout_gsdMode.addWidget(self.radioGsdManual)

        self.horizontalSpacer_gsdMode = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_gsdMode.addItem(self.horizontalSpacer_gsdMode)


        self.verticalLayout_gsd.addLayout(self.horizontalLayout_gsdMode)

        self.horizontalLayout_gsdValue = QHBoxLayout()
        self.horizontalLayout_gsdValue.setObjectName(u"horizontalLayout_gsdValue")
        self.labelGsdValue = QLabel(self.widgetGsd)
        self.labelGsdValue.setObjectName(u"labelGsdValue")
        self.labelGsdValue.setFont(font1)

        self.horizontalLayout_gsdValue.addWidget(self.labelGsdValue)

        self.gsdSpinBox = QDoubleSpinBox(self.widgetGsd)
        self.gsdSpinBox.setObjectName(u"gsdSpinBox")
        self.gsdSpinBox.setFont(font1)
        self.gsdSpinBox.setDecimals(1)
        self.gsdSpinBox.setMinimum(0.500000000000000)
        self.gsdSpinBox.setMaximum(50.000000000000000)
        self.gsdSpinBox.setSingleStep(0.500000000000000)
        self.gsdSpinBox.setValue(8.000000000000000)

        self.horizontalLayout_gsdValue.addWidget(self.gsdSpinBox)

        self.labelGsdNote = QLabel(self.widgetGsd)
        self.labelGsdNote.setObjectName(u"labelGsdNote")
        font2 = QFont()
        font2.setPointSize(11)
        font2.setItalic(True)
        self.labelGsdNote.setFont(font2)
        self.labelGsdNote.setWordWrap(True)

        self.horizontalLayout_gsdValue.addWidget(self.labelGsdNote)

        self.horizontalSpacer_gsdValue = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_gsdValue.addItem(self.horizontalSpacer_gsdValue)


        self.verticalLayout_gsd.addLayout(self.horizontalLayout_gsdValue)


        self.verticalLayout_root.addWidget(self.widgetGsd)

        self.widgetAggressiveness = QWidget(SnowTrackWizard)
        self.widgetAggressiveness.setObjectName(u"widgetAggressiveness")
        self.verticalLayout_aggr = QVBoxLayout(self.widgetAggressiveness)
        self.verticalLayout_aggr.setSpacing(3)
        self.verticalLayout_aggr.setObjectName(u"verticalLayout_aggr")
        self.labelAggressiveness = QLabel(self.widgetAggressiveness)
        self.labelAggressiveness.setObjectName(u"labelAggressiveness")
        self.labelAggressiveness.setFont(font)

        self.verticalLayout_aggr.addWidget(self.labelAggressiveness)

        self.labelNote = QLabel(self.widgetAggressiveness)
        self.labelNote.setObjectName(u"labelNote")
        self.labelNote.setFont(font2)
        self.labelNote.setWordWrap(True)

        self.verticalLayout_aggr.addWidget(self.labelNote)

        self.aggressivenessSliderPlaceholder = QWidget(self.widgetAggressiveness)
        self.aggressivenessSliderPlaceholder.setObjectName(u"aggressivenessSliderPlaceholder")
        self.aggressivenessSliderPlaceholder.setMinimumSize(QSize(600, 60))

        self.verticalLayout_aggr.addWidget(self.aggressivenessSliderPlaceholder)


        self.verticalLayout_root.addWidget(self.widgetAggressiveness)

        self.verticalSpacer_bottom = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_root.addItem(self.verticalSpacer_bottom)


        self.retranslateUi(SnowTrackWizard)

        QMetaObject.connectSlotsByName(SnowTrackWizard)
    # setupUi

    def retranslateUi(self, SnowTrackWizard):
        self.labelTrackType.setText(QCoreApplication.translate("SnowTrackWizard", u"What kind of foot tracks are you looking for?", None))
#if QT_CONFIG(tooltip)
        self.radioPosthole.setToolTip(QCoreApplication.translate("SnowTrackWizard", u"Round holes about 25-35 cm across, 40-70 cm apart, left by someone sinking into deep, soft snow.", None))
#endif // QT_CONFIG(tooltip)
        self.radioPosthole.setText(QCoreApplication.translate("SnowTrackWizard", u"Postholes in deep, soft snow", None))
#if QT_CONFIG(tooltip)
        self.radioBoot.setToolTip(QCoreApplication.translate("SnowTrackWizard", u"Smaller boot prints about 20 cm across, 50-100 cm apart, in shallow or packed snow.", None))
#endif // QT_CONFIG(tooltip)
        self.radioBoot.setText(QCoreApplication.translate("SnowTrackWizard", u"Boot prints in shallow or packed snow", None))
        self.labelGsd.setText(QCoreApplication.translate("SnowTrackWizard", u"How should ADIAT determine the ground sample distance (GSD) of each image?", None))
#if QT_CONFIG(tooltip)
        self.radioGsdAuto.setToolTip(QCoreApplication.translate("SnowTrackWizard", u"Calculate each image's GSD from its altitude and camera metadata.", None))
#endif // QT_CONFIG(tooltip)
        self.radioGsdAuto.setText(QCoreApplication.translate("SnowTrackWizard", u"From image altitude and camera data", None))
#if QT_CONFIG(tooltip)
        self.radioGsdManual.setToolTip(QCoreApplication.translate("SnowTrackWizard", u"Use the same GSD for every image, e.g. when flying a fixed height over steep terrain.", None))
#endif // QT_CONFIG(tooltip)
        self.radioGsdManual.setText(QCoreApplication.translate("SnowTrackWizard", u"Use a fixed value", None))
        self.labelGsdValue.setText(QCoreApplication.translate("SnowTrackWizard", u"GSD (cm/px):", None))
        self.labelGsdNote.setText(QCoreApplication.translate("SnowTrackWizard", u"Also used for any image without usable altitude or camera metadata.", None))
        self.labelAggressiveness.setText(QCoreApplication.translate("SnowTrackWizard", u"How aggressively should ADIAT search for tracks?", None))
        self.labelNote.setText(QCoreApplication.translate("SnowTrackWizard", u"Note: A higher setting finds fainter and shorter trails but may also increase false positives.", None))
        pass
    # retranslateUi

