# Technical Design Document
## Automated Drone Image Analysis Tool (ADIAT)

**Version:** 2.0.0
**Developer:** TEXSAR (Texas Search and Rescue)
**License:** AGPL-3.0

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Project Structure](#3-project-structure)
4. [Technology Stack](#4-technology-stack)
5. [Core Components](#5-core-components)
6. [Detection Algorithms](#6-detection-algorithms)
7. [Data Models](#7-data-models)
8. [Services Layer](#8-services-layer)
9. [User Interface](#9-user-interface)
10. [Configuration](#10-configuration)
11. [Build & Deployment](#11-build--deployment)
12. [Testing](#12-testing)
13. [Contributing Guidelines](#13-contributing-guidelines)

---

## 1. Overview

### 1.1 Purpose

The Automated Drone Image Analysis Tool (ADIAT) is a desktop application designed to analyze drone imagery for Search and Rescue (SAR) operations. It automatically identifies Areas of Interest (AOIs) in images using various computer vision algorithms, helping SAR teams quickly locate potential targets in large datasets of aerial imagery.

### 1.2 Key Features

- **Batch Image Analysis**: Process hundreds of drone images in parallel
- **Multiple Detection Algorithms**: 8 pluggable algorithms for RGB and thermal imagery
- **Real-Time Stream Analysis**: Process RTMP/HLS video streams for live detection
- **GPS Integration**: Extract and display geospatial metadata from drone imagery
- **Interactive Viewer**: Review, annotate, and flag detected areas of interest
- **Export Capabilities**: Generate PDF reports, KML files, and CalTopo integrations
- **Thermal Image Support**: Analyze thermal imagery from DJI, Autel, and FLIR drones

### 1.3 Target Users

- Search and Rescue teams
- Emergency response organizations
- Drone operators conducting aerial surveys
- Remote sensing analysts

---

## 2. Architecture

### 2.1 High-Level Architecture

ADIAT follows a **Model-View-Controller (MVC)** architecture with a service-oriented design pattern.

```
┌─────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ MainWindow │ Viewer │ Dialogs │ RTMP Viewers        │  │
│  └──────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                    CONTROLLER LAYER                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ MainWindow │ Viewer │ AOI │ GPS │ Export Controllers │  │
│  └──────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                     SERVICE LAYER                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ AnalyzeService │ ImageService │ XmlService          │  │
│  │ ThermalParser │ Export Services │ Settings          │  │
│  └──────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                    ALGORITHM LAYER                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ ColorRange │ HSV │ RXAnomaly │ MatchedFilter │ AI    │  │
│  │ MRMap │ ThermalRange │ ThermalAnomaly                │  │
│  └──────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                      DATA LAYER                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ XML Files │ TIFF Masks │ Pickle Caches │ Settings    │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Design Patterns

| Pattern | Implementation | Purpose |
|---------|----------------|---------|
| **MVC** | Controllers, Services, Views | Separation of concerns |
| **Plugin Architecture** | Algorithm modules | Extensible detection methods |
| **Service Layer** | Core services | Centralized business logic |
| **Signal-Slot** | Qt signals | Thread-safe communication |
| **Factory** | ThermalParserService | Drone-specific parser selection |

### 2.3 Threading Model

- **Main Thread**: UI rendering and user interaction
- **Worker Threads**: Image analysis via `QThread`
- **Multiprocessing Pool**: Parallel image processing
- **Background Threads**: RTMP streaming, video recording

---

## 3. Project Structure

```
automated-drone-image-analysis-tool/
├── app/                              # Main application package
│   ├── __main__.py                   # Entry point
│   ├── __init__.py                   # Package definition (version)
│   ├── algorithms.conf               # Algorithm registry (JSON)
│   ├── drones.pkl                    # Drone sensor database
│   ├── xmp.pkl                       # XMP field mappings
│   ├── ADIAT.ico                     # Application icon
│   │
│   ├── core/                         # Core application logic
│   │   ├── controllers/              # UI controllers
│   │   │   ├── MainWindow.py         # Main window controller
│   │   │   ├── Perferences.py        # Settings dialog
│   │   │   ├── VideoParser.py        # Video frame extraction
│   │   │   ├── RTMP*Viewer.py        # Real-time stream viewers
│   │   │   └── viewer/               # Viewer sub-controllers
│   │   │       ├── Viewer.py         # Main viewer (1400+ lines)
│   │   │       ├── aoi/              # AOI management
│   │   │       ├── gps/              # GPS/map functionality
│   │   │       ├── thumbnails/       # Thumbnail loading
│   │   │       ├── exports/          # Export controllers
│   │   │       ├── components/       # Dialog controllers
│   │   │       ├── coordinates/      # Coordinate handling
│   │   │       └── status/           # Status bar management
│   │   │
│   │   ├── services/                 # Business logic services
│   │   │   ├── AnalyzeService.py     # Batch processing orchestrator
│   │   │   ├── ImageService.py       # Image metadata extraction
│   │   │   ├── XmlService.py         # XML data persistence
│   │   │   ├── SettingsService.py    # User preferences
│   │   │   ├── ConfigService.py      # Algorithm configuration
│   │   │   ├── LoggerService.py      # Centralized logging
│   │   │   ├── GSDService.py         # Ground Sample Distance
│   │   │   ├── AlertService.py       # Real-time alerts
│   │   │   ├── ThermalParserService.py
│   │   │   ├── PdfGeneratorService.py
│   │   │   ├── KMLGeneratorService.py
│   │   │   ├── CalTopoService.py
│   │   │   ├── ZipBundleService.py
│   │   │   ├── RTMPStreamService.py
│   │   │   ├── VideoRecordingService.py
│   │   │   ├── HistogramNormalizationService.py
│   │   │   ├── KMeansClustersService.py
│   │   │   ├── CustomColorsService.py
│   │   │   ├── RealtimeColorDetectionService.py
│   │   │   ├── RealtimeMotionDetectionService.py
│   │   │   ├── RealtimeAnomalyDetectionService.py
│   │   │   └── thermalParserServices/
│   │   │       ├── DjiThermalParserService.py
│   │   │       ├── FlirThermalParserService.py
│   │   │       └── AutelThermalParserService.py
│   │   │
│   │   └── views/                    # Auto-generated UI files
│   │       ├── *_ui.py               # Compiled from .ui files
│   │       ├── resources_rc.py       # Compiled resources
│   │       └── components/           # Custom widgets
│   │           ├── QtImageViewer.py  # Image display widget
│   │           ├── GroupedComboBox.py
│   │           └── Toggle.py
│   │
│   ├── algorithms/                   # Detection algorithm modules
│   │   ├── AlgorithmController.py    # Base controller class
│   │   ├── AlgorithmService.py       # Base service class
│   │   ├── ColorRange/               # RGB color detection
│   │   ├── HSVColorRange/            # HSV color detection
│   │   ├── MatchedFilter/            # Template matching
│   │   ├── RXAnomaly/                # Spectral anomaly detection
│   │   ├── MRMap/                    # Multi-spectral detection
│   │   ├── ThermalRange/             # Temperature range detection
│   │   ├── ThermalAnomaly/           # Temperature anomaly detection
│   │   ├── AIPersonDetector/         # ONNX-based person detection
│   │   └── Shared/                   # Shared algorithm resources
│   │
│   ├── helpers/                      # Utility functions
│   │   ├── ColorUtils.py             # Color conversion utilities
│   │   ├── CudaCheck.py              # GPU availability check
│   │   ├── LocationInfo.py           # GPS coordinate utilities
│   │   ├── MetaDataHelper.py         # EXIF/XMP extraction
│   │   ├── PickleHelper.py           # Pickle file utilities
│   │   └── SlidingWindowSlicer.py    # Image segmentation
│   │
│   ├── external/                     # External tools
│   │   ├── exiftool.exe              # ExifTool binary (Windows)
│   │   ├── dji_thermal_sdk_v1.7/     # DJI thermal SDK
│   │   └── autel/                    # Autel drone libraries
│   │
│   └── tests/                        # Test suite
│       ├── conftest.py               # Pytest fixtures
│       ├── algorithms/               # Algorithm tests
│       ├── core/services/            # Service tests
│       └── helpers/                  # Helper tests
│
├── resources/                        # UI resources
│   ├── views/                        # Qt Designer .ui files
│   │   ├── MainWindow.ui
│   │   ├── Viewer.ui
│   │   ├── algorithms/               # Algorithm UIs
│   │   └── components/               # Component UIs
│   ├── icons/                        # Theme icons
│   │   ├── dark_theme/               # Dark theme icons
│   │   └── light_theme/              # Light theme icons
│   ├── fonts/                        # Application fonts
│   ├── resources.qrc                 # Resource manifest
│   └── style.qss                     # Qt stylesheet
│
├── setup.py                          # Build configuration
├── requirements.txt                  # Production dependencies
├── requirements-dev.txt              # Development dependencies
├── app.spec                          # PyInstaller config
├── app_debug.spec                    # Debug build config
├── pyuic.json                        # UI compilation config
├── pytest.ini                        # Test configuration
├── .flake8                           # Linting rules
├── README.md                         # Project readme
└── LICENSE                           # AGPL-3.0 license
```

---

## 4. Technology Stack

### 4.1 Core Technologies

| Category | Technology | Purpose |
|----------|------------|---------|
| **Language** | Python 3.x | Primary development language |
| **UI Framework** | PySide6 (Qt6) | Cross-platform GUI |
| **Image Processing** | OpenCV | Computer vision operations |
| **Numerical Computing** | NumPy | Array operations |
| **Scientific Computing** | SciPy | Statistical analysis |
| **Machine Learning** | ONNX Runtime | AI model inference |
| **Data Analysis** | Pandas | Tabular data handling |

### 4.2 Dependencies

**Core Dependencies** (`requirements.txt`):

```
PySide6                 # Qt6 Python bindings
opencv-python           # Computer vision
numpy                   # Numerical computing
scipy==1.15.3           # Scientific algorithms
pillow                  # Image manipulation
spectral                # Spectral analysis
scikit-image            # Image processing
qimage2ndarray          # Qt/NumPy integration
PyExifTool              # EXIF metadata
piexif                  # EXIF parsing
tifffile                # TIFF file support
pandas                  # Data tables
pyarrow==20.0.0         # Arrow data format
simplekml               # KML generation
reportlab               # PDF generation
pyqtdarktheme==2.1.0    # Dark theme
utm                     # UTM coordinates
onnxruntime-gpu==1.20.1 # AI inference
```

**Development Dependencies** (`requirements-dev.txt`):

```
qt6-tools               # Qt development tools
PyInstaller             # Executable building
pytest-qt               # Qt testing
flake8                  # Code linting
```

### 4.3 External Tools

| Tool | Purpose | Platform |
|------|---------|----------|
| ExifTool | EXIF/XMP metadata extraction | Windows |
| DJI Thermal SDK v1.7 | DJI thermal image parsing | Windows |
| Autel Libraries | Autel thermal support | Windows |

---

## 5. Core Components

### 5.1 MainWindow

**File**: `/app/core/controllers/MainWindow.py`

The main application window that orchestrates image analysis.

**Responsibilities**:
- Algorithm selection and configuration
- Input/output folder management
- Analysis parameter configuration
- Progress monitoring
- Results viewing

**Key Methods**:
```python
class MainWindow(QMainWindow):
    def _startButton_clicked(self)      # Start analysis
    def _cancelButton_clicked(self)     # Cancel processing
    def _on_worker_msg(self, msg)       # Handle progress updates
    def _on_worker_done(self, id, count, path)  # Handle completion
    def load_xml_file(self, path)       # Load previous results
```

### 5.2 Viewer

**File**: `/app/core/controllers/viewer/Viewer.py`

Interactive image viewer for reviewing analysis results.

**Responsibilities**:
- Image display with zoom/pan
- AOI visualization and management
- Metadata display
- Export functionality
- User annotations

**Sub-Controllers**:

| Controller | Purpose |
|------------|---------|
| `AOIController` | AOI selection, filtering, sorting |
| `ThumbnailController` | Thumbnail loading and display |
| `GPSMapController` | GPS map visualization |
| `CoordinateController` | Coordinate formatting |
| `StatusController` | Status bar updates |
| `ExportController` | PDF/KML/Zip exports |

**Keyboard Shortcuts**:

| Key | Action |
|-----|--------|
| `→` / `←` | Next/previous image |
| `↓` / `P` | Hide current image |
| `↑` / `U` | Unhide current image |
| `H` | Toggle pixel highlighting |
| `C` | Toggle AOI circles / Create mode |
| `F` | Flag/unflag selected AOI |
| `M` | Show GPS map |
| `E` | Upscale current view |
| `Ctrl+H` | Image adjustments |
| `Ctrl+M` | Measure tool |

### 5.3 QtImageViewer

**File**: `/app/core/views/components/QtImageViewer.py`

Custom QGraphicsView for image display with advanced interaction.

**Features**:
- Smooth zoom (1% to 100x)
- Pan support (right-click drag)
- Region zoom (left-click drag)
- Zoom stack history
- Signal emission for mouse events

**Key Signals**:
```python
leftMouseButtonPressed(x, y, pixmap)
leftMouseButtonReleased(x, y)
rightMouseButtonPressed(x, y)
rightMouseButtonReleased(x, y)
zoomChanged(factor)
viewChanged()
mousePositionOnImageChanged(point)
```

---

## 6. Detection Algorithms

### 6.1 Algorithm Architecture

Each algorithm follows a consistent structure:

```
AlgorithmName/
├── __init__.py
├── controllers/
│   ├── AlgorithmNameController.py    # UI configuration
│   └── AlgorithmNameRangeViewerController.py  # Optional viewer
├── services/
│   └── AlgorithmNameService.py       # Processing logic
└── views/
    └── AlgorithmName_ui.py           # Auto-generated UI
```

### 6.2 Base Classes

**AlgorithmController** (`/app/algorithms/AlgorithmController.py`):
```python
class AlgorithmController(ABC):
    @abstractmethod
    def validate(self) -> bool

    @abstractmethod
    def get_options(self) -> dict

    @abstractmethod
    def load_options(self, options: dict) -> None
```

**AlgorithmService** (`/app/algorithms/AlgorithmService.py`):
```python
class AlgorithmService:
    def process_image(self, img, full_path, input_dir, output_dir) -> AnalysisResult
    def identify_areas_of_interest(self, img, contours) -> list[dict]
    def store_mask(self, input_file, output_file, mask, temperature_data) -> None
    def split_image(self, img, segments, overlap) -> list
    def glue_image(self, pieces) -> np.ndarray
```

### 6.3 Available Algorithms

#### RGB Algorithms

| Algorithm | Description | Key Parameters |
|-----------|-------------|----------------|
| **Color Range (RGB)** | Detects pixels within RGB value ranges | RGB min/max values |
| **Color Range (HSV)** | Detects colors in HSV color space | Hue, Saturation, Value ranges |
| **Matched Filter** | Template matching for patterns | Filter kernel, threshold |
| **RX Anomaly** | Spectral anomaly detection using Mahalanobis distance | Sensitivity (1-9), segments |
| **MRMap** | Multi-spectral detection variant | Configuration-dependent |
| **AI Person Detector** | ONNX-based person detection | Confidence threshold, CPU/GPU |

#### Thermal Algorithms

| Algorithm | Description | Key Parameters |
|-----------|-------------|----------------|
| **Temperature Range** | Detects pixels within temperature range | Min/max temperature (°C) |
| **Temperature Anomaly** | Statistical anomaly in thermal data | Sensitivity threshold |

### 6.4 Algorithm Configuration

**File**: `/app/algorithms.conf`

```json
{
  "algorithms": [
    {
      "name": "ColorRange",
      "label": "Color Range (RGB)",
      "controller": "ColorRangeController",
      "service": "ColorRangeService",
      "combine_overlapping_aois": true,
      "platforms": ["Windows", "Darwin"],
      "type": "RGB"
    },
    {
      "name": "HSVColorRange",
      "label": "Color Range (HSV)",
      "controller": "HSVColorRangeController",
      "service": "HSVColorRangeService",
      "combine_overlapping_aois": true,
      "platforms": ["Windows", "Darwin"],
      "type": "RGB"
    },
    {
      "name": "RXAnomaly",
      "label": "RX Anomaly",
      "controller": "RXAnomalyController",
      "service": "RXAnomalyService",
      "combine_overlapping_aois": true,
      "platforms": ["Windows", "Darwin"],
      "type": "RGB"
    },
    {
      "name": "ThermalRange",
      "label": "Temperature Range",
      "controller": "ThermalRangeController",
      "service": "ThermalRangeService",
      "combine_overlapping_aois": true,
      "platforms": ["Windows"],
      "type": "Thermal"
    }
  ]
}
```

### 6.5 Processing Pipeline

```
1. INPUT IMAGE
   └─► cv2.imread()

2. PREPROCESSING (optional)
   ├─► Histogram normalization
   └─► K-means clustering

3. ALGORITHM PROCESSING
   ├─► Color space conversion (BGR→HSV/LAB)
   ├─► Detection algorithm execution
   └─► Binary mask generation

4. CONTOUR DETECTION
   ├─► cv2.findContours()
   └─► Area filtering (min_area, max_area)

5. AOI EXTRACTION
   ├─► Minimum enclosing circle calculation
   ├─► Radius padding addition
   ├─► Pixel coordinate extraction
   └─► Optional AOI combination

6. OUTPUT
   ├─► Multi-band GeoTIFF mask
   └─► XML metadata entry
```

---

## 7. Data Models

### 7.1 Area of Interest (AOI)

```python
area_of_interest = {
    'center': (int, int),           # (x, y) pixel coordinates
    'radius': int,                  # Radius in pixels
    'area': int,                    # Total pixel area
    'contour': list[list[int]],     # Contour points: [[x1, y1], ...]
    'detected_pixels': list[list[int]],  # Detected pixels
    'flagged': bool,                # User flag status
    'user_comment': str             # User annotation
}
```

### 7.2 Analysis Result

```python
class AnalysisResult:
    input_path: str                 # Original image path
    output_path: str                # Relative mask path
    output_dir: str                 # Output directory
    areas_of_interest: list[dict]   # List of AOIs
    base_contour_count: int         # Count before combining
    error_message: str              # Error if failed
```

### 7.3 Image Metadata

```python
image = {
    'xml': ET.Element,              # XML element reference
    'path': str,                    # Original image path
    'mask_path': str,               # Mask TIFF path
    'hidden': bool,                 # Hidden status
    'areas_of_interest': list[dict] # AOIs for this image
}
```

### 7.4 XML Schema

**File**: `ADIAT_Data.xml`

```xml
<?xml version="1.0" encoding="utf-8"?>
<data>
    <settings
        output_dir="/path/to/output"
        input_dir="/path/to/input"
        num_processes="4"
        identifier_color="(0, 255, 0)"
        aoi_radius="10"
        min_area="100"
        max_area="500000"
        hist_ref_path=""
        kmeans_clusters="0"
        algorithm="ColorRange"
        thermal="False"
    >
        <options>
            <option name="param_name" value="param_value"/>
        </options>
    </settings>

    <images>
        <image
            path="relative/path/image.jpg"
            mask_path="mask_filename.tif"
            hidden="False"
        >
            <area_of_interest
                area="1250"
                center="(500, 600)"
                radius="45"
                contour="[[480, 580], [520, 580], ...]"
                detected_pixels="[[481, 581], ...]"
                flagged="False"
                user_comment="Note"
            />
        </image>
    </images>
</data>
```

### 7.5 Mask File Format (GeoTIFF)

Multi-band TIFF structure:
- **Band 0**: Detection mask (uint8, 0 or 255)
- **Band 1+**: Temperature data (float32) for thermal images

```python
# Storage
stacked = np.stack([mask, temperature_data], axis=0)
tifffile.imwrite(
    path,
    stacked,
    photometric='minisblack',
    metadata={'axes': 'CYX'},
    compression='deflate'
)
```

### 7.6 GPS Data Structures

```python
# Decimal Degrees
coords = {
    'latitude': 40.123456,
    'longitude': -75.987654
}

# Degrees, Minutes, Seconds
dms = {
    'latitude': {'degrees': 40, 'minutes': 7, 'seconds': 24.44, 'ref': 'N'},
    'longitude': {'degrees': 75, 'minutes': 59, 'seconds': 15.95, 'ref': 'W'}
}

# UTM
utm_coords = {
    'easting': 500000,
    'northing': 4447000,
    'zone_number': 18,
    'zone_letter': 'S'
}
```

---

## 8. Services Layer

### 8.1 Core Services

#### AnalyzeService

**File**: `/app/core/services/AnalyzeService.py`

Orchestrates batch image analysis with multiprocessing.

```python
class AnalyzeService(QObject):
    sig_msg = Signal(str)           # Progress messages
    sig_aois = Signal()              # AOI count warning
    sig_done = Signal(int, int, str) # Completion signal

    def process_files(self)          # Main processing method
    @staticmethod
    def process_file(...)            # Per-image processing (multiprocess)
```

#### ImageService

**File**: `/app/core/services/ImageService.py`

Extracts metadata and processes images for display.

```python
class ImageService:
    def get_relative_altitude(self) -> float
    def get_asl_altitude(self) -> float
    def get_gps_coordinates(self) -> tuple[float, float]
    def get_gsd(self) -> float
    def get_drone_orientation(self) -> float
    def get_thermal_data(self) -> np.ndarray
    def circle_areas_of_interest(self, img, aois, color) -> np.ndarray
    def highlight_aoi_pixels(self, img, aoi, color) -> np.ndarray
```

#### XmlService

**File**: `/app/core/services/XmlService.py`

Manages XML-based data persistence.

```python
class XmlService:
    def get_settings(self) -> tuple[dict, int]
    def get_images(self) -> list[dict]
    def add_settings_to_xml(self, **kwargs) -> None
    def add_image_to_xml(self, img: dict) -> None
    def update_aoi(self, image_idx, aoi_idx, **kwargs) -> None
    def save_xml_file(self, path: str) -> None
```

### 8.2 Export Services

| Service | Output Format | Purpose |
|---------|---------------|---------|
| `PdfGeneratorService` | PDF | Multi-page reports with images |
| `KMLGeneratorService` | KML | Google Earth placemarks |
| `CalTopoService` | CalTopo API | Map marker uploads |
| `ZipBundleService` | ZIP | Archive of results |

### 8.3 Real-Time Services

| Service | Purpose | Performance |
|---------|---------|-------------|
| `RTMPStreamService` | RTMP/HLS stream handling | Configurable FPS |
| `RealtimeColorDetectionService` | Live HSV detection | <100ms/frame |
| `RealtimeMotionDetectionService` | Motion tracking | <150ms/frame |
| `RealtimeAnomalyDetectionService` | Statistical anomaly | <50ms/frame |
| `VideoRecordingService` | MP4 recording | H.264 encoding |

### 8.4 Thermal Services

| Service | Drone Support |
|---------|---------------|
| `ThermalParserService` | Factory for parser selection |
| `DjiThermalParserService` | DJI thermal drones |
| `FlirThermalParserService` | FLIR cameras |
| `AutelThermalParserService` | Autel thermal drones |

### 8.5 Utility Services

| Service | Purpose |
|---------|---------|
| `SettingsService` | User preferences (QSettings) |
| `ConfigService` | Algorithm configuration |
| `LoggerService` | Centralized logging |
| `GSDService` | Ground Sample Distance calculation |
| `HistogramNormalizationService` | Image normalization |
| `KMeansClustersService` | Color clustering |

---

## 9. User Interface

### 9.1 Main Window

**Features**:
- Algorithm selection dropdown (grouped by type)
- Input/output folder selection
- Parameter configuration widgets
- Progress log output
- Control buttons (Start, Cancel, View Results)

### 9.2 Viewer Window

**Layout**:
```
┌─────────────────────────────────────────────────┐
│ Toolbar                                          │
├───────────────────────────────┬─────────────────┤
│                               │ Thumbnails      │
│                               ├─────────────────┤
│     Image Display             │ AOI List        │
│     (QtImageViewer)           │                 │
│                               │                 │
│                               ├─────────────────┤
│                               │ AOI Details     │
├───────────────────────────────┴─────────────────┤
│ Status Bar (GPS, Altitude, GSD, Temperature)    │
└─────────────────────────────────────────────────┘
```

**Viewer Features**:
- Zoom/pan with mouse and keyboard
- AOI visualization with colored circles
- Pixel highlighting for detections
- Magnifying glass overlay
- North-oriented image rotation
- Image adjustment dialog (brightness, contrast)
- Measure tool for distances

### 9.3 Export Dialogs

- **PDF Export**: Organization name, search name, flagged-only option
- **KML Export**: Coordinate system selection
- **CalTopo Export**: Authentication and upload
- **Zip Export**: Bundle selection

### 9.4 Real-Time Viewers

- **RTMP Color Detection Viewer**: HSV-based live detection
- **RTMP Anomaly Detection Viewer**: Statistical anomaly detection
- **RTMP Motion Detection Viewer**: Motion tracking

### 9.5 Theme Support

- Dark theme (default via pyqtdarktheme)
- Light theme option
- Consistent icon sets for both themes

---

## 10. Configuration

### 10.1 User Preferences

**Storage**: Platform-specific QSettings
- **Windows**: Registry (`HKEY_CURRENT_USER\Software\ADIAT`)
- **macOS**: `~/Library/Preferences/com.adiat.plist`
- **Linux**: `~/.config/ADIAT/ADIAT.conf`

**Available Settings**:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `Theme` | str | 'Dark' | UI theme |
| `PositionFormat` | str | 'Decimal Degrees' | GPS format |
| `TemperatureUnit` | str | 'C' | Celsius/Fahrenheit |
| `DistanceUnit` | str | 'm' | Meters/Feet |
| `MaxAOIs` | int | 1000 | Warning threshold |
| `InputFolder` | str | '' | Last used input |
| `OutputFolder` | str | '' | Last used output |

### 10.2 Algorithm Configuration

**File**: `/app/algorithms.conf`

JSON-based registry of available algorithms with:
- Module name and display label
- Controller and service class names
- Platform support (Windows/Darwin)
- Algorithm type (RGB/Thermal)
- AOI combination setting

### 10.3 Drone Database

**Files**: `/app/drones.pkl`, `/app/xmp.pkl`

Pickle files containing:
- Drone sensor specifications (dimensions, camera info)
- XMP attribute mappings per manufacturer

---

## 11. Build & Deployment

### 11.1 Development Setup

```bash
# Clone repository
git clone https://github.com/crgrove/automated-drone-image-analysis-tool.git
cd automated-drone-image-analysis-tool

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Build UI resources
python setup.py build_res

# Run application
python -m app
```

### 11.2 Build Commands

**Build UI Resources**:
```bash
python setup.py build_res
```
Compiles `.ui` files and `.qrc` resources to Python.

**Create Distribution**:
```bash
python setup.py sdist
```
Creates source distribution with resources.

**Build Executable**:
```bash
python setup.py bdist_app
```
Creates standalone executable using PyInstaller.

### 11.3 PyInstaller Configuration

**File**: `/app.spec`

Bundles:
- Application code
- External tools (ExifTool, DJI SDK, Autel libs)
- Data files (icons, configs, models)
- AI model for person detection

**Output**:
- **Windows**: `dist/ADIAT/ADIAT.exe`
- **macOS**: `dist/ADIAT.app`

### 11.4 UI Resource Compilation

**File**: `/pyuic.json`

Configuration for `pyside6-uic` and `pyside6-rcc` to compile:
- 14 `.ui` files to `*_ui.py`
- 3 `.qrc` files to `*_rc.py`

---

## 12. Testing

### 12.1 Test Structure

```
app/tests/
├── conftest.py                   # Pytest fixtures
├── test_main_ui.py               # Main UI tests
├── algorithms/
│   ├── test_algorithm_service.py
│   ├── test_color_range.py
│   ├── test_hsv_color_range.py
│   ├── test_matched_filter.py
│   ├── test_rx_anomaly.py
│   ├── test_ai_person_detector.py
│   ├── test_temperature_range.py
│   └── test_temperature_anomaly.py
├── core/services/
│   ├── test_config_service.py
│   ├── test_histogram_normalization_service.py
│   ├── test_k_means_clusters_service.py
│   ├── test_logging_service.py
│   ├── test_settings_service.py
│   ├── test_xml_service.py
│   └── test_zip_bundle_service.py
└── helpers/
    ├── test_color_utils.py
    ├── test_location_info.py
    └── test_meta_data_helper.py
```

### 12.2 Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest app/tests/algorithms/test_color_range.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=app
```

### 12.3 Test Configuration

**File**: `/pytest.ini`

```ini
[pytest]
pythonpath = app
qt_api = pyqt5
```

### 12.4 Code Quality

**Linting** (`.flake8`):
```ini
[flake8]
max-line-length = 160
extend-ignore = F401, E402
exclude = dist, .vs, .venv, resource, build, *_ui.py, *_rc.py
```

Run linting:
```bash
flake8 app
```

---

## 13. Contributing Guidelines

### 13.1 Development Workflow

1. **Fork the repository**
2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make changes** following code style guidelines
4. **Write tests** for new functionality
5. **Build UI resources** if modifying `.ui` files
   ```bash
   python setup.py build_res
   ```
6. **Run tests**
   ```bash
   pytest
   ```
7. **Run linting**
   ```bash
   flake8 app
   ```
8. **Commit changes**
   ```bash
   git commit -m "Add feature description"
   ```
9. **Push and create PR**
   ```bash
   git push origin feature/your-feature-name
   ```

### 13.2 Code Style Guidelines

- Follow PEP 8 with max line length of 160
- Use meaningful variable and function names
- Add docstrings for classes and public methods
- Use type hints where appropriate
- Separate concerns: controllers handle UI, services handle logic

### 13.3 Adding a New Algorithm

1. **Create algorithm directory**:
   ```
   app/algorithms/YourAlgorithm/
   ├── __init__.py
   ├── controllers/
   │   ├── __init__.py
   │   └── YourAlgorithmController.py
   ├── services/
   │   ├── __init__.py
   │   └── YourAlgorithmService.py
   └── views/
       └── __init__.py
   ```

2. **Create UI file**: `resources/views/algorithms/YourAlgorithm.ui`

3. **Implement controller** (extend `AlgorithmController`):
   ```python
   class YourAlgorithmController(QWidget, Ui_YourAlgorithm, AlgorithmController):
       def validate(self) -> bool:
           # Validate parameters
           pass

       def get_options(self) -> dict:
           # Return algorithm parameters
           pass

       def load_options(self, options: dict) -> None:
           # Load saved parameters
           pass
   ```

4. **Implement service** (extend `AlgorithmService`):
   ```python
   class YourAlgorithmService(AlgorithmService):
       def process_image(self, img, full_path, input_dir, output_dir):
           # Implement detection logic
           # Return AnalysisResult
           pass
   ```

5. **Register in `algorithms.conf`**:
   ```json
   {
     "name": "YourAlgorithm",
     "label": "Your Algorithm Name",
     "controller": "YourAlgorithmController",
     "service": "YourAlgorithmService",
     "combine_overlapping_aois": true,
     "platforms": ["Windows", "Darwin"],
     "type": "RGB"
   }
   ```

6. **Build resources**:
   ```bash
   python setup.py build_res
   ```

### 13.4 Adding a New Service

1. Create service file in `/app/core/services/`
2. Implement business logic
3. Use signals for thread-safe communication
4. Add tests in `/app/tests/core/services/`

### 13.5 Modifying UI

1. Edit `.ui` file using Qt Designer
2. Run resource build:
   ```bash
   python setup.py build_res
   ```
3. Update controller if adding new widgets

### 13.6 Pull Request Guidelines

- Clear description of changes
- Reference related issues
- Include test coverage
- Update documentation if needed
- Screenshots for UI changes

---

## Appendix A: Key File Locations

| Purpose | File Path |
|---------|-----------|
| Entry point | `/app/__main__.py` |
| Main window | `/app/core/controllers/MainWindow.py` |
| Viewer | `/app/core/controllers/viewer/Viewer.py` |
| Algorithm registry | `/app/algorithms.conf` |
| Analysis service | `/app/core/services/AnalyzeService.py` |
| Image service | `/app/core/services/ImageService.py` |
| XML service | `/app/core/services/XmlService.py` |
| Base algorithm | `/app/algorithms/AlgorithmService.py` |
| Image viewer widget | `/app/core/views/components/QtImageViewer.py` |
| Metadata helper | `/app/helpers/MetaDataHelper.py` |
| GPS utilities | `/app/helpers/LocationInfo.py` |

---

## Appendix B: Common Tasks

### Run the Application
```bash
python -m app
```

### Analyze Images
1. Select algorithm from dropdown
2. Configure parameters
3. Select input folder with images
4. Select output folder for results
5. Click "Start"
6. Click "View Results" when complete

### Export Results
1. Open results in Viewer
2. Flag important AOIs with `F` key
3. Use export buttons for PDF/KML/ZIP

### Add Custom Colors
For HSV Color Range algorithm, use the custom color picker to define precise color ranges for detection.

### Process Thermal Images
1. Select "Temperature Range" or "Temperature Anomaly" algorithm
2. Provide thermal images from supported drones (DJI, Autel, FLIR)
3. Configure temperature thresholds

---

## Appendix C: Troubleshooting

### ExifTool Not Found
Ensure `exiftool.exe` is in `/app/external/` (Windows only).

### CUDA Not Available
AI Person Detector will fall back to CPU mode. Install CUDA toolkit and compatible onnxruntime-gpu for GPU acceleration.

### UI Not Updating
Always compile resources after modifying `.ui` files:
```bash
python setup.py build_res
```

### Import Errors
Ensure you're running from the project root and virtual environment is activated.

### Thermal Parsing Fails
- Check drone manufacturer support
- Ensure thermal SDK libraries are present
- Verify image format compatibility

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-11-18 | ADIAT Team | Initial technical design document |

---

*This document provides a comprehensive technical overview of the ADIAT application. For user documentation, see README.md. For API documentation, refer to inline docstrings in the source code.*
