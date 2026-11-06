# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'RoundShapeWizard.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QGridLayout,
    QHBoxLayout, QLabel, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget)

class Ui_RoundShapeWizard(object):
    def setupUi(self, RoundShapeWizard):
        if not RoundShapeWizard.objectName():
            RoundShapeWizard.setObjectName(u"RoundShapeWizard")
        self.verticalLayout_root = QVBoxLayout(RoundShapeWizard)
        self.verticalLayout_root.setObjectName(u"verticalLayout_root")
        self.verticalLayout_root.setContentsMargins(0, 5, 0, 0)
        self.widgetTarget = QWidget(RoundShapeWizard)
        self.widgetTarget.setObjectName(u"widgetTarget")
        self.verticalLayout_target = QVBoxLayout(self.widgetTarget)
        self.verticalLayout_target.setObjectName(u"verticalLayout_target")
        self.labelTarget = QLabel(self.widgetTarget)
        self.labelTarget.setObjectName(u"labelTarget")
        font = QFont()
        font.setPointSize(12)
        self.labelTarget.setFont(font)
        self.labelTarget.setWordWrap(True)

        self.verticalLayout_target.addWidget(self.labelTarget)

        self.horizontalLayout_preset = QHBoxLayout()
        self.horizontalLayout_preset.setObjectName(u"horizontalLayout_preset")
        self.presetComboBox = QComboBox(self.widgetTarget)
        self.presetComboBox.addItem("")
        self.presetComboBox.addItem("")
        self.presetComboBox.addItem("")
        self.presetComboBox.addItem("")
        self.presetComboBox.addItem("")
        self.presetComboBox.setObjectName(u"presetComboBox")
        font1 = QFont()
        font1.setPointSize(11)
        self.presetComboBox.setFont(font1)

        self.horizontalLayout_preset.addWidget(self.presetComboBox)

        self.horizontalSpacer_preset = QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_preset.addItem(self.horizontalSpacer_preset)


        self.verticalLayout_target.addLayout(self.horizontalLayout_preset)

        self.labelPresetNote = QLabel(self.widgetTarget)
        self.labelPresetNote.setObjectName(u"labelPresetNote")
        font2 = QFont()
        font2.setPointSize(11)
        font2.setItalic(True)
        self.labelPresetNote.setFont(font2)
        self.labelPresetNote.setWordWrap(True)

        self.verticalLayout_target.addWidget(self.labelPresetNote)

        self.customSizeWidget = QWidget(self.widgetTarget)
        self.customSizeWidget.setObjectName(u"customSizeWidget")
        self.customSizeGridLayout = QGridLayout(self.customSizeWidget)
        self.customSizeGridLayout.setObjectName(u"customSizeGridLayout")
        self.longDiameterLabel = QLabel(self.customSizeWidget)
        self.longDiameterLabel.setObjectName(u"longDiameterLabel")
        self.longDiameterLabel.setFont(font1)

        self.customSizeGridLayout.addWidget(self.longDiameterLabel, 0, 0, 1, 1)

        self.longMinSpinBox = QDoubleSpinBox(self.customSizeWidget)
        self.longMinSpinBox.setObjectName(u"longMinSpinBox")
        self.longMinSpinBox.setFont(font1)
        self.longMinSpinBox.setDecimals(1)
        self.longMinSpinBox.setMinimum(1.000000000000000)
        self.longMinSpinBox.setMaximum(2000.000000000000000)
        self.longMinSpinBox.setSingleStep(1.000000000000000)
        self.longMinSpinBox.setValue(55.000000000000000)

        self.customSizeGridLayout.addWidget(self.longMinSpinBox, 0, 1, 1, 1)

        self.longToLabel = QLabel(self.customSizeWidget)
        self.longToLabel.setObjectName(u"longToLabel")
        self.longToLabel.setFont(font1)

        self.customSizeGridLayout.addWidget(self.longToLabel, 0, 2, 1, 1)

        self.longMaxSpinBox = QDoubleSpinBox(self.customSizeWidget)
        self.longMaxSpinBox.setObjectName(u"longMaxSpinBox")
        self.longMaxSpinBox.setFont(font1)
        self.longMaxSpinBox.setDecimals(1)
        self.longMaxSpinBox.setMinimum(1.000000000000000)
        self.longMaxSpinBox.setMaximum(2000.000000000000000)
        self.longMaxSpinBox.setSingleStep(1.000000000000000)
        self.longMaxSpinBox.setValue(95.000000000000000)

        self.customSizeGridLayout.addWidget(self.longMaxSpinBox, 0, 3, 1, 1)

        self.shortDiameterLabel = QLabel(self.customSizeWidget)
        self.shortDiameterLabel.setObjectName(u"shortDiameterLabel")
        self.shortDiameterLabel.setFont(font1)

        self.customSizeGridLayout.addWidget(self.shortDiameterLabel, 1, 0, 1, 1)

        self.shortMinSpinBox = QDoubleSpinBox(self.customSizeWidget)
        self.shortMinSpinBox.setObjectName(u"shortMinSpinBox")
        self.shortMinSpinBox.setFont(font1)
        self.shortMinSpinBox.setDecimals(1)
        self.shortMinSpinBox.setMinimum(1.000000000000000)
        self.shortMinSpinBox.setMaximum(2000.000000000000000)
        self.shortMinSpinBox.setSingleStep(1.000000000000000)
        self.shortMinSpinBox.setValue(50.000000000000000)

        self.customSizeGridLayout.addWidget(self.shortMinSpinBox, 1, 1, 1, 1)

        self.shortToLabel = QLabel(self.customSizeWidget)
        self.shortToLabel.setObjectName(u"shortToLabel")
        self.shortToLabel.setFont(font1)

        self.customSizeGridLayout.addWidget(self.shortToLabel, 1, 2, 1, 1)

        self.shortMaxSpinBox = QDoubleSpinBox(self.customSizeWidget)
        self.shortMaxSpinBox.setObjectName(u"shortMaxSpinBox")
        self.shortMaxSpinBox.setFont(font1)
        self.shortMaxSpinBox.setDecimals(1)
        self.shortMaxSpinBox.setMinimum(1.000000000000000)
        self.shortMaxSpinBox.setMaximum(2000.000000000000000)
        self.shortMaxSpinBox.setSingleStep(1.000000000000000)
        self.shortMaxSpinBox.setValue(95.000000000000000)

        self.customSizeGridLayout.addWidget(self.shortMaxSpinBox, 1, 3, 1, 1)

        self.customSizeSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.customSizeGridLayout.addItem(self.customSizeSpacer, 0, 4, 1, 1)


        self.verticalLayout_target.addWidget(self.customSizeWidget)


        self.verticalLayout_root.addWidget(self.widgetTarget)

        self.widgetSensitivity = QWidget(RoundShapeWizard)
        self.widgetSensitivity.setObjectName(u"widgetSensitivity")
        self.verticalLayout_sensitivity = QVBoxLayout(self.widgetSensitivity)
        self.verticalLayout_sensitivity.setSpacing(3)
        self.verticalLayout_sensitivity.setObjectName(u"verticalLayout_sensitivity")
        self.labelSensitivity = QLabel(self.widgetSensitivity)
        self.labelSensitivity.setObjectName(u"labelSensitivity")
        self.labelSensitivity.setFont(font)

        self.verticalLayout_sensitivity.addWidget(self.labelSensitivity)

        self.labelSensitivityNote = QLabel(self.widgetSensitivity)
        self.labelSensitivityNote.setObjectName(u"labelSensitivityNote")
        self.labelSensitivityNote.setFont(font2)
        self.labelSensitivityNote.setWordWrap(True)

        self.verticalLayout_sensitivity.addWidget(self.labelSensitivityNote)

        self.sensitivitySliderPlaceholder = QWidget(self.widgetSensitivity)
        self.sensitivitySliderPlaceholder.setObjectName(u"sensitivitySliderPlaceholder")
        self.sensitivitySliderPlaceholder.setMinimumSize(QSize(600, 60))

        self.verticalLayout_sensitivity.addWidget(self.sensitivitySliderPlaceholder)


        self.verticalLayout_root.addWidget(self.widgetSensitivity)

        self.verticalSpacer_bottom = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_root.addItem(self.verticalSpacer_bottom)


        self.retranslateUi(RoundShapeWizard)

        QMetaObject.connectSlotsByName(RoundShapeWizard)
    # setupUi

    def retranslateUi(self, RoundShapeWizard):
        self.labelTarget.setText(QCoreApplication.translate("RoundShapeWizard", u"What kind of object are you looking for?", None))
        self.presetComboBox.setItemText(0, QCoreApplication.translate("RoundShapeWizard", u"Hat, helmet or bucket", None))
        self.presetComboBox.setItemText(1, QCoreApplication.translate("RoundShapeWizard", u"Life ring, tube or tire", None))
        self.presetComboBox.setItemText(2, QCoreApplication.translate("RoundShapeWizard", u"Umbrella", None))
        self.presetComboBox.setItemText(3, QCoreApplication.translate("RoundShapeWizard", u"Dome tent", None))
        self.presetComboBox.setItemText(4, QCoreApplication.translate("RoundShapeWizard", u"Custom size", None))

#if QT_CONFIG(tooltip)
        self.presetComboBox.setToolTip(QCoreApplication.translate("RoundShapeWizard", u"The kind of object to search for. Each preset sets the expected top-down size range;\n"
"choose Custom size to enter your own. Detection is driven by size and curved edges,\n"
"not colour, so it works for black, grey or earth-toned targets.", None))
#endif // QT_CONFIG(tooltip)
        self.labelPresetNote.setText(QCoreApplication.translate("RoundShapeWizard", u"Detection uses the object's size and curved outline, not its colour, and also finds outlines that are partly hidden. Sizes are as seen from directly above.", None))
#if QT_CONFIG(tooltip)
        self.longDiameterLabel.setToolTip(QCoreApplication.translate("RoundShapeWizard", u"Expected width of the target across its longest direction, seen from directly above.\n"
"For a round target both diameters are the same.", None))
#endif // QT_CONFIG(tooltip)
        self.longDiameterLabel.setText(QCoreApplication.translate("RoundShapeWizard", u"Long Diameter:", None))
#if QT_CONFIG(tooltip)
        self.longMinSpinBox.setToolTip(QCoreApplication.translate("RoundShapeWizard", u"Smallest expected long diameter.", None))
#endif // QT_CONFIG(tooltip)
        self.longToLabel.setText(QCoreApplication.translate("RoundShapeWizard", u"to", None))
#if QT_CONFIG(tooltip)
        self.longMaxSpinBox.setToolTip(QCoreApplication.translate("RoundShapeWizard", u"Largest expected long diameter.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.shortDiameterLabel.setToolTip(QCoreApplication.translate("RoundShapeWizard", u"Expected width of the target across its narrowest direction, seen from directly above.\n"
"For an oval this is smaller than the long diameter.", None))
#endif // QT_CONFIG(tooltip)
        self.shortDiameterLabel.setText(QCoreApplication.translate("RoundShapeWizard", u"Short Diameter:", None))
#if QT_CONFIG(tooltip)
        self.shortMinSpinBox.setToolTip(QCoreApplication.translate("RoundShapeWizard", u"Smallest expected short diameter.", None))
#endif // QT_CONFIG(tooltip)
        self.shortToLabel.setText(QCoreApplication.translate("RoundShapeWizard", u"to", None))
#if QT_CONFIG(tooltip)
        self.shortMaxSpinBox.setToolTip(QCoreApplication.translate("RoundShapeWizard", u"Largest expected short diameter.", None))
#endif // QT_CONFIG(tooltip)
        self.labelSensitivity.setText(QCoreApplication.translate("RoundShapeWizard", u"How many candidates should ADIAT show?", None))
        self.labelSensitivityNote.setText(QCoreApplication.translate("RoundShapeWizard", u"Note: A higher setting shows weaker candidates too, which finds more targets but also more boulders, bushes and debris.", None))
        pass
    # retranslateUi

