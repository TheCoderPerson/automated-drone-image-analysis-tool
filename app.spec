import platform
import glob
import os
# -*- mode: python -*-

block_cipher = None

try:
    spec_dir = os.path.abspath(os.path.dirname(__file__))
except NameError:
    # __file__ may be undefined in some PyInstaller contexts; fall back to cwd
    spec_dir = os.path.abspath(os.getcwd())
translation_candidates = [
    os.path.join(spec_dir, 'translations', 'app_en.qm'),
    os.path.join(spec_dir, 'translations', 'app_it.qm'),
    os.path.join(spec_dir, 'translations', 'app_es.qm'),
    os.path.join(spec_dir, 'translations', 'app_nl.qm'),
]
translation_datas = [(path, 'translations') for path in translation_candidates if os.path.exists(path)]

# Runtime hook: default packaged builds to WARNING-level logging so shipped apps
# don't accumulate verbose debug/info logs on users' machines. It runs inside the
# frozen app at startup (a spec-level env assignment would only affect the build
# machine). setdefault keeps ADIAT_LOG_LEVEL overridable for field debugging; the
# policy also matches LoggerService.resolve_log_level's sys.frozen default.
adiat_runtime_hooks = [os.path.join(spec_dir, 'runtime_hooks', 'set_log_level.py')]

if platform.system() == 'Windows':
    a = Analysis(['app/__main__.py'],
                pathex=['app'],
                binaries=[
                    ('LICENSE','.'),
                    ('app/external/exiftool.exe','external'),
                    ('app/external/dji_thermal_sdk_v1.7_20241205','external/dji_thermal_sdk_v1.7_20241205'),
                    ('app/external/autel', 'external/autel')
                ],
                datas=[
                    ('resources/icons/ADIAT.ico','.'),
                    ('app/algorithms.conf','.'),
                    ('app/drones.csv', '.'),
                    ('app/xmp.csv', '.'),
                    ('app/colors.pkl', '.'),
                    ('colors.csv', '.'),
                    # AI Person Detector models
                    ('app/algorithms/models/AIPersonDetector/ai_person_model_V3_640.onnx', 'algorithms/models/AIPersonDetector'),
                    ('app/algorithms/models/AIPersonDetector/ai_person_model_V3_1024.onnx', 'algorithms/models/AIPersonDetector')
                    ] + translation_datas,

                hiddenimports=[
                    'shapely',
                    'shapely.geometry',
                    # pysolar dispatches between numeric_numpy / numeric_python at runtime;
                    # PyInstaller's static analysis misses the fallback path.
                    'pysolar',
                    'pysolar.solar',
                    'pysolar.numeric',
                    'pysolar.numeric_numpy',
                    'pysolar.numeric_python',
                    # Image algorithm services (dynamically loaded via importlib in AnalyzeService)
                    'algorithms.images.ColorRange.services.ColorRangeService',
                    'algorithms.images.HSVColorRange.services.HSVColorRangeService',
                    'algorithms.images.MatchedFilter.services.MatchedFilterService',
                    'algorithms.images.RXAnomaly.services.RXAnomalyService',
                    'algorithms.images.MRMap.services.MRMapService',
                    'algorithms.images.ThermalRange.services.ThermalRangeService',
                    'algorithms.images.ThermalAnomaly.services.ThermalAnomalyService',
                    'algorithms.images.ThermalResidualAnomaly.services.ThermalResidualAnomalyService',
                    'algorithms.images.AIPersonDetector.services.AIPersonDetectorService',
                    # Streaming algorithms modules
                    'algorithms.streaming',
                    'algorithms.streaming.MotionDetection',
                    'algorithms.streaming.MotionDetection.controllers',
                    'algorithms.streaming.MotionDetection.controllers.MotionDetectionController',
                    'algorithms.streaming.MotionDetection.controllers.MotionDetectionWizardController',
                    'algorithms.streaming.MotionDetection.services',
                    'algorithms.streaming.MotionDetection.services.MotionDetectionService',
                    'algorithms.streaming.MotionDetection.views',
                    'algorithms.streaming.ColorDetection',
                    'algorithms.streaming.ColorDetection.controllers',
                    'algorithms.streaming.ColorDetection.controllers.ColorDetectionController',
                    'algorithms.streaming.ColorDetection.controllers.ColorDetectionWizardController',
                    'algorithms.streaming.ColorDetection.services',
                    'algorithms.streaming.ColorDetection.services.ColorDetectionService',
                    'algorithms.streaming.ColorDetection.views',
                    'algorithms.streaming.ColorDetection.views.ColorDetectionControlWidget',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.controllers',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.controllers.ColorAnomalyAndMotionDetectionController',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.controllers.ColorAnomalyAndMotionDetectionWizardController',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.services',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.services.ColorAnomalyAndMotionDetectionOrchestrator',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.services.ColorAnomalyService',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.services.MotionDetectionService',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.services.shared_types',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.services.utils',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.views',
                    'algorithms.streaming.ColorAnomalyAndMotionDetection.views.ColorAnomalyAndMotionDetectionControlWidget',
                ],
                hookspath=None,
                runtime_hooks=adiat_runtime_hooks,
                excludes=['PyQt5', 'PyQt6'],
                cipher=block_cipher)
elif platform.system() == 'Darwin':
    a = Analysis(['app/__main__.py'],
                    pathex=['app'],
                    binaries=[
                        ('LICENSE','.')
                    ],
                    datas=[
                        ('resources/icons/ADIAT.ico','.'),
                        ('app/algorithms.conf','.'),
                        ('app/drones.csv', '.'),
                        ('app/xmp.csv', '.'),
                        # Color lists used by ColorListService (expects under app/)
                        ('app/colors.pkl', 'app'),
                        ('colors.csv', 'app'),
                        # AI Person Detector models
                        ('app/algorithms/models/AIPersonDetector/ai_person_model_V3_640.onnx', 'algorithms/models/AIPersonDetector'),
                        ('app/algorithms/models/AIPersonDetector/ai_person_model_V3_1024.onnx', 'algorithms/models/AIPersonDetector')
                        ] + translation_datas,
                    hiddenimports=[
                        'shapely',
                        'shapely.geometry',
                        # pysolar dispatches between numeric_numpy / numeric_python at runtime;
                        # PyInstaller's static analysis misses the fallback path.
                        'pysolar',
                        'pysolar.solar',
                        'pysolar.numeric',
                        'pysolar.numeric_numpy',
                        'pysolar.numeric_python',
                        # Image algorithm services (dynamically loaded via importlib in AnalyzeService)
                        'algorithms.images.ColorRange.services.ColorRangeService',
                        'algorithms.images.HSVColorRange.services.HSVColorRangeService',
                        'algorithms.images.MatchedFilter.services.MatchedFilterService',
                        'algorithms.images.RXAnomaly.services.RXAnomalyService',
                        'algorithms.images.MRMap.services.MRMapService',
                        'algorithms.images.ThermalRange.services.ThermalRangeService',
                        'algorithms.images.ThermalAnomaly.services.ThermalAnomalyService',
                        'algorithms.images.ThermalResidualAnomaly.services.ThermalResidualAnomalyService',
                        'algorithms.images.AIPersonDetector.services.AIPersonDetectorService',
                        # Streaming algorithms modules
                        'algorithms.streaming',
                        'algorithms.streaming.MotionDetection',
                        'algorithms.streaming.MotionDetection.controllers',
                        'algorithms.streaming.MotionDetection.controllers.MotionDetectionController',
                        'algorithms.streaming.MotionDetection.controllers.MotionDetectionWizardController',
                        'algorithms.streaming.MotionDetection.services',
                        'algorithms.streaming.MotionDetection.services.MotionDetectionService',
                        'algorithms.streaming.MotionDetection.views',
                        'algorithms.streaming.ColorDetection',
                        'algorithms.streaming.ColorDetection.controllers',
                        'algorithms.streaming.ColorDetection.controllers.ColorDetectionController',
                        'algorithms.streaming.ColorDetection.controllers.ColorDetectionWizardController',
                        'algorithms.streaming.ColorDetection.services',
                        'algorithms.streaming.ColorDetection.services.ColorDetectionService',
                        'algorithms.streaming.ColorDetection.views',
                        'algorithms.streaming.ColorDetection.views.ColorDetectionControlWidget',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.controllers',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.controllers.ColorAnomalyAndMotionDetectionController',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.controllers.ColorAnomalyAndMotionDetectionWizardController',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.services',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.services.ColorAnomalyAndMotionDetectionOrchestrator',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.services.ColorAnomalyService',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.services.MotionDetectionService',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.services.shared_types',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.services.utils',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.views',
                        'algorithms.streaming.ColorAnomalyAndMotionDetection.views.ColorAnomalyAndMotionDetectionControlWidget',
                    ],
                    hookspath=None,
                    runtime_hooks=adiat_runtime_hooks,
                    excludes=['PyQt5', 'PyQt6'],
                    cipher=block_cipher)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name='ADIAT',
          debug=False,
          strip=False,
          upx=True,
          console=False,
          icon='resources/icons/ADIAT.ico')

coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               name='ADIAT')

app = BUNDLE(coll,
             name='ADIAT.app',
             icon='resources/icons/ADIAT.ico',
             bundle_identifier=None)
