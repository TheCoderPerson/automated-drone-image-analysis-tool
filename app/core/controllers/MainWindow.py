from core.views.components.GroupedComboBox import GroupedComboBox
import pathlib
import os
import platform
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtCore import QThread, pyqtSlot, QSize, Qt
from PyQt5.QtWidgets import QApplication, QMainWindow, QColorDialog, QFileDialog, QMessageBox, QSizePolicy

from core.views.MainWindow_ui import Ui_MainWindow

from helpers.ColorUtils import ColorUtils

from core.controllers.Viewer import Viewer
from core.controllers.Perferences import Preferences
from core.controllers.VideoParser import VideoParser

from core.services.LoggerService import LoggerService
from core.services.AnalyzeService import AnalyzeService
from core.services.SettingsService import SettingsService
from core.services.XmlService import XmlService
from core.services.ConfigService import ConfigService

"""****Import Algorithm Controllers****"""
from algorithms.ColorRange.controllers.ColorRangeController import ColorRangeController
from algorithms.RXAnomaly.controllers.RXAnomalyController import RXAnomalyController
from algorithms.MatchedFilter.controllers.MatchedFilterController import MatchedFilterController
from algorithms.ThermalRange.controllers.ThermalRangeController import ThermalRangeController
from algorithms.ThermalAnomaly.controllers.ThermalAnomalyController import ThermalAnomalyController
"""****End Algorithm Import****"""


class MainWindow(QMainWindow, Ui_MainWindow):
    """Controller for the Main Window (QMainWindow)."""

    def __init__(self, theme, version):
        """
        __init__ constructor to build the ADIAT Main Window

        :qdarktheme theme: instance of qdarktheme that allows us to toggle light/dark mode
        :String version: the app version # to be included in the Main Window title bar
        """
        self.logger = LoggerService()
        QMainWindow.__init__(self)
        self.theme = theme
        self.setupUi(self)
        self.__threads = []
        self.images = None
        self.algorithmWidget = None
        self.identifierColor = (0, 255, 0)
        self.HistogramImgWidget.setVisible(False)
        self.KMeansWidget.setVisible(False)
        self.setWindowTitle("Automated Drone Image Analysis Tool  v" + version + " - Sponsored by TEXSAR")
        self.loadAlgorithms()
        # Adding slots for GUI elements
        self.identifierColorButton.clicked.connect(self.identifierButtonClicked)
        self.inputFolderButton.clicked.connect(self.inputFolderButtonClicked)
        self.outputFolderButton.clicked.connect(self.outputFolderButtonClicked)
        self.startButton.clicked.connect(self.startButtonClicked)
        self.cancelButton.clicked.connect(self.cancelButtonClicked)
        self.viewResultsButton.clicked.connect(self.viewResultsButtonClicked)
        self.actionLoadFile.triggered.connect(self.openLoadFile)
        self.actionPreferences.triggered.connect(self.openPreferences)
        self.actionVideoParser.triggered.connect(self.openVideoParser)
        self.algorithmComboBox.currentTextChanged.connect(self.algorithmComboBoxChanged)
        self.algorithmComboBoxChanged()
        self.histogramCheckbox.stateChanged.connect(self.histogramCheckboxChange)
        self.histogramButton.clicked.connect(self.histogramButtonClicked)
        self.kMeansCheckbox.stateChanged.connect(self.kMeansCheckboxChange)
        self.results_path = ''

        self.settings_service = SettingsService()
        self.setDefaults()

    def loadAlgorithms(self):
        """
        setupAlgorithmComboBox adds combobox entries for algorithm selector
        """
        system = platform.system()
        configService = ConfigService(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'algorithms.conf'))
        self.algorithms = configService.getAlgorithms()
        algorithm_list = dict()
        for algorithm in self.algorithms:
            if system in algorithm['platforms']:
                if algorithm['type'] not in algorithm_list:
                    algorithm_list[algorithm['type']] = []
                algorithm_list[algorithm['type']].append(algorithm['label'])
        self.replaceAlgorithmComboBox()
        for key, list in algorithm_list.items():
            self.algorithmComboBox.addGroup(key, list)
        self.algorithmComboBox.setCurrentIndex(1)

    def replaceAlgorithmComboBox(self):
        """
        replaceAlgorithmComboBox replaces the standard QtComboBox with a version that allows grouping.
        """
        self.tempAlgorithmComboBox.deleteLater()
        self.algorithmComboBox = GroupedComboBox(self.setupFrame)
        sizePolicy = QSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.algorithmComboBox.sizePolicy().hasHeightForWidth())
        self.algorithmComboBox.setSizePolicy(sizePolicy)
        self.algorithmComboBox.setMinimumSize(QSize(300, 0))
        font = QFont()
        font.setPointSize(10)
        self.algorithmComboBox.setFont(font)
        self.algorithmSelectorlLayout.replaceWidget(self.tempAlgorithmComboBox, self.algorithmComboBox)

    def identifierButtonClicked(self):
        """
        identifierButtonClicked click handler for the object identifier color button
        Opens a color selector dialog
        """
        color = QColorDialog().getColor()
        if color.isValid():
            self.identifierColor = (color.red(), color.green(), color.blue())
            self.identifierColorButton.setStyleSheet("background-color: " + color.name() + ";")

    def inputFolderButtonClicked(self):
        """
        inputFolderButtonClicked click handler for the input folder button
        Opens a file/directory dialog
        """
        if self.inputFolderLine.text() != "":
            dir = self.inputFolderLine.text()
        else:
            dir = self.settings_service.getSetting('InputFolder')
        if not isinstance(dir, str):
            dir = ""
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", dir, QFileDialog.ShowDirsOnly)
        # if a directory is selected, populate the input folder textbox with the path and update the persistent settings with the latest path.
        if directory != "":
            self.inputFolderLine.setText(directory)
            path = pathlib.Path(directory)
            self.settings_service.setSetting('InputFolder', path.parent.__str__())

    def outputFolderButtonClicked(self):
        """
        outputFolderButtonClicked click handler for the output folder button
        Opens a file/directory dialog
        """
        if self.outputFolderLine.text() != "":
            dir = self.outputFolderLine.text()
        else:
            dir = self.settings_service.getSetting('OutputFolder')
        if not isinstance(dir, str):
            dir = ""
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", dir, QFileDialog.ShowDirsOnly)

        # if a directory is selected, populate the input folder textbox with the path and update the persistent settings with the latest path.
        if directory != "":
            self.outputFolderLine.setText(directory)
            path = pathlib.Path(directory)
            self.settings_service.setSetting('OutputFolder', path.parent.__str__())

    def histogramButtonClicked(self):
        """
        histogramButtonClicked click handler for the histogram reference image loaded
        Opens a file dialog
        """
        # default the directory to the input folder directory if populated.
        if self.inputFolderLine.text() != "":
            dir = self.inputFolderLine.text()
        else:
            dir = self.settings_service.getSetting('InputFolder')

        filename, ok = QFileDialog.getOpenFileName(self, "Select a Reference Image", dir, "Images (*.png *.jpg)")
        if filename:
            self.histogramLine.setText(filename)

    def algorithmComboBoxChanged(self):
        """
        algorithmComboBoxChanged action method for updates to the algorithm combobox
        On change loads the QWidget associated with the selected algorithm and sets the max processes spinbox to the default value for the new algorithm
        """
        if self.algorithmWidget is not None:
            self.verticalLayout_2.removeWidget(self.algorithmWidget)
            self.algorithmWidget.deleteLater()
        self.activeAlgorithm = [x for x in self.algorithms if x['label'] == self.algorithmComboBox.currentText()][0]

        cls = globals()[self.activeAlgorithm['controller']]
        self.algorithmWidget = cls()
        self.verticalLayout_2.addWidget(self.algorithmWidget)
        if self.algorithmWidget.is_thermal:
            self.AdvancedFeaturesWidget.hide()
        else:
            self.AdvancedFeaturesWidget.show()

    def histogramCheckboxChange(self):
        """
        histogramCheckboxChange action method triggered on changes to the histogram checkbox
        When checked the reference image selector is displayed
        """
        if self.histogramCheckbox.isChecked():
            self.HistogramImgWidget.setVisible(True)
        else:
            self.HistogramImgWidget.setVisible(False)

    def kMeansCheckboxChange(self):
        """
        kMeansCheckboxChange action method triggered on changes to the kMeans Clustering checkbox
        When checked the number of clusters spinbox is displayed
        """
        if self.kMeansCheckbox.isChecked():
            self.KMeansWidget.setVisible(True)
        else:
            self.KMeansWidget.setVisible(False)

    def startButtonClicked(self):
        """
        startButtonClicked click handler for triggering the image analysis process
        """
        try:
            # ensure the algorithm-specific requirements are met.
            alg_validation = self.algorithmWidget.validate()

            if alg_validation is not None:
                self.showError(alg_validation)
                return

            # verify that the directories have been set.
            if self.inputFolderLine.text() == "" or self.outputFolderLine.text() == "":
                self.showError("Please set the input and output directories.")
                return

            self.setStartButton(False)
            self.setViewResultsButton(False)

            self.addLogEntry("--- Starting image processing ---")

            # get the algorithm-specific optins
            options = self.algorithmWidget.getOptions()

            hist_ref_path = None
            if self.histogramCheckbox.isChecked() and self.histogramLine.text() != "":
                hist_ref_path = self.histogramLine.text()

            kmeans_clusters = None
            if self.kMeansCheckbox.isChecked():
                kmeans_clusters = self.clustersSpinBox.value()

            # update the persistent settings for minimum object size and identifier color based on the current settings.
            self.settings_service.setSetting('MinObjectArea', self.minAreaSpinBox.value())
            self.settings_service.setSetting('IdentifierColor', self.identifierColor)
            self.settings_service.setSetting('MaxProcesses', self.maxProcessesSpinBox.value())

            max_aois = self.settings_service.getSetting('MaxAOIs')
            aoi_radius = self.settings_service.getSetting('AOIRadius')

            # Create instance of the analysis class with the selected algorithm
            self.analyzeService = AnalyzeService(1, self.activeAlgorithm, self.inputFolderLine.text(), self.outputFolderLine.text(), self.identifierColor,
                                                 self.minAreaSpinBox.value(), self.maxProcessesSpinBox.value(), max_aois, aoi_radius, hist_ref_path,
                                                 kmeans_clusters, self.algorithmWidget.is_thermal, options)

            # This must be done in a separate thread so that it won't block the GUI updates to the log
            thread = QThread()
            self.__threads.append((thread, self.analyzeService))
            self.analyzeService.moveToThread(thread)

            # Connecting the slots messages back from the analysis thread
            self.analyzeService.sig_msg.connect(self.onWorkerMsg)
            self.analyzeService.sig_aois.connect(self.showAOIsLimitWarning)
            self.analyzeService.sig_done.connect(self.onWorkerDone)

            thread.started.connect(self.analyzeService.processFiles)
            thread.start()

            self.results_path = self.outputFolderLine.text()

            self.setCancelButton(True)
        except Exception as e:
            self.logger.error(e)

    def cancelButtonClicked(self):
        """
        cancelButtonClicked click handler that cancelled in progress analysis
        """
        self.analyzeService.processCancel()
        self.setCancelButton(False)

    def viewResultsButtonClicked(self):
        """
        viewResultsButtonClicked click handler for launching the image viewer once analysis has been completed
        """
        QApplication.setOverrideCursor(Qt.WaitCursor)
        output_folder = self.results_path + "/ADIAT_Results/"
        file = pathlib.Path(output_folder + "ADIAT_Data.xml")
        if file.is_file():
            position_format = self.settings_service.getSetting('PositionFormat')
            temperature_unit = self.settings_service.getSetting('TemperatureUnit')
            self.viewer = Viewer(file, position_format, temperature_unit, False)
            self.viewer.show()
        else:
            self.showError("Could not parse XML file.  Check file paths in \"ADIAT_Data.xml\"")
        QApplication.restoreOverrideCursor()

    def addLogEntry(self, text):
        """
        addLogEntry adds a new line of text to the output window

        :String text: the text to add to the output window
        """
        self.outputWindow.appendPlainText(text)

    @pyqtSlot()
    def showAOIsLimitWarning(self):
        """
        showAOIsLimitWarning opens a message box showing a warning that the maximum number of areas of interest has been exceed
        Gives the user the options to continue or cancel the current analysis
        """
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setText("Area of Interest Limit (" + str(self.settings_service.getSetting('MaxAOIs')) +
                    ") exceeded.  Would you like to proceed with the current execution?")
        msg.setWindowTitle("Area of Interest Limit Exceeded")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        result = msg.exec_()
        if result == QMessageBox.No:
            self.cancelButtonClicked()

    @pyqtSlot(str)
    def onWorkerMsg(self, text):
        """
        onWorkerMsg calls the addLogEntry method to add a new line to the output window

        :String text: the text to add to the output window
        """
        self.addLogEntry(text)

    @pyqtSlot(int, int)
    def onWorkerDone(self, id, images_with_aois):
        """
        onWorkerDone  Oncompletion of the analysis process adds a log entry with information specific to the results and updates button states

        :Int id: the id of the calling object
        :Int images_with_aois: the number of images that include areas of interest
        """
        self.addLogEntry("--- Image Processing Completed ---")
        if images_with_aois > 0:
            self.addLogEntry(str(images_with_aois) + " images with areas of interest identified")
            self.setViewResultsButton(True)
        else:
            self.addLogEntry("No areas of interest identified")
            self.setViewResultsButton(False)

        self.setStartButton(True)
        self.setCancelButton(False)

        for thread, analyze in self.__threads:
            thread.quit()

    def showError(self, text):
        """
        showError open a message box showing an error with the provided text

        :String text: the text to be included are the error message
        """
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText(text)
        msg.setWindowTitle("Error Starting Processing")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    def openLoadFile(self):
        """
        openLoadFile action for the open file menu item
        """
        try:
            file = QFileDialog.getOpenFileName(self, "Select File")
            if file[0] != "":
                self.processXmlFile(file[0])
        except Exception as e:
            self.logger.error(e)

    def processXmlFile(self, full_path):
        """
        processXmlFile takes a file from the Load File dialog and processes it.

        :String full_path: the path to the XML file
        """
        try:
            image_count = self.getSettingsFromXml(full_path)
            if image_count > 0:
                self.setViewResultsButton(True)
            if self.algorithmWidget.is_thermal:
                self.AdvancedFeaturesWidget.hide()
            else:
                self.AdvancedFeaturesWidget.show()
        except Exception as e:
            self.logger.error(e)

    def getSettingsFromXml(self, full_path):
        """
        getSettingsFromXml populates the UI with previously executed analysis

        :String full_path: the path to the XML file
        :return int: the number of images with areas of interest
        """
        xmlLoader = XmlService(full_path)
        settings, image_count = xmlLoader.getSettings()
        if 'output_dir' in settings:
            self.outputFolderLine.setText(settings['output_dir'])
            self.results_path = settings['output_dir']
        if 'input_dir' in settings:
            self.inputFolderLine.setText(settings['input_dir'])
        if 'identifier_color' in settings:
            self.identifierColor = settings['identifier_color']
            color = QColor(self.identifierColor[0], self.identifierColor[1], self.identifierColor[2])
            self.identifierColorButton.setStyleSheet("background-color: " + color.name() + ";")
        if 'num_processes' in settings:
            self.maxProcessesSpinBox.setValue(settings['num_processes'])
        if 'min_area' in settings:
            self.minAreaSpinBox.setValue(int(settings['min_area']))
        if 'hist_ref_path' in settings:
            self.histogramCheckbox.setChecked(True)
            self.histogramLine.setText(settings['hist_ref_path'])
        if 'kmeans_clusters' in settings:
            self.kMeansCheckbox.setChecked(True)
            self.clustersSpinBox.setValue(settings['kmeans_clusters'])
        if 'algorithm' in settings:
            self.activeAlgorithm = [x for x in self.algorithms if x['name'] == settings['algorithm']][0]
            self.algorithmComboBox.setCurrentText(self.activeAlgorithm['label'])
            self.algorithmWidget.loadOptions(settings['options'])
        if ('thermal') in settings:
            self.algorithmWidget.is_thermal = (settings['thermal'] == 'True')
        else:
            self.algorithmWidget.is_thermal = False
        return image_count

    def openPreferences(self):
        """
        openPreferences action for the preferences menu item
        Opens a dialog showing the application preferences
        """
        pref = Preferences(self)
        pref.exec()

    def openVideoParser(self):
        """
        openVideoParser action for the Video Parser menu item
        Opens a dialog showing the video parser
        """
        parser = VideoParser()
        parser.exec_()

    def closeEvent(self, event):
        """
        closeEvent closes all windows when the main window is closes.
        """
        for window in QApplication.topLevelWidgets():
            window.close()

    def setStartButton(self, enabled):
        """
        setStartButton updates the start button based on the enabled parameter

        :Boolean enabled: True to enable and False to disable the button
        """
        if enabled:
            self.startButton.setStyleSheet("background-color: rgb(0, 136, 0);\n""color: rgb(228, 231, 235);")
            self.startButton.setEnabled(True)
        else:
            self.startButton.setStyleSheet("")
            self.startButton.setEnabled(False)

    def setCancelButton(self, enabled):
        """
        setCancelButton updates the cancel button based on the enabled parameter

        :Boolean enabled: True to enable and False to disable the button
        """
        if enabled:
            self.cancelButton.setStyleSheet("background-color: rgb(136, 0, 0);\n""color: rgb(228, 231, 235);")
            self.cancelButton.setEnabled(True)
        else:
            self.cancelButton.setStyleSheet("")
            self.cancelButton.setEnabled(False)

    def setViewResultsButton(self, enabled):
        """
        setViewResultsButton updates the view results button based on the enabled parameter

        :Boolean enabled: True to enable and False to disable the button
        """
        if enabled:
            self.viewResultsButton.setStyleSheet("background-color: rgb(0, 0, 136);\n""color: rgb(228, 231, 235);")
            self.viewResultsButton.setEnabled(True)
        else:
            self.viewResultsButton.setStyleSheet("")
            self.viewResultsButton.setEnabled(False)

    def setDefaults(self):
        """
        setDefaults sets UI element default values based on persistent settings and sets default values for persistent settings if not previously set
        """
        min_area = self.settings_service.getSetting('MinObjectArea')
        if isinstance(min_area, int):
            self.minAreaSpinBox.setProperty("value", min_area)

        max_processes = self.settings_service.getSetting('MaxProcesses')
        if isinstance(max_processes, int):
            self.maxProcessesSpinBox.setProperty("value", max_processes)

        id_color = self.settings_service.getSetting('IdentifierColor')
        if isinstance(id_color, tuple):
            self.identifierColor = id_color
            color = QColor(self.identifierColor[0], self.identifierColor[1], self.identifierColor[2])
            self.identifierColorButton.setStyleSheet("background-color: " + color.name() + ";")

        max_aois = self.settings_service.getSetting('MaxAOIs')
        if not isinstance(max_aois, int):
            self.settings_service.setSetting('MaxAOIs', 100)

        aoi_radius = self.settings_service.getSetting('AOIRadius')
        if not isinstance(aoi_radius, int):
            self.settings_service.setSetting('AOIRadius', 15)

        position_format = self.settings_service.getSetting('PositionFormat')
        if not isinstance(position_format, str):
            self.settings_service.setSetting('PositionFormat', 'Lat/Long - Decimal Degrees')

        temperature_unit = self.settings_service.getSetting('TemperatureUnit')
        if not isinstance(temperature_unit, str):
            self.settings_service.setSetting('TemperatureUnit', 'Fahrenheit')

        theme = self.settings_service.getSetting('Theme')
        if theme is None:
            self.settings_service.setSetting('Theme', 'Dark')
            theme = 'Dark'
        self.updateTheme(theme)

    def updateTheme(self, theme):
        """
        updateTheme updates the application theme based on the theme parameter

        :String theme: Light or Dark
        """
        if theme == 'Light':
            self.theme.setup_theme("light")
        else:
            self.theme.setup_theme("dark")
