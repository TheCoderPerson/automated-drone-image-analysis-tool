# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'RoundShape.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QGridLayout, QHBoxLayout, QLabel, QSizePolicy,
    QSpacerItem, QSpinBox, QVBoxLayout, QWidget)

class Ui_RoundShape(object):
    def setupUi(self, RoundShape):
        if not RoundShape.objectName():
            RoundShape.setObjectName(u"RoundShape")
        RoundShape.resize(760, 190)
        self.verticalLayout = QVBoxLayout(RoundShape)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.horizontalLayout_options = QHBoxLayout()
        self.horizontalLayout_options.setObjectName(u"horizontalLayout_options")
        self.optionsGridLayout = QGridLayout()
        self.optionsGridLayout.setObjectName(u"optionsGridLayout")
        self.optionsGridLayout.setHorizontalSpacing(6)
        self.optionsGridLayout.setVerticalSpacing(4)
        self.targetLabel = QLabel(RoundShape)
        self.targetLabel.setObjectName(u"targetLabel")
        font = QFont()
        font.setPointSize(10)
        self.targetLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.targetLabel, 0, 0, 1, 1)

        self.presetComboBox = QComboBox(RoundShape)
        self.presetComboBox.addItem("")
        self.presetComboBox.addItem("")
        self.presetComboBox.addItem("")
        self.presetComboBox.addItem("")
        self.presetComboBox.addItem("")
        self.presetComboBox.setObjectName(u"presetComboBox")
        self.presetComboBox.setFont(font)

        self.optionsGridLayout.addWidget(self.presetComboBox, 0, 1, 1, 3)

        self.gridSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.optionsGridLayout.addItem(self.gridSpacer, 0, 4, 1, 1)

        self.longDiameterLabel = QLabel(RoundShape)
        self.longDiameterLabel.setObjectName(u"longDiameterLabel")
        self.longDiameterLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.longDiameterLabel, 1, 0, 1, 1)

        self.longMinSpinBox = QDoubleSpinBox(RoundShape)
        self.longMinSpinBox.setObjectName(u"longMinSpinBox")
        self.longMinSpinBox.setFont(font)
        self.longMinSpinBox.setDecimals(1)
        self.longMinSpinBox.setMinimum(1.000000000000000)
        self.longMinSpinBox.setMaximum(2000.000000000000000)
        self.longMinSpinBox.setSingleStep(1.000000000000000)
        self.longMinSpinBox.setValue(55.000000000000000)

        self.optionsGridLayout.addWidget(self.longMinSpinBox, 1, 1, 1, 1)

        self.longToLabel = QLabel(RoundShape)
        self.longToLabel.setObjectName(u"longToLabel")
        self.longToLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.longToLabel, 1, 2, 1, 1)

        self.longMaxSpinBox = QDoubleSpinBox(RoundShape)
        self.longMaxSpinBox.setObjectName(u"longMaxSpinBox")
        self.longMaxSpinBox.setFont(font)
        self.longMaxSpinBox.setDecimals(1)
        self.longMaxSpinBox.setMinimum(1.000000000000000)
        self.longMaxSpinBox.setMaximum(2000.000000000000000)
        self.longMaxSpinBox.setSingleStep(1.000000000000000)
        self.longMaxSpinBox.setValue(95.000000000000000)

        self.optionsGridLayout.addWidget(self.longMaxSpinBox, 1, 3, 1, 1)

        self.shortDiameterLabel = QLabel(RoundShape)
        self.shortDiameterLabel.setObjectName(u"shortDiameterLabel")
        self.shortDiameterLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.shortDiameterLabel, 2, 0, 1, 1)

        self.shortMinSpinBox = QDoubleSpinBox(RoundShape)
        self.shortMinSpinBox.setObjectName(u"shortMinSpinBox")
        self.shortMinSpinBox.setFont(font)
        self.shortMinSpinBox.setDecimals(1)
        self.shortMinSpinBox.setMinimum(1.000000000000000)
        self.shortMinSpinBox.setMaximum(2000.000000000000000)
        self.shortMinSpinBox.setSingleStep(1.000000000000000)
        self.shortMinSpinBox.setValue(50.000000000000000)

        self.optionsGridLayout.addWidget(self.shortMinSpinBox, 2, 1, 1, 1)

        self.shortToLabel = QLabel(RoundShape)
        self.shortToLabel.setObjectName(u"shortToLabel")
        self.shortToLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.shortToLabel, 2, 2, 1, 1)

        self.shortMaxSpinBox = QDoubleSpinBox(RoundShape)
        self.shortMaxSpinBox.setObjectName(u"shortMaxSpinBox")
        self.shortMaxSpinBox.setFont(font)
        self.shortMaxSpinBox.setDecimals(1)
        self.shortMaxSpinBox.setMinimum(1.000000000000000)
        self.shortMaxSpinBox.setMaximum(2000.000000000000000)
        self.shortMaxSpinBox.setSingleStep(1.000000000000000)
        self.shortMaxSpinBox.setValue(95.000000000000000)

        self.optionsGridLayout.addWidget(self.shortMaxSpinBox, 2, 3, 1, 1)

        self.minConfidenceLabel = QLabel(RoundShape)
        self.minConfidenceLabel.setObjectName(u"minConfidenceLabel")
        self.minConfidenceLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.minConfidenceLabel, 0, 5, 1, 1)

        self.minConfidenceSpinBox = QDoubleSpinBox(RoundShape)
        self.minConfidenceSpinBox.setObjectName(u"minConfidenceSpinBox")
        self.minConfidenceSpinBox.setFont(font)
        self.minConfidenceSpinBox.setDecimals(0)
        self.minConfidenceSpinBox.setMinimum(0.000000000000000)
        self.minConfidenceSpinBox.setMaximum(100.000000000000000)
        self.minConfidenceSpinBox.setSingleStep(5.000000000000000)
        self.minConfidenceSpinBox.setValue(50.000000000000000)

        self.optionsGridLayout.addWidget(self.minConfidenceSpinBox, 0, 6, 1, 1)

        self.maxDetectionsLabel = QLabel(RoundShape)
        self.maxDetectionsLabel.setObjectName(u"maxDetectionsLabel")
        self.maxDetectionsLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.maxDetectionsLabel, 1, 5, 1, 1)

        self.maxDetectionsSpinBox = QSpinBox(RoundShape)
        self.maxDetectionsSpinBox.setObjectName(u"maxDetectionsSpinBox")
        self.maxDetectionsSpinBox.setFont(font)
        self.maxDetectionsSpinBox.setMinimum(1)
        self.maxDetectionsSpinBox.setMaximum(500)
        self.maxDetectionsSpinBox.setValue(25)

        self.optionsGridLayout.addWidget(self.maxDetectionsSpinBox, 1, 6, 1, 1)

        self.sizeToleranceLabel = QLabel(RoundShape)
        self.sizeToleranceLabel.setObjectName(u"sizeToleranceLabel")
        self.sizeToleranceLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.sizeToleranceLabel, 2, 5, 1, 1)

        self.sizeToleranceSpinBox = QSpinBox(RoundShape)
        self.sizeToleranceSpinBox.setObjectName(u"sizeToleranceSpinBox")
        self.sizeToleranceSpinBox.setFont(font)
        self.sizeToleranceSpinBox.setMinimum(0)
        self.sizeToleranceSpinBox.setMaximum(100)
        self.sizeToleranceSpinBox.setValue(20)

        self.optionsGridLayout.addWidget(self.sizeToleranceSpinBox, 2, 6, 1, 1)

        self.angleToleranceLabel = QLabel(RoundShape)
        self.angleToleranceLabel.setObjectName(u"angleToleranceLabel")
        self.angleToleranceLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.angleToleranceLabel, 3, 0, 1, 1)

        self.angleToleranceSpinBox = QDoubleSpinBox(RoundShape)
        self.angleToleranceSpinBox.setObjectName(u"angleToleranceSpinBox")
        self.angleToleranceSpinBox.setFont(font)
        self.angleToleranceSpinBox.setDecimals(1)
        self.angleToleranceSpinBox.setMinimum(1.000000000000000)
        self.angleToleranceSpinBox.setMaximum(30.000000000000000)
        self.angleToleranceSpinBox.setSingleStep(1.000000000000000)
        self.angleToleranceSpinBox.setValue(15.000000000000000)

        self.optionsGridLayout.addWidget(self.angleToleranceSpinBox, 3, 1, 1, 1)

        self.edgeContrastLabel = QLabel(RoundShape)
        self.edgeContrastLabel.setObjectName(u"edgeContrastLabel")
        self.edgeContrastLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.edgeContrastLabel, 3, 2, 1, 1)

        self.edgeContrastSpinBox = QDoubleSpinBox(RoundShape)
        self.edgeContrastSpinBox.setObjectName(u"edgeContrastSpinBox")
        self.edgeContrastSpinBox.setFont(font)
        self.edgeContrastSpinBox.setDecimals(1)
        self.edgeContrastSpinBox.setMinimum(1.000000000000000)
        self.edgeContrastSpinBox.setMaximum(100.000000000000000)
        self.edgeContrastSpinBox.setSingleStep(1.000000000000000)
        self.edgeContrastSpinBox.setValue(10.000000000000000)

        self.optionsGridLayout.addWidget(self.edgeContrastSpinBox, 3, 3, 1, 1)

        self.edgeSupportLabel = QLabel(RoundShape)
        self.edgeSupportLabel.setObjectName(u"edgeSupportLabel")
        self.edgeSupportLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.edgeSupportLabel, 3, 5, 1, 1)

        self.edgeSupportSpinBox = QDoubleSpinBox(RoundShape)
        self.edgeSupportSpinBox.setObjectName(u"edgeSupportSpinBox")
        self.edgeSupportSpinBox.setFont(font)
        self.edgeSupportSpinBox.setDecimals(2)
        self.edgeSupportSpinBox.setMinimum(0.050000000000000)
        self.edgeSupportSpinBox.setMaximum(1.000000000000000)
        self.edgeSupportSpinBox.setSingleStep(0.050000000000000)
        self.edgeSupportSpinBox.setValue(0.500000000000000)

        self.optionsGridLayout.addWidget(self.edgeSupportSpinBox, 3, 6, 1, 1)

        self.minArcLabel = QLabel(RoundShape)
        self.minArcLabel.setObjectName(u"minArcLabel")
        self.minArcLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.minArcLabel, 4, 0, 1, 1)

        self.minArcSpinBox = QDoubleSpinBox(RoundShape)
        self.minArcSpinBox.setObjectName(u"minArcSpinBox")
        self.minArcSpinBox.setFont(font)
        self.minArcSpinBox.setDecimals(0)
        self.minArcSpinBox.setMinimum(60.000000000000000)
        self.minArcSpinBox.setMaximum(330.000000000000000)
        self.minArcSpinBox.setSingleStep(10.000000000000000)
        self.minArcSpinBox.setValue(150.000000000000000)

        self.optionsGridLayout.addWidget(self.minArcSpinBox, 4, 1, 1, 1)

        self.minDiameterLabel = QLabel(RoundShape)
        self.minDiameterLabel.setObjectName(u"minDiameterLabel")
        self.minDiameterLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.minDiameterLabel, 4, 2, 1, 1)

        self.minDiameterSpinBox = QSpinBox(RoundShape)
        self.minDiameterSpinBox.setObjectName(u"minDiameterSpinBox")
        self.minDiameterSpinBox.setFont(font)
        self.minDiameterSpinBox.setMinimum(4)
        self.minDiameterSpinBox.setMaximum(200)
        self.minDiameterSpinBox.setValue(12)

        self.optionsGridLayout.addWidget(self.minDiameterSpinBox, 4, 3, 1, 1)

        self.fallbackGsdLabel = QLabel(RoundShape)
        self.fallbackGsdLabel.setObjectName(u"fallbackGsdLabel")
        self.fallbackGsdLabel.setFont(font)

        self.optionsGridLayout.addWidget(self.fallbackGsdLabel, 4, 5, 1, 1)

        self.fallbackGsdSpinBox = QDoubleSpinBox(RoundShape)
        self.fallbackGsdSpinBox.setObjectName(u"fallbackGsdSpinBox")
        self.fallbackGsdSpinBox.setFont(font)
        self.fallbackGsdSpinBox.setDecimals(2)
        self.fallbackGsdSpinBox.setMinimum(0.000000000000000)
        self.fallbackGsdSpinBox.setMaximum(50.000000000000000)
        self.fallbackGsdSpinBox.setSingleStep(0.100000000000000)
        self.fallbackGsdSpinBox.setValue(0.000000000000000)

        self.optionsGridLayout.addWidget(self.fallbackGsdSpinBox, 4, 6, 1, 1)

        self.detectArcsCheckBox = QCheckBox(RoundShape)
        self.detectArcsCheckBox.setObjectName(u"detectArcsCheckBox")
        self.detectArcsCheckBox.setFont(font)
        self.detectArcsCheckBox.setChecked(True)

        self.optionsGridLayout.addWidget(self.detectArcsCheckBox, 5, 0, 1, 2)

        self.debugOutputCheckBox = QCheckBox(RoundShape)
        self.debugOutputCheckBox.setObjectName(u"debugOutputCheckBox")
        self.debugOutputCheckBox.setFont(font)
        self.debugOutputCheckBox.setChecked(False)

        self.optionsGridLayout.addWidget(self.debugOutputCheckBox, 5, 2, 1, 3)


        self.horizontalLayout_options.addLayout(self.optionsGridLayout)

        self.horizontalSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_options.addItem(self.horizontalSpacer)


        self.verticalLayout.addLayout(self.horizontalLayout_options)


        self.retranslateUi(RoundShape)

        QMetaObject.connectSlotsByName(RoundShape)
    # setupUi

    def retranslateUi(self, RoundShape):
        RoundShape.setWindowTitle(QCoreApplication.translate("RoundShape", u"Form", None))
#if QT_CONFIG(tooltip)
        self.targetLabel.setToolTip(QCoreApplication.translate("RoundShape", u"The kind of object to search for. Each preset sets the expected top-down size range;\n"
"choose Custom size to enter your own. Detection is driven by size and curved edges,\n"
"not colour, so it works for black, grey or earth-toned targets.", None))
#endif // QT_CONFIG(tooltip)
        self.targetLabel.setText(QCoreApplication.translate("RoundShape", u"Target Type:", None))
        self.presetComboBox.setItemText(0, QCoreApplication.translate("RoundShape", u"Hat, helmet or bucket", None))
        self.presetComboBox.setItemText(1, QCoreApplication.translate("RoundShape", u"Life ring, tube or tire", None))
        self.presetComboBox.setItemText(2, QCoreApplication.translate("RoundShape", u"Umbrella", None))
        self.presetComboBox.setItemText(3, QCoreApplication.translate("RoundShape", u"Dome tent", None))
        self.presetComboBox.setItemText(4, QCoreApplication.translate("RoundShape", u"Custom size", None))

#if QT_CONFIG(tooltip)
        self.presetComboBox.setToolTip(QCoreApplication.translate("RoundShape", u"The kind of object to search for. Each preset sets the expected top-down size range;\n"
"choose Custom size to enter your own. Detection is driven by size and curved edges,\n"
"not colour, so it works for black, grey or earth-toned targets.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.longDiameterLabel.setToolTip(QCoreApplication.translate("RoundShape", u"Expected width of the target across its longest direction, seen from directly above.\n"
"For a round target both diameters are the same.", None))
#endif // QT_CONFIG(tooltip)
        self.longDiameterLabel.setText(QCoreApplication.translate("RoundShape", u"Long Diameter:", None))
#if QT_CONFIG(tooltip)
        self.longMinSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"Smallest expected long diameter.", None))
#endif // QT_CONFIG(tooltip)
        self.longToLabel.setText(QCoreApplication.translate("RoundShape", u"to", None))
#if QT_CONFIG(tooltip)
        self.longMaxSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"Largest expected long diameter.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.shortDiameterLabel.setToolTip(QCoreApplication.translate("RoundShape", u"Expected width of the target across its narrowest direction, seen from directly above.\n"
"For an oval this is smaller than the long diameter.", None))
#endif // QT_CONFIG(tooltip)
        self.shortDiameterLabel.setText(QCoreApplication.translate("RoundShape", u"Short Diameter:", None))
#if QT_CONFIG(tooltip)
        self.shortMinSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"Smallest expected short diameter.", None))
#endif // QT_CONFIG(tooltip)
        self.shortToLabel.setText(QCoreApplication.translate("RoundShape", u"to", None))
#if QT_CONFIG(tooltip)
        self.shortMaxSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"Largest expected short diameter.", None))
#endif // QT_CONFIG(tooltip)
        self.minConfidenceLabel.setText(QCoreApplication.translate("RoundShape", u"Min Confidence:", None))
#if QT_CONFIG(tooltip)
        self.minConfidenceSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"Only shapes scoring at least this confidence (0-100) become AOIs.\n"
"Raise if boulders or bushes produce many hits; lower to see weaker candidates.", None))
#endif // QT_CONFIG(tooltip)
        self.maxDetectionsLabel.setText(QCoreApplication.translate("RoundShape", u"Max Per Image:", None))
#if QT_CONFIG(tooltip)
        self.maxDetectionsSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"At most this many AOIs are kept per image, highest confidence first.\n"
"Protects reviewers from floods of hits in rocky or brushy terrain.", None))
#endif // QT_CONFIG(tooltip)
        self.sizeToleranceLabel.setText(QCoreApplication.translate("RoundShape", u"Size Tolerance:", None))
#if QT_CONFIG(tooltip)
        self.sizeToleranceSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"How far a shape may fall outside the size range before its score starts to drop.\n"
"Raise when altitude data is uncertain or the terrain is steep.", None))
#endif // QT_CONFIG(tooltip)
        self.sizeToleranceSpinBox.setSuffix(QCoreApplication.translate("RoundShape", u"%", None))
        self.angleToleranceLabel.setText(QCoreApplication.translate("RoundShape", u"Angle Tolerance:", None))
#if QT_CONFIG(tooltip)
        self.angleToleranceSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"How far an edge may turn away from the outline it is meant to follow and still count.\n"
"Raise for soft or lumpy targets such as tents; lower to reject more natural clutter.", None))
#endif // QT_CONFIG(tooltip)
        self.angleToleranceSpinBox.setSuffix(QCoreApplication.translate("RoundShape", u"\u00b0", None))
        self.edgeContrastLabel.setText(QCoreApplication.translate("RoundShape", u"Edge Contrast:", None))
#if QT_CONFIG(tooltip)
        self.edgeContrastSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"Minimum brightness step across an edge (0-255 scale).\n"
"Raise if grass, gravel or shadows produce many weak edges; lower for faded or dusty targets.", None))
#endif // QT_CONFIG(tooltip)
        self.edgeSupportLabel.setText(QCoreApplication.translate("RoundShape", u"Edge Support:", None))
#if QT_CONFIG(tooltip)
        self.edgeSupportSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"Fraction of a candidate's outline that must lie on a real edge for it to count as a\n"
"whole circle or oval. Lower for faint or partly shaded targets; raise if bushes produce many hits.", None))
#endif // QT_CONFIG(tooltip)
        self.minArcLabel.setText(QCoreApplication.translate("RoundShape", u"Min Arc:", None))
#if QT_CONFIG(tooltip)
        self.minArcSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"Shortest unbroken stretch of outline, in degrees of the full circle, reported as an arc\n"
"when Detect Arcs is on. Lower to catch more of a hidden target; raise if curved trails or shadows produce hits.", None))
#endif // QT_CONFIG(tooltip)
        self.minArcSpinBox.setSuffix(QCoreApplication.translate("RoundShape", u"\u00b0", None))
        self.minDiameterLabel.setText(QCoreApplication.translate("RoundShape", u"Min Diameter:", None))
#if QT_CONFIG(tooltip)
        self.minDiameterSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"Smallest target diameter, in processing pixels, worth searching for. Images where the target\n"
"would be smaller are skipped and logged - raise the processing resolution or fly lower.", None))
#endif // QT_CONFIG(tooltip)
        self.minDiameterSpinBox.setSuffix(QCoreApplication.translate("RoundShape", u" px", None))
        self.fallbackGsdLabel.setText(QCoreApplication.translate("RoundShape", u"Fallback GSD:", None))
#if QT_CONFIG(tooltip)
        self.fallbackGsdSpinBox.setToolTip(QCoreApplication.translate("RoundShape", u"Ground sample distance (cm per pixel at full resolution) to assume when an image has no usable\n"
"altitude or camera metadata. Leave at None to report such images as errors instead.", None))
#endif // QT_CONFIG(tooltip)
        self.fallbackGsdSpinBox.setSuffix(QCoreApplication.translate("RoundShape", u" cm/px", None))
        self.fallbackGsdSpinBox.setSpecialValueText(QCoreApplication.translate("RoundShape", u"None", None))
#if QT_CONFIG(tooltip)
        self.detectArcsCheckBox.setToolTip(QCoreApplication.translate("RoundShape", u"Also report outlines that are only partly visible - a tire half under brush, a tent cut by the\n"
"image edge, a coiled hose - when one unbroken arc of at least Min Arc shows.\n"
"Turn off to report only whole circles and ovals.", None))
#endif // QT_CONFIG(tooltip)
        self.detectArcsCheckBox.setText(QCoreApplication.translate("RoundShape", u"Detect Arcs", None))
#if QT_CONFIG(tooltip)
        self.debugOutputCheckBox.setToolTip(QCoreApplication.translate("RoundShape", u"Save an overlay per image (traced edges, candidates, symmetry heatmap) to a round_debug folder\n"
"in the output folder. Useful for tuning in new terrain; slows processing.", None))
#endif // QT_CONFIG(tooltip)
        self.debugOutputCheckBox.setText(QCoreApplication.translate("RoundShape", u"Write Debug Images", None))
    # retranslateUi

