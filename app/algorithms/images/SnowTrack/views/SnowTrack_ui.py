# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'SnowTrack.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QHBoxLayout,
    QLabel, QSizePolicy, QSlider, QSpacerItem,
    QSpinBox, QVBoxLayout, QWidget)

class Ui_SnowTrack(object):
    def setupUi(self, SnowTrack):
        if not SnowTrack.objectName():
            SnowTrack.setObjectName(u"SnowTrack")
        SnowTrack.resize(760, 110)
        self.verticalLayout = QVBoxLayout(SnowTrack)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.horizontalLayout_gsd = QHBoxLayout()
        self.horizontalLayout_gsd.setObjectName(u"horizontalLayout_gsd")
        self.gsdModeLabel = QLabel(SnowTrack)
        self.gsdModeLabel.setObjectName(u"gsdModeLabel")
        font = QFont()
        font.setPointSize(10)
        self.gsdModeLabel.setFont(font)

        self.horizontalLayout_gsd.addWidget(self.gsdModeLabel)

        self.gsdModeComboBox = QComboBox(SnowTrack)
        self.gsdModeComboBox.addItem("")
        self.gsdModeComboBox.addItem("")
        self.gsdModeComboBox.setObjectName(u"gsdModeComboBox")
        self.gsdModeComboBox.setFont(font)

        self.horizontalLayout_gsd.addWidget(self.gsdModeComboBox)

        self.horizontalSpacer_gsd = QSpacerItem(12, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_gsd.addItem(self.horizontalSpacer_gsd)

        self.gsdValueLabel = QLabel(SnowTrack)
        self.gsdValueLabel.setObjectName(u"gsdValueLabel")
        self.gsdValueLabel.setFont(font)

        self.horizontalLayout_gsd.addWidget(self.gsdValueLabel)

        self.gsdSpinBox = QDoubleSpinBox(SnowTrack)
        self.gsdSpinBox.setObjectName(u"gsdSpinBox")
        self.gsdSpinBox.setFont(font)
        self.gsdSpinBox.setDecimals(1)
        self.gsdSpinBox.setMinimum(0.500000000000000)
        self.gsdSpinBox.setMaximum(50.000000000000000)
        self.gsdSpinBox.setSingleStep(0.500000000000000)
        self.gsdSpinBox.setValue(8.000000000000000)

        self.horizontalLayout_gsd.addWidget(self.gsdSpinBox)

        self.horizontalSpacer_sensitivity = QSpacerItem(20, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_gsd.addItem(self.horizontalSpacer_sensitivity)

        self.sensitivityLabel = QLabel(SnowTrack)
        self.sensitivityLabel.setObjectName(u"sensitivityLabel")
        self.sensitivityLabel.setFont(font)

        self.horizontalLayout_gsd.addWidget(self.sensitivityLabel)

        self.sensitivitySlider = QSlider(SnowTrack)
        self.sensitivitySlider.setObjectName(u"sensitivitySlider")
        self.sensitivitySlider.setMinimum(1)
        self.sensitivitySlider.setMaximum(10)
        self.sensitivitySlider.setPageStep(1)
        self.sensitivitySlider.setValue(5)
        self.sensitivitySlider.setOrientation(Qt.Horizontal)
        self.sensitivitySlider.setTickPosition(QSlider.TicksBelow)
        self.sensitivitySlider.setTickInterval(1)

        self.horizontalLayout_gsd.addWidget(self.sensitivitySlider)

        self.sensitivityValueLabel = QLabel(SnowTrack)
        self.sensitivityValueLabel.setObjectName(u"sensitivityValueLabel")
        self.sensitivityValueLabel.setMinimumSize(QSize(30, 0))
        font1 = QFont()
        font1.setPointSize(10)
        font1.setBold(True)
        self.sensitivityValueLabel.setFont(font1)
        self.sensitivityValueLabel.setText(u"5")

        self.horizontalLayout_gsd.addWidget(self.sensitivityValueLabel)


        self.verticalLayout.addLayout(self.horizontalLayout_gsd)

        self.horizontalLayout_gait = QHBoxLayout()
        self.horizontalLayout_gait.setObjectName(u"horizontalLayout_gait")
        self.printDiameterLabel = QLabel(SnowTrack)
        self.printDiameterLabel.setObjectName(u"printDiameterLabel")
        self.printDiameterLabel.setFont(font)

        self.horizontalLayout_gait.addWidget(self.printDiameterLabel)

        self.printDiameterSpinBox = QSpinBox(SnowTrack)
        self.printDiameterSpinBox.setObjectName(u"printDiameterSpinBox")
        self.printDiameterSpinBox.setFont(font)
        self.printDiameterSpinBox.setMinimum(5)
        self.printDiameterSpinBox.setMaximum(100)
        self.printDiameterSpinBox.setValue(30)

        self.horizontalLayout_gait.addWidget(self.printDiameterSpinBox)

        self.horizontalSpacer_print = QSpacerItem(12, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_gait.addItem(self.horizontalSpacer_print)

        self.stepLengthLabel = QLabel(SnowTrack)
        self.stepLengthLabel.setObjectName(u"stepLengthLabel")
        self.stepLengthLabel.setFont(font)

        self.horizontalLayout_gait.addWidget(self.stepLengthLabel)

        self.stepMinSpinBox = QSpinBox(SnowTrack)
        self.stepMinSpinBox.setObjectName(u"stepMinSpinBox")
        self.stepMinSpinBox.setFont(font)
        self.stepMinSpinBox.setMinimum(10)
        self.stepMinSpinBox.setMaximum(300)
        self.stepMinSpinBox.setValue(35)

        self.horizontalLayout_gait.addWidget(self.stepMinSpinBox)

        self.stepToLabel = QLabel(SnowTrack)
        self.stepToLabel.setObjectName(u"stepToLabel")
        self.stepToLabel.setFont(font)

        self.horizontalLayout_gait.addWidget(self.stepToLabel)

        self.stepMaxSpinBox = QSpinBox(SnowTrack)
        self.stepMaxSpinBox.setObjectName(u"stepMaxSpinBox")
        self.stepMaxSpinBox.setFont(font)
        self.stepMaxSpinBox.setMinimum(10)
        self.stepMaxSpinBox.setMaximum(300)
        self.stepMaxSpinBox.setValue(90)

        self.horizontalLayout_gait.addWidget(self.stepMaxSpinBox)

        self.horizontalSpacer_step = QSpacerItem(12, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_gait.addItem(self.horizontalSpacer_step)

        self.trailWidthLabel = QLabel(SnowTrack)
        self.trailWidthLabel.setObjectName(u"trailWidthLabel")
        self.trailWidthLabel.setFont(font)

        self.horizontalLayout_gait.addWidget(self.trailWidthLabel)

        self.trailWidthSpinBox = QSpinBox(SnowTrack)
        self.trailWidthSpinBox.setObjectName(u"trailWidthSpinBox")
        self.trailWidthSpinBox.setFont(font)
        self.trailWidthSpinBox.setMinimum(5)
        self.trailWidthSpinBox.setMaximum(200)
        self.trailWidthSpinBox.setValue(50)

        self.horizontalLayout_gait.addWidget(self.trailWidthSpinBox)

        self.horizontalSpacer_gait = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_gait.addItem(self.horizontalSpacer_gait)


        self.verticalLayout.addLayout(self.horizontalLayout_gait)

        self.horizontalLayout_cadence = QHBoxLayout()
        self.horizontalLayout_cadence.setObjectName(u"horizontalLayout_cadence")
        self.minPrintsLabel = QLabel(SnowTrack)
        self.minPrintsLabel.setObjectName(u"minPrintsLabel")
        self.minPrintsLabel.setFont(font)

        self.horizontalLayout_cadence.addWidget(self.minPrintsLabel)

        self.minPrintsSpinBox = QSpinBox(SnowTrack)
        self.minPrintsSpinBox.setObjectName(u"minPrintsSpinBox")
        self.minPrintsSpinBox.setFont(font)
        self.minPrintsSpinBox.setMinimum(3)
        self.minPrintsSpinBox.setMaximum(50)
        self.minPrintsSpinBox.setValue(6)

        self.horizontalLayout_cadence.addWidget(self.minPrintsSpinBox)

        self.horizontalSpacer_prints = QSpacerItem(12, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_cadence.addItem(self.horizontalSpacer_prints)

        self.stepVariationLabel = QLabel(SnowTrack)
        self.stepVariationLabel.setObjectName(u"stepVariationLabel")
        self.stepVariationLabel.setFont(font)

        self.horizontalLayout_cadence.addWidget(self.stepVariationLabel)

        self.stepVariationSpinBox = QSpinBox(SnowTrack)
        self.stepVariationSpinBox.setObjectName(u"stepVariationSpinBox")
        self.stepVariationSpinBox.setFont(font)
        self.stepVariationSpinBox.setMinimum(5)
        self.stepVariationSpinBox.setMaximum(100)
        self.stepVariationSpinBox.setValue(35)

        self.horizontalLayout_cadence.addWidget(self.stepVariationSpinBox)

        self.horizontalSpacer_cadence = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_cadence.addItem(self.horizontalSpacer_cadence)


        self.verticalLayout.addLayout(self.horizontalLayout_cadence)


        self.retranslateUi(SnowTrack)

        QMetaObject.connectSlotsByName(SnowTrack)
    # setupUi

    def retranslateUi(self, SnowTrack):
        SnowTrack.setWindowTitle(QCoreApplication.translate("SnowTrack", u"Form", None))
#if QT_CONFIG(tooltip)
        self.gsdModeLabel.setToolTip(QCoreApplication.translate("SnowTrack", u"How ADIAT converts real-world track sizes into pixels.\n"
"Every setting below is in centimeters on the ground, so the ground sample distance (GSD) of each image must be known.\n"
"\u2022 From Image Metadata: calculated per image from the drone's altitude and camera data (recommended)\n"
"\u2022 Fixed Value: the same GSD is used for every image\n"
"If an image has no usable altitude/camera metadata, the fixed value is used for it instead.\n"
"Over steep terrain the altitude above takeoff can differ from the height above the snow; use a fixed value if you know the true GSD.", None))
#endif // QT_CONFIG(tooltip)
        self.gsdModeLabel.setText(QCoreApplication.translate("SnowTrack", u"GSD Source:", None))
        self.gsdModeComboBox.setItemText(0, QCoreApplication.translate("SnowTrack", u"From Image Metadata", None))
        self.gsdModeComboBox.setItemText(1, QCoreApplication.translate("SnowTrack", u"Fixed Value", None))

#if QT_CONFIG(tooltip)
        self.gsdModeComboBox.setToolTip(QCoreApplication.translate("SnowTrack", u"Where the ground sample distance (cm per pixel) of each image comes from.\n"
"\u2022 From Image Metadata: calculated from altitude and camera data, falling back to the fixed value\n"
"\u2022 Fixed Value: always use the fixed value", None))
#endif // QT_CONFIG(tooltip)
        self.gsdValueLabel.setText(QCoreApplication.translate("SnowTrack", u"Fixed GSD (cm/px):", None))
#if QT_CONFIG(tooltip)
        self.gsdSpinBox.setToolTip(QCoreApplication.translate("SnowTrack", u"Ground sample distance in centimeters per pixel.\n"
"\u2022 Range: 0.5 to 50.0\n"
"\u2022 Default: 8.0\n"
"Used for every image in Fixed Value mode, and for images without usable metadata otherwise.\n"
"Track detection works best between about 4 and 12 cm/px; coarser imagery shrinks prints below a pixel.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.sensitivityLabel.setToolTip(QCoreApplication.translate("SnowTrack", u"How faint a print may be and still be considered.\n"
"\u2022 Range: 1 to 10\n"
"\u2022 Default: 5\n"
"\u2022 Lower values: only well-shadowed prints (sunny conditions), fastest\n"
"\u2022 Higher values: also faint prints (flat light, wind-filled tracks)\n"
"Every trail must still beat the chance of lining up random clutter, so higher values mostly cost processing time; very high values can add false trails in cluttered snow.", None))
#endif // QT_CONFIG(tooltip)
        self.sensitivityLabel.setText(QCoreApplication.translate("SnowTrack", u"Sensitivity:", None))
#if QT_CONFIG(tooltip)
        self.sensitivitySlider.setToolTip(QCoreApplication.translate("SnowTrack", u"Adjust how faint a print may be (1 = only strong prints, 10 = faint prints too).", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.sensitivityValueLabel.setToolTip(QCoreApplication.translate("SnowTrack", u"Current sensitivity (1-10).", None))
#endif // QT_CONFIG(tooltip)
        self.printDiameterLabel.setText(QCoreApplication.translate("SnowTrack", u"Print Diameter (cm):", None))
#if QT_CONFIG(tooltip)
        self.printDiameterSpinBox.setToolTip(QCoreApplication.translate("SnowTrack", u"Typical diameter of one footprint depression.\n"
"\u2022 Range: 5 to 100 cm\n"
"\u2022 Default: 30 cm (posthole in deep, soft snow)\n"
"Sets the size of dark spot the detector looks for. Boot prints in packed snow are about 20 cm;\n"
"deep postholes are 25-35 cm. Must be smaller than the minimum step length.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.stepLengthLabel.setToolTip(QCoreApplication.translate("SnowTrack", u"Distance between consecutive prints (left to right foot), center to center.\n"
"\u2022 Default: 35 to 90 cm\n"
"Walking adults take 60-80 cm steps on firm ground and 40-70 cm steps when postholing in deep snow.\n"
"Spacing outside this range (small animals, bounding animals) is ignored.", None))
#endif // QT_CONFIG(tooltip)
        self.stepLengthLabel.setText(QCoreApplication.translate("SnowTrack", u"Step Length (cm):", None))
#if QT_CONFIG(tooltip)
        self.stepMinSpinBox.setToolTip(QCoreApplication.translate("SnowTrack", u"Shortest average step length to accept (cm).", None))
#endif // QT_CONFIG(tooltip)
        self.stepToLabel.setText(QCoreApplication.translate("SnowTrack", u"to", None))
#if QT_CONFIG(tooltip)
        self.stepMaxSpinBox.setToolTip(QCoreApplication.translate("SnowTrack", u"Longest average step length to accept (cm).", None))
#endif // QT_CONFIG(tooltip)
        self.trailWidthLabel.setText(QCoreApplication.translate("SnowTrack", u"Max Trail Width (cm):", None))
#if QT_CONFIG(tooltip)
        self.trailWidthSpinBox.setToolTip(QCoreApplication.translate("SnowTrack", u"Largest sideways spread between left and right prints (center to center).\n"
"\u2022 Range: 5 to 200 cm\n"
"\u2022 Default: 50 cm\n"
"People walk with their feet 10-30 cm apart, wider when wading through deep snow.", None))
#endif // QT_CONFIG(tooltip)
        self.minPrintsLabel.setText(QCoreApplication.translate("SnowTrack", u"Min Prints:", None))
#if QT_CONFIG(tooltip)
        self.minPrintsSpinBox.setToolTip(QCoreApplication.translate("SnowTrack", u"Fewest detected prints a trail must contain to be reported.\n"
"\u2022 Range: 3 to 50\n"
"\u2022 Default: 6\n"
"Lower values find shorter trail fragments but accept more chance alignments of clutter.", None))
#endif // QT_CONFIG(tooltip)
        self.stepVariationLabel.setText(QCoreApplication.translate("SnowTrack", u"Max Step Variation (%):", None))
#if QT_CONFIG(tooltip)
        self.stepVariationSpinBox.setToolTip(QCoreApplication.translate("SnowTrack", u"How irregular the step lengths of a trail may be (coefficient of variation).\n"
"\u2022 Range: 5 to 100 %\n"
"\u2022 Default: 35 %\n"
"A walker's cadence is regular; random clutter is not. Raise this for rough terrain or tired, stumbling gait.", None))
#endif // QT_CONFIG(tooltip)
    # retranslateUi

