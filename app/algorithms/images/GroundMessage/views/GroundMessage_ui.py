# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'GroundMessage.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout,
    QLabel, QSizePolicy, QSlider, QSpacerItem,
    QSpinBox, QVBoxLayout, QWidget)

class Ui_GroundMessage(object):
    def setupUi(self, GroundMessage):
        if not GroundMessage.objectName():
            GroundMessage.setObjectName(u"GroundMessage")
        GroundMessage.resize(674, 140)
        self.verticalLayout = QVBoxLayout(GroundMessage)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.confidenceLayout = QHBoxLayout()
        self.confidenceLayout.setObjectName(u"confidenceLayout")
        self.confidenceLabel = QLabel(GroundMessage)
        self.confidenceLabel.setObjectName(u"confidenceLabel")
        font = QFont()
        font.setPointSize(10)
        self.confidenceLabel.setFont(font)

        self.confidenceLayout.addWidget(self.confidenceLabel)

        self.confidenceSlider = QSlider(GroundMessage)
        self.confidenceSlider.setObjectName(u"confidenceSlider")
        self.confidenceSlider.setMinimum(0)
        self.confidenceSlider.setMaximum(100)
        self.confidenceSlider.setPageStep(5)
        self.confidenceSlider.setValue(50)
        self.confidenceSlider.setOrientation(Qt.Horizontal)
        self.confidenceSlider.setTickPosition(QSlider.TicksBelow)
        self.confidenceSlider.setTickInterval(10)

        self.confidenceLayout.addWidget(self.confidenceSlider)

        self.confidenceValueLabel = QLabel(GroundMessage)
        self.confidenceValueLabel.setObjectName(u"confidenceValueLabel")
        self.confidenceValueLabel.setMinimumSize(QSize(30, 0))
        font1 = QFont()
        font1.setPointSize(10)
        font1.setBold(True)
        self.confidenceValueLabel.setFont(font1)
        self.confidenceValueLabel.setText(u"50")

        self.confidenceLayout.addWidget(self.confidenceValueLabel)


        self.verticalLayout.addLayout(self.confidenceLayout)

        self.charSizeLayout = QHBoxLayout()
        self.charSizeLayout.setObjectName(u"charSizeLayout")
        self.charSizeLabel = QLabel(GroundMessage)
        self.charSizeLabel.setObjectName(u"charSizeLabel")
        self.charSizeLabel.setFont(font)

        self.charSizeLayout.addWidget(self.charSizeLabel)

        self.minCharSizeLabel = QLabel(GroundMessage)
        self.minCharSizeLabel.setObjectName(u"minCharSizeLabel")
        self.minCharSizeLabel.setFont(font)

        self.charSizeLayout.addWidget(self.minCharSizeLabel)

        self.minCharSizeSpinBox = QSpinBox(GroundMessage)
        self.minCharSizeSpinBox.setObjectName(u"minCharSizeSpinBox")
        self.minCharSizeSpinBox.setMinimum(10)
        self.minCharSizeSpinBox.setMaximum(5000)
        self.minCharSizeSpinBox.setSingleStep(10)
        self.minCharSizeSpinBox.setValue(40)

        self.charSizeLayout.addWidget(self.minCharSizeSpinBox)

        self.maxCharSizeLabel = QLabel(GroundMessage)
        self.maxCharSizeLabel.setObjectName(u"maxCharSizeLabel")
        self.maxCharSizeLabel.setFont(font)

        self.charSizeLayout.addWidget(self.maxCharSizeLabel)

        self.maxCharSizeSpinBox = QSpinBox(GroundMessage)
        self.maxCharSizeSpinBox.setObjectName(u"maxCharSizeSpinBox")
        self.maxCharSizeSpinBox.setMinimum(20)
        self.maxCharSizeSpinBox.setMaximum(10000)
        self.maxCharSizeSpinBox.setSingleStep(50)
        self.maxCharSizeSpinBox.setValue(600)

        self.charSizeLayout.addWidget(self.maxCharSizeSpinBox)

        self.charSizeSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.charSizeLayout.addItem(self.charSizeSpacer)


        self.verticalLayout.addLayout(self.charSizeLayout)

        self.polarityLayout = QHBoxLayout()
        self.polarityLayout.setObjectName(u"polarityLayout")
        self.polarityLabel = QLabel(GroundMessage)
        self.polarityLabel.setObjectName(u"polarityLabel")
        self.polarityLabel.setFont(font)

        self.polarityLayout.addWidget(self.polarityLabel)

        self.polarityComboBox = QComboBox(GroundMessage)
        self.polarityComboBox.addItem("")
        self.polarityComboBox.addItem("")
        self.polarityComboBox.addItem("")
        self.polarityComboBox.setObjectName(u"polarityComboBox")

        self.polarityLayout.addWidget(self.polarityComboBox)

        self.polaritySpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.polarityLayout.addItem(self.polaritySpacer)


        self.verticalLayout.addLayout(self.polarityLayout)

        self.singleCharactersCheckBox = QCheckBox(GroundMessage)
        self.singleCharactersCheckBox.setObjectName(u"singleCharactersCheckBox")
        self.singleCharactersCheckBox.setFont(font)
        self.singleCharactersCheckBox.setChecked(True)

        self.verticalLayout.addWidget(self.singleCharactersCheckBox)


        self.retranslateUi(GroundMessage)

        QMetaObject.connectSlotsByName(GroundMessage)
    # setupUi

    def retranslateUi(self, GroundMessage):
        GroundMessage.setWindowTitle(QCoreApplication.translate("GroundMessage", u"Form", None))
#if QT_CONFIG(tooltip)
        self.confidenceLabel.setToolTip(QCoreApplication.translate("GroundMessage", u"Minimum confidence for a message to be reported.\n"
"Confidence combines how character-like each shape is with how consistently the characters line up as a message.", None))
#endif // QT_CONFIG(tooltip)
        self.confidenceLabel.setText(QCoreApplication.translate("GroundMessage", u"Confidence Threshold", None))
#if QT_CONFIG(tooltip)
        self.confidenceSlider.setToolTip(QCoreApplication.translate("GroundMessage", u"Minimum confidence (0-100%) for a message to be reported.\n"
"\u2022 Default: 50%\n"
"\u2022 Lower values (30-45%): Report weaker candidates (more detections, more false positives)\n"
"\u2022 Medium values (45-60%): Balanced (recommended for most searches)\n"
"\u2022 Higher values (60-80%): Only report rows of clearly formed characters (fewer false positives)\n"
"Single characters (e.g. an X) score lower than multi-character messages, so very high thresholds report words only.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.confidenceValueLabel.setToolTip(QCoreApplication.translate("GroundMessage", u"Current confidence threshold percentage.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.charSizeLabel.setToolTip(QCoreApplication.translate("GroundMessage", u"Expected size of one character in the image, in pixels (its longest side).\n"
"Character size in pixels = character size on the ground / ground sample distance (GSD).\n"
"Example: a 2 m (6.5 ft) letter photographed at 2 cm/pixel is about 100 pixels tall.", None))
#endif // QT_CONFIG(tooltip)
        self.charSizeLabel.setText(QCoreApplication.translate("GroundMessage", u"Character Size (px)", None))
        self.minCharSizeLabel.setText(QCoreApplication.translate("GroundMessage", u"Min", None))
#if QT_CONFIG(tooltip)
        self.minCharSizeSpinBox.setToolTip(QCoreApplication.translate("GroundMessage", u"Smallest character to look for, in pixels of the original image.\n"
"\u2022 Default: 40\n"
"Characters smaller than about 40 pixels rarely have enough detail to be recognised as characters.", None))
#endif // QT_CONFIG(tooltip)
        self.maxCharSizeLabel.setText(QCoreApplication.translate("GroundMessage", u"Max", None))
#if QT_CONFIG(tooltip)
        self.maxCharSizeSpinBox.setToolTip(QCoreApplication.translate("GroundMessage", u"Largest character to look for, in pixels of the original image.\n"
"\u2022 Default: 600\n"
"A wider range takes longer to process and can increase false positives.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.polarityLabel.setToolTip(QCoreApplication.translate("GroundMessage", u"Whether the material the characters are made of is darker or lighter than the ground around it.", None))
#endif // QT_CONFIG(tooltip)
        self.polarityLabel.setText(QCoreApplication.translate("GroundMessage", u"Character Material", None))
        self.polarityComboBox.setItemText(0, QCoreApplication.translate("GroundMessage", u"Darker or lighter than the ground", None))
        self.polarityComboBox.setItemText(1, QCoreApplication.translate("GroundMessage", u"Darker than the ground", None))
        self.polarityComboBox.setItemText(2, QCoreApplication.translate("GroundMessage", u"Lighter than the ground", None))

#if QT_CONFIG(tooltip)
        self.polarityComboBox.setToolTip(QCoreApplication.translate("GroundMessage", u"Whether the characters are darker or lighter than the ground around them.\n"
"\u2022 Darker or lighter: Search for both (default; slower)\n"
"\u2022 Darker than the ground: e.g. branches or logs on snow, sand or dry grass\n"
"\u2022 Lighter than the ground: e.g. pale rocks or bright clothing on soil or vegetation", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.singleCharactersCheckBox.setToolTip(QCoreApplication.translate("GroundMessage", u"Also report a single, isolated character such as an X or V (international ground-to-air signals).\n"
"A lone character is harder to tell apart from crossed branches than a whole word, so this can add false positives.", None))
#endif // QT_CONFIG(tooltip)
        self.singleCharactersCheckBox.setText(QCoreApplication.translate("GroundMessage", u"Report single characters (e.g. X or V)", None))
    # retranslateUi

