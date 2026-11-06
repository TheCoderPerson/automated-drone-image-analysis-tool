# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'GroundMessageWizard.ui'
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
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QRadioButton,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)

class Ui_GroundMessageWizard(object):
    def setupUi(self, GroundMessageWizard):
        if not GroundMessageWizard.objectName():
            GroundMessageWizard.setObjectName(u"GroundMessageWizard")
        self.verticalLayout_root = QVBoxLayout(GroundMessageWizard)
        self.verticalLayout_root.setObjectName(u"verticalLayout_root")
        self.verticalLayout_root.setContentsMargins(0, 5, 0, 0)
        self.widgetMaterial = QWidget(GroundMessageWizard)
        self.widgetMaterial.setObjectName(u"widgetMaterial")
        self.verticalLayout_material = QVBoxLayout(self.widgetMaterial)
        self.verticalLayout_material.setObjectName(u"verticalLayout_material")
        self.labelMaterial = QLabel(self.widgetMaterial)
        self.labelMaterial.setObjectName(u"labelMaterial")
        font = QFont()
        font.setPointSize(12)
        self.labelMaterial.setFont(font)
        self.labelMaterial.setWordWrap(True)

        self.verticalLayout_material.addWidget(self.labelMaterial)

        self.radioMaterialDark = QRadioButton(self.widgetMaterial)
        self.radioMaterialDark.setObjectName(u"radioMaterialDark")
        font1 = QFont()
        font1.setPointSize(11)
        self.radioMaterialDark.setFont(font1)

        self.verticalLayout_material.addWidget(self.radioMaterialDark)

        self.radioMaterialLight = QRadioButton(self.widgetMaterial)
        self.radioMaterialLight.setObjectName(u"radioMaterialLight")
        self.radioMaterialLight.setFont(font1)

        self.verticalLayout_material.addWidget(self.radioMaterialLight)

        self.radioMaterialEither = QRadioButton(self.widgetMaterial)
        self.radioMaterialEither.setObjectName(u"radioMaterialEither")
        self.radioMaterialEither.setFont(font1)
        self.radioMaterialEither.setChecked(True)

        self.verticalLayout_material.addWidget(self.radioMaterialEither)


        self.verticalLayout_root.addWidget(self.widgetMaterial)

        self.widgetSingle = QWidget(GroundMessageWizard)
        self.widgetSingle.setObjectName(u"widgetSingle")
        self.verticalLayout_single = QVBoxLayout(self.widgetSingle)
        self.verticalLayout_single.setObjectName(u"verticalLayout_single")
        self.labelSingle = QLabel(self.widgetSingle)
        self.labelSingle.setObjectName(u"labelSingle")
        self.labelSingle.setFont(font)
        self.labelSingle.setWordWrap(True)

        self.verticalLayout_single.addWidget(self.labelSingle)

        self.horizontalLayout_single = QHBoxLayout()
        self.horizontalLayout_single.setSpacing(20)
        self.horizontalLayout_single.setObjectName(u"horizontalLayout_single")
        self.radioSingleNo = QRadioButton(self.widgetSingle)
        self.radioSingleNo.setObjectName(u"radioSingleNo")
        self.radioSingleNo.setFont(font1)

        self.horizontalLayout_single.addWidget(self.radioSingleNo)

        self.radioSingleYes = QRadioButton(self.widgetSingle)
        self.radioSingleYes.setObjectName(u"radioSingleYes")
        self.radioSingleYes.setFont(font1)
        self.radioSingleYes.setChecked(True)

        self.horizontalLayout_single.addWidget(self.radioSingleYes)

        self.horizontalSpacer_single = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_single.addItem(self.horizontalSpacer_single)


        self.verticalLayout_single.addLayout(self.horizontalLayout_single)


        self.verticalLayout_root.addWidget(self.widgetSingle)

        self.widgetAggressiveness = QWidget(GroundMessageWizard)
        self.widgetAggressiveness.setObjectName(u"widgetAggressiveness")
        self.verticalLayout_aggr = QVBoxLayout(self.widgetAggressiveness)
        self.verticalLayout_aggr.setSpacing(3)
        self.verticalLayout_aggr.setObjectName(u"verticalLayout_aggr")
        self.labelAggressiveness = QLabel(self.widgetAggressiveness)
        self.labelAggressiveness.setObjectName(u"labelAggressiveness")
        self.labelAggressiveness.setFont(font)
        self.labelAggressiveness.setWordWrap(True)

        self.verticalLayout_aggr.addWidget(self.labelAggressiveness)

        self.labelNote = QLabel(self.widgetAggressiveness)
        self.labelNote.setObjectName(u"labelNote")
        font2 = QFont()
        font2.setPointSize(11)
        font2.setItalic(True)
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


        self.retranslateUi(GroundMessageWizard)

        QMetaObject.connectSlotsByName(GroundMessageWizard)
    # setupUi

    def retranslateUi(self, GroundMessageWizard):
        self.labelMaterial.setText(QCoreApplication.translate("GroundMessageWizard", u"What is the message most likely made of?", None))
        self.radioMaterialDark.setText(QCoreApplication.translate("GroundMessageWizard", u"Dark material on lighter ground (branches or logs on snow, sand or dry grass)", None))
        self.radioMaterialLight.setText(QCoreApplication.translate("GroundMessageWizard", u"Light material on darker ground (pale rocks or bright clothing on soil or vegetation)", None))
        self.radioMaterialEither.setText(QCoreApplication.translate("GroundMessageWizard", u"Not sure / could be either", None))
        self.labelSingle.setText(QCoreApplication.translate("GroundMessageWizard", u"Could the message be a single symbol, such as an X or V?", None))
        self.radioSingleNo.setText(QCoreApplication.translate("GroundMessageWizard", u"No", None))
        self.radioSingleYes.setText(QCoreApplication.translate("GroundMessageWizard", u"Yes", None))
        self.labelAggressiveness.setText(QCoreApplication.translate("GroundMessageWizard", u"How aggressively should ADIAT search for messages?", None))
        self.labelNote.setText(QCoreApplication.translate("GroundMessageWizard", u"Note: A higher setting will find more potential messages but may also report crossed branches and other clutter.", None))
        pass
    # retranslateUi

