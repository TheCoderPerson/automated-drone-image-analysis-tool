import numpy as np
import cv2

from algorithms.Shared.views.RangeViewer_ui import Ui_ColorRangeViewer
from core.views.components.QtImageViewer import QtImageViewer

from PyQt5.QtGui import QImage
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import QDialog, QFrame


class ColorRangeRangeViewer(QDialog, Ui_ColorRangeViewer):
    """Controller for the Color Range Range Viewer Dialog"""

    def __init__(self, min_rgb, max_rgb):
        """
        __init__ constructor for the dialog

        :Tuple(int, int, int) min_rgb: The minimum color in the selected range
        :Tuple(int, int, int) max_rgb: The maximum color in the selected range
        """
        QDialog.__init__(self)
        self.setupUi(self)
        palettes = self.generatePalettes(min_rgb, max_rgb)
        self.populateImage(palettes["selected"][2], True)
        self.populateImage(palettes["selected"][1], True)
        self.populateImage(palettes["selected"][0], True)
        self.populateImage(palettes["unselected"][2], False)
        self.populateImage(palettes["unselected"][1], False)
        self.populateImage(palettes["unselected"][0], False)

    def generatePalettes(self, min_rgb, max_rgb):
        """
        generatePalettes generates numpy.ndarrays representing selected and unselected colors

        :Tuple(int, int, int) min_rgb: The minimum color in the selected range
        :Tuple(int, int, int) max_rgb: The maximum color in the selected range
        :return Dictionary: numpy.ndarrays representing the selected and unselected color ranges
        """

        cv_lower_limit = np.array([min_rgb[2], min_rgb[1], min_rgb[0]], dtype=np.uint8)
        cv_upper_limit = np.array([max_rgb[2], max_rgb[1], max_rgb[0]], dtype=np.uint8)

        # How big do we want the palettes to be
        multiplier = 2
        # 180 Hue values
        x_range = 180 * multiplier
        # 256 Light values
        y_range = 256 * multiplier

        # generate the base palettes
        high = self.generatePalette(x_range, y_range, multiplier, 255)
        med = self.generatePalette(x_range, y_range, multiplier, 128)
        low = self.generatePalette(x_range, y_range, multiplier, 64)

        # create the masks representing the selected and unselected colors
        high_mask = cv2.inRange(high, cv_lower_limit, cv_upper_limit)
        med_mask = cv2.inRange(med, cv_lower_limit, cv_upper_limit)
        low_mask = cv2.inRange(low, cv_lower_limit, cv_upper_limit)
        inverse_high_mask = cv2.bitwise_not(high_mask)
        inverse_med_mask = cv2.bitwise_not(med_mask)
        inverse_low_mask = cv2.bitwise_not(low_mask)

        # apply the masks to the base palettes
        selected_high = cv2.bitwise_and(high, high, mask=high_mask)
        unselected_high = cv2.bitwise_and(high, high, mask=inverse_high_mask)
        selected_med = cv2.bitwise_and(med, med, mask=med_mask)
        unselected_med = cv2.bitwise_and(med, med, mask=inverse_med_mask)
        selected_low = cv2.bitwise_and(low, low, mask=low_mask)
        unselected_low = cv2.bitwise_and(low, low, mask=inverse_low_mask)
        return {"selected": [selected_high, selected_med, selected_low], "unselected": [unselected_high, unselected_med, unselected_low]}

    def generatePalette(self, x_range, y_range, multiplier, saturation):
        """
        generatePalette generates numpy.ndarray representing the HSL palette at a given saturation

        :Int x_range: the height of the palette
        :Int y_range: the width of the palette
        :Int multiplier: corresponds to the size of the palette
        :Int saturation: the saturation level for the palette
        :return numpy.ndarray: numpy.ndarray representing the HSL palette
        """
        img = np.zeros((x_range, y_range, 3), np.uint8)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2HLS)
        for x in range(x_range):
            for y in range(y_range):
                height = min(max(round(x / multiplier, 0), 0), 255)
                length = min(max(round(y / multiplier, 0), 0), 255)
                img[x, y] = [height, length, saturation]
        return cv2.cvtColor(img, cv2.COLOR_HLS2BGR)

    def populateImage(self, img, selected):
        """
        populateImage generates a QtImageViewer and adds it to an existing layout

        :numpy.ndarray img: numpy.ndarray representation of the image
        :Boolean selected: determines which layout to add the widget to
        """
        image = QtImageViewer(self)
        image.setMinimumSize(QSize(190, 190))
        image.aspectRatioMode = Qt.KeepAspectRatio
        height, width, channel = img.shape
        bytesPerLine = 3 * width
        qImg = QImage(img.data, width, height, bytesPerLine, QImage.Format_RGB888).rgbSwapped()
        image.setImage(qImg)
        image.setFrameShape(QFrame.NoFrame)
        if selected:
            self.selectedLayout.addWidget(image)
        else:
            self.unselectedLayout.addWidget(image)
