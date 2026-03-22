"""
Main Window for AURIK Professional
Professional audio restoration interface
"""

import math as _math
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
import numpy as np
from scipy.signal import resample_poly as _resample_poly
import soundfile as sf

try:
    from backend.api.bridge import get_aurik_denker_class, get_aurik_denker_instance

    _BRIDGE_AVAILABLE = True
except ImportError:
    _BRIDGE_AVAILABLE = False

    def get_aurik_denker_class():  # type: ignore[misc]
        return None

    def get_aurik_denker_instance():  # type: ignore[misc]
        return None


_TARGET_SR = 48_000


def _resample_to_48k(audio: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    """Resamples audio to 48 kHz if needed. Accepts any input sample rate."""
    if sr == _TARGET_SR:
        return audio.astype(np.float32), sr
    _gcd = _math.gcd(sr, _TARGET_SR)
    _up, _dn = _TARGET_SR // _gcd, sr // _gcd
    axis = 0 if audio.ndim > 1 else -1
    resampled = _resample_poly(audio, _up, _dn, axis=axis).astype(np.float32)
    return resampled, _TARGET_SR


from ..core.preset_manager import Preset, PresetManager
from ..core.queue_manager import QueueManager, QueueStatus
from ..i18n import t
from .audio_player import AudioPlayer
from .preset_browser import PresetBrowserWidget
from .queue_widget import QueueWidget
from .waveform_widget import MatplotlibWaveformWidget as WaveformWidget  # Legacy-Widget (Matplotlib-basiert)


class ProcessingThread(QThread):
    """Background thread for audio processing"""

    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, input_file, output_file, settings):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.settings = settings

    def run(self):
        """Process audio in background"""
        try:
            # §RELEASE_MUST: Singleton-Accessor — kein direktes AurikDenker()
            denker = get_aurik_denker_instance()
            if denker is None:
                raise RuntimeError("AurikDenker-Instanz nicht verfügbar")

            self.progress.emit(10)

            # Load audio — resample to 48 kHz (Aurik internal SR)
            audio, sr = sf.read(self.input_file)
            audio, sr = _resample_to_48k(np.asarray(audio, dtype=np.float32), sr)
            self.progress.emit(20)

            # §RELEASE_MUST: Canonical entrypoint via AurikDenker.denke() — no UV3 bypass
            # Mode: "Restoration" | "Studio 2026" only
            mode = self.settings.get("processing_mode", "Restoration")
            self.progress.emit(30)

            # Process
            result = denker.denke(audio, sr, mode=mode)
            self.progress.emit(80)

            # Save at 48 kHz (internal processing SR)
            sf.write(self.output_file, result.audio, sr)
            self.progress.emit(100)

            self.finished.emit(t("legacy.main.processed_file", file=Path(self.input_file).name))

        except Exception as e:
            self.error.emit(t("legacy.main.processing_error_detail", error=str(e)))


class BatchProcessingThread(QThread):
    """Background thread for batch queue processing"""

    item_started = pyqtSignal(str)  # item_id
    item_progress = pyqtSignal(str, int)  # item_id, progress
    item_finished = pyqtSignal(str)  # item_id
    item_error = pyqtSignal(str, str)  # item_id, error_message
    all_finished = pyqtSignal()

    def __init__(self, queue_manager: QueueManager):
        super().__init__()
        self.queue_manager = queue_manager
        self._stop_requested = False

    def run(self):
        """Process all items in queue"""
        # §RELEASE_MUST: Singleton-Accessor — kein direktes AurikDenker()
        denker = get_aurik_denker_instance()
        if denker is None:
            for item in [i for i in self.queue_manager.items if i.status == QueueStatus.PENDING]:
                msg = "AurikDenker-Instanz nicht verfügbar"
                self.queue_manager.update_item_status(item.id, QueueStatus.FAILED, 0, msg)
                self.item_error.emit(item.id, msg)
            self.all_finished.emit()
            return

        while not self._stop_requested:
            # Get next item
            item = self.queue_manager.get_next_item()
            if item is None:
                break

            try:
                # Mark as processing
                self.queue_manager.update_item_status(item.id, QueueStatus.PROCESSING, 0)
                self.item_started.emit(item.id)

                # Load audio — resample to 48 kHz (Aurik internal SR)
                audio, sr = sf.read(item.input_file)
                audio, sr = _resample_to_48k(np.asarray(audio, dtype=np.float32), sr)
                self.item_progress.emit(item.id, 20)
                self.queue_manager.update_item_status(item.id, QueueStatus.PROCESSING, 20)

                # §RELEASE_MUST: Canonical entrypoint via AurikDenker.denke() — no UV3 bypass
                # Mode: "Restoration" | "Studio 2026" only
                mode = item.settings.get("processing_mode", "Restoration")
                self.item_progress.emit(item.id, 30)
                self.queue_manager.update_item_status(item.id, QueueStatus.PROCESSING, 30)

                # Process
                result = denker.denke(audio, sr, mode=mode)
                self.item_progress.emit(item.id, 80)
                self.queue_manager.update_item_status(item.id, QueueStatus.PROCESSING, 80)

                # Save at 48 kHz (internal processing SR)
                sf.write(item.output_file, result.audio, sr)
                self.item_progress.emit(item.id, 100)

                # Mark as completed
                self.queue_manager.update_item_status(item.id, QueueStatus.COMPLETED, 100)
                self.item_finished.emit(item.id)

            except Exception as e:
                error_msg = str(e)
                self.queue_manager.update_item_status(item.id, QueueStatus.FAILED, 0, error_msg)
                self.item_error.emit(item.id, error_msg)

        self.all_finished.emit()

    def stop(self):
        """Request stop"""
        self._stop_requested = True


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.current_file = None
        self.processing_thread = None
        self.batch_thread = None
        self.queue_manager = QueueManager()
        self.preset_manager = PresetManager()
        self.init_ui()
        self.apply_dark_theme()

    def init_ui(self):
        """Initialize user interface"""
        self.setWindowTitle(t("legacy.main.window_title"))
        self.setGeometry(100, 100, 1600, 900)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout
        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # Left panel: File list and controls
        left_panel = self.create_left_panel()

        # Middle panel: Waveform and settings
        middle_panel = self.create_right_panel()

        # Right panel: Queue
        right_panel = self.create_queue_panel()

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(middle_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)  # Left: 25%
        splitter.setStretchFactor(1, 2)  # Middle: 50%
        splitter.setStretchFactor(2, 1)  # Right: 25%

        main_layout.addWidget(splitter)

        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage(t("status.ready"))

        # Progress bar in status bar
        # §11.4: setRange(0, 10000) — setRange(0, 100) ist explizit verboten
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 10000)
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.hide()
        self.statusBar.addPermanentWidget(self.progress_bar)

    def create_left_panel(self):
        """Create left control panel"""
        panel = QWidget()
        layout = QVBoxLayout()
        panel.setLayout(layout)

        # Title
        title = QLabel(t("legacy.main.brand_title_html"))
        layout.addWidget(title)

        # File list
        file_group = QGroupBox(t("legacy.main.audio_files"))
        file_layout = QVBoxLayout()
        file_group.setLayout(file_layout)

        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        file_layout.addWidget(self.file_list)

        # File buttons
        btn_layout = QHBoxLayout()
        btn_add = QPushButton(t("legacy.main.add_files"))
        btn_add.clicked.connect(self.add_files)
        btn_clear = QPushButton(t("legacy.main.clear"))
        btn_clear.clicked.connect(self.file_list.clear)
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_clear)
        file_layout.addLayout(btn_layout)

        layout.addWidget(file_group)

        # Medium selection — §RELEASE_MUST: auto-detected by MediumClassifier, no manual override
        medium_group = QGroupBox(t("legacy.main.medium_type"))
        medium_layout = QVBoxLayout()
        medium_group.setLayout(medium_layout)

        self.medium_combo = None  # §RELEASE_MUST: kein manueller Tonträger — MediumClassifier erkennt automatisch
        medium_label = QLabel("🔍 Wird automatisch erkannt")
        medium_label.setStyleSheet("color: #888888; font-style: italic;")
        medium_layout.addWidget(medium_label)

        layout.addWidget(medium_group)

        # Processing mode — §RELEASE_MUST: one-button contract, only Restoration | Studio 2026
        mode_group = QGroupBox(t("legacy.main.processing_mode"))
        mode_layout = QVBoxLayout()
        mode_group.setLayout(mode_layout)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Restoration", "Restoration")
        self.mode_combo.addItem("Studio 2026", "Studio 2026")
        self.mode_combo.setCurrentIndex(0)  # Restoration (default)
        mode_layout.addWidget(self.mode_combo)

        layout.addWidget(mode_group)

        # Process button
        self.btn_process = QPushButton(t("legacy.main.process_now"))
        self.btn_process.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                font-size: 13px;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.btn_process.clicked.connect(self.process_audio)
        self.btn_process.setEnabled(False)
        layout.addWidget(self.btn_process)

        # Add to Queue button
        self.btn_add_queue = QPushButton(t("legacy.main.add_to_queue"))
        self.btn_add_queue.setStyleSheet("""
            QPushButton {
                background-color: #00aa00;
                color: white;
                font-size: 13px;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #00cc00;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.btn_add_queue.clicked.connect(self.add_to_queue)
        self.btn_add_queue.setEnabled(False)
        layout.addWidget(self.btn_add_queue)

        # Preset browser
        preset_group = QGroupBox(t("legacy.main.presets"))
        preset_layout = QVBoxLayout()
        preset_group.setLayout(preset_layout)

        self.preset_browser = PresetBrowserWidget(self.preset_manager)
        self.preset_browser.preset_applied.connect(self.apply_preset)
        preset_layout.addWidget(self.preset_browser)

        layout.addWidget(preset_group)

        return panel

    def create_right_panel(self):
        """Create right settings panel"""
        panel = QWidget()
        layout = QVBoxLayout()
        panel.setLayout(layout)

        # Tabs for Waveform and Preview
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #444444;
                border-radius: 3px;
                background: #1e1e1e;
            }
            QTabBar::tab {
                background: #2d2d2d;
                color: #cccccc;
                padding: 8px 20px;
                border: 1px solid #444444;
                border-bottom: none;
                border-top-left-radius: 3px;
                border-top-right-radius: 3px;
            }
            QTabBar::tab:selected {
                background: #0078d4;
                color: white;
            }
            QTabBar::tab:hover {
                background: #3d3d3d;
            }
        """)

        # Waveform tab
        waveform_tab = QWidget()
        waveform_layout = QVBoxLayout()
        waveform_tab.setLayout(waveform_layout)

        self.waveform_widget = WaveformWidget()
        waveform_layout.addWidget(self.waveform_widget)

        tabs.addTab(waveform_tab, t("legacy.main.tab_waveform"))

        # Preview tab
        preview_tab = QWidget()
        preview_layout = QVBoxLayout()
        preview_tab.setLayout(preview_layout)

        self.audio_player = AudioPlayer()
        preview_layout.addWidget(self.audio_player)

        tabs.addTab(preview_tab, t("legacy.main.tab_preview"))

        layout.addWidget(tabs)

        # Musical Goals — §RELEASE_MUST: Vollautarker Bedienvertrag
        # Manuelle Goal-Slider sind im Produktions-UI verboten (One-Button-Contract)
        # 14 Goals werden automatisch durch AdaptiveGoalThresholds + MusicalGoalsChecker optimiert
        goals_group = QGroupBox(t("legacy.main.musical_goals"))
        goals_layout = QVBoxLayout()
        goals_group.setLayout(goals_layout)

        self.goal_sliders = {}  # §RELEASE_MUST: keine manuellen Slider — automatisch optimiert
        goals_info = QLabel(
            "✅ 14 Musical Goals werden automatisch optimiert\n(Natürlichkeit, Authentizität, Brillanz, Wärme ...)"
        )
        goals_info.setStyleSheet("color: #888888; font-style: italic; padding: 4px;")
        goals_info.setWordWrap(True)
        goals_layout.addWidget(goals_info)

        layout.addWidget(goals_group)

        # Phase 2.3 Enhancement
        enhancement_group = QGroupBox(t("legacy.main.instrumental_enhancement"))
        enhancement_layout = QVBoxLayout()
        enhancement_group.setLayout(enhancement_layout)

        enhance_grid = QHBoxLayout()

        self.enhancement_checks = {}
        enhancements = [
            ("Bass", "legacy.main.enhancement_bass"),
            ("Drums", "legacy.main.enhancement_drums"),
            ("Guitar", "legacy.main.enhancement_guitar"),
            ("Piano", "legacy.main.enhancement_piano"),
            ("Brass", "legacy.main.enhancement_brass"),
            ("Spatial", "legacy.main.enhancement_spatial"),
        ]

        for enhancement, text_key in enhancements:
            checkbox = QCheckBox(t(text_key))
            enhance_grid.addWidget(checkbox)
            self.enhancement_checks[enhancement] = checkbox

        enhancement_layout.addLayout(enhance_grid)
        layout.addWidget(enhancement_group)

        layout.addStretch()

        return panel

    def add_files(self):
        """Add audio files to process"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            t("legacy.main.select_audio_files"),
            "",
            t("legacy.main.audio_files_filter"),
        )

        for file in files:
            self.file_list.addItem(file)

        if self.file_list.count() > 0:
            self.btn_process.setEnabled(True)
            self.btn_add_queue.setEnabled(True)

    def on_file_selected(self):
        """Handle file selection"""
        items = self.file_list.selectedItems()
        if items:
            self.current_file = items[0].text()
            self.load_waveform()

    def load_waveform(self):
        """Load and display waveform with progress bar"""
        try:
            # Premium-Look für den Ladebalken
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 2px solid #444;
                    border-radius: 10px;
                    text-align: center;
                    font: bold 14px "Segoe UI", "Arial";
                    color: #fff;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #232526, stop:1 #414345);
                }
                QProgressBar::chunk {
                    border-radius: 8px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #00c6ff, stop:0.5 #0072ff, stop:1 #005bea);
                    box-shadow: 0px 2px 8px #0072ff88;
                }
            """)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(t("legacy.main.loading_file_progress"))
            self.progress_bar.show()
            self.statusBar.showMessage(t("legacy.main.loading_file"))

            # Fortschritts-Signal verbinden
            self.waveform_widget.progress.connect(self.update_progress)
            # Start Ladeprozess (sendet 10, 40, 70, 90, 100)
            success_waveform = self.waveform_widget.load_audio(self.current_file)
            # Player laden (90%)
            self.progress_bar.setValue(9000)
            QApplication.processEvents()
            success_player = self.audio_player.load_audio(self.current_file)
            # Abschluss
            self.progress_bar.setValue(10000)
            QApplication.processEvents()
            self.progress_bar.hide()
            self.statusBar.showMessage(t("status.ready"))

            if not success_waveform or not success_player:
                QMessageBox.warning(
                    self,
                    t("legacy.common.error_title"),
                    t("legacy.main.failed_load_audio", file=self.current_file),
                )

            # Fortschritts-Signal trennen, um Mehrfachverbindungen zu vermeiden
            self.waveform_widget.progress.disconnect(self.update_progress)

        except Exception as e:
            self.progress_bar.hide()
            self.statusBar.showMessage(t("legacy.main.waveform_load_error_status"))
            QMessageBox.critical(
                self,
                t("legacy.common.error_title"),
                t("legacy.main.waveform_load_error", error=str(e)),
            )

    def process_audio(self):
        """Process selected audio files"""
        if self.processing_thread and self.processing_thread.isRunning():
            QMessageBox.warning(self, t("dialog.processing_running_title"), t("legacy.main.already_processing"))
            return

        items = self.file_list.selectedItems()
        if not items:
            QMessageBox.warning(self, t("legacy.main.no_selection_title"), t("legacy.main.no_selection_body"))
            return

        input_file = items[0].text()

        # Get output file
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            t("legacy.main.save_processed_audio"),
            str(Path(input_file).stem) + "_restored.wav",
            t("legacy.main.wav_filter"),
        )

        if not output_file:
            return

        # §RELEASE_MUST: Medium wird automatisch durch MediumClassifier erkannt
        # §RELEASE_MUST: Mode nur "Restoration" | "Studio 2026"
        settings = {
            "processing_mode": self.mode_combo.currentData(),
        }

        # Start processing
        self.processing_thread = ProcessingThread(input_file, output_file, settings)
        self.processing_thread.progress.connect(self.update_progress)
        self.processing_thread.finished.connect(self.on_processing_finished)
        self.processing_thread.error.connect(self.on_processing_error)

        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.btn_process.setEnabled(False)
        self.statusBar.showMessage(t("status.restoring", percent=0))

        self.processing_thread.start()

    def update_progress(self, value):
        """Update progress bar — scales 0-100 signal to internal 0-10000 range (§11.4)"""
        self.progress_bar.setValue(max(100, min(10000, value * 100)))

    def on_processing_finished(self, message):
        """Handle processing completion"""
        self.progress_bar.hide()
        self.btn_process.setEnabled(True)
        self.statusBar.showMessage(t("status.ready"))
        QMessageBox.information(self, t("legacy.common.success_title"), message)

    def on_processing_error(self, error_message):
        """Handle processing error"""
        self.progress_bar.hide()
        self.btn_process.setEnabled(True)
        self.statusBar.showMessage(t("legacy.common.error_short"))
        QMessageBox.critical(self, t("dialog.processing_error_title"), error_message)

    def create_queue_panel(self):
        """Create queue management panel"""
        panel = QWidget()
        layout = QVBoxLayout()
        panel.setLayout(layout)

        # Queue widget
        self.queue_widget = QueueWidget(self.queue_manager)
        self.queue_widget.process_queue_requested.connect(self.process_queue)
        self.queue_widget.clear_queue_requested.connect(self.clear_queue)
        self.queue_widget.remove_item_requested.connect(self.remove_queue_item)
        layout.addWidget(self.queue_widget)

        return panel

    def add_to_queue(self):
        """Add selected files to processing queue"""
        # Get selected files or all files
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            # Add all files
            files = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        else:
            files = [item.text() for item in selected_items]

        if not files:
            QMessageBox.warning(self, t("dialog.no_files_title"), t("legacy.main.no_files_for_queue"))
            return

        # §RELEASE_MUST: Medium wird automatisch durch MediumClassifier erkannt
        # §RELEASE_MUST: Mode nur "Restoration" | "Studio 2026"
        settings = {
            "processing_mode": self.mode_combo.currentData(),
        }

        # Choose output directory
        output_dir = QFileDialog.getExistingDirectory(self, t("legacy.main.select_output_dir"), str(Path.home()))

        if not output_dir:
            return

        # Add files to queue
        added_count = 0
        for input_file in files:
            filename = Path(input_file).stem
            ext = Path(input_file).suffix
            output_file = str(Path(output_dir) / f"{filename}_restored{ext}")

            item = self.queue_manager.add_item(input_file, output_file, settings)
            self.queue_widget.add_item(item)
            added_count += 1

        self.statusBar.showMessage(t("legacy.main.added_to_queue", count=added_count), 3000)

    def process_queue(self):
        """Start batch processing of queue"""
        if self.batch_thread and self.batch_thread.isRunning():
            QMessageBox.warning(self, t("dialog.processing_running_title"), t("legacy.main.queue_already_processing"))
            return

        stats = self.queue_manager.get_queue_stats()
        if stats["pending"] == 0:
            QMessageBox.information(self, t("legacy.main.queue_empty_title"), t("dialog.no_pending_body"))
            return

        # Start batch processing
        self.batch_thread = BatchProcessingThread(self.queue_manager)
        self.batch_thread.item_started.connect(self.on_queue_item_started)
        self.batch_thread.item_progress.connect(self.on_queue_item_progress)
        self.batch_thread.item_finished.connect(self.on_queue_item_finished)
        self.batch_thread.item_error.connect(self.on_queue_item_error)
        self.batch_thread.all_finished.connect(self.on_queue_all_finished)

        self.statusBar.showMessage(t("legacy.main.processing_queue"))
        self.batch_thread.start()

    def on_queue_item_started(self, item_id):
        """Handle queue item start"""
        self.queue_widget.update_item(item_id, status=QueueStatus.PROCESSING)
        item = self.queue_manager.get_item_by_id(item_id)
        if item:
            self.statusBar.showMessage(t("legacy.main.processing_item", file=Path(item.input_file).name))

    def on_queue_item_progress(self, item_id, progress):
        """Handle queue item progress"""
        self.queue_widget.update_item(item_id, progress=progress)

    def on_queue_item_finished(self, item_id):
        """Handle queue item completion"""
        self.queue_widget.update_item(item_id, status=QueueStatus.COMPLETED, progress=100)

    def on_queue_item_error(self, item_id, error_message):
        """Handle queue item error"""
        self.queue_widget.update_item(item_id, status=QueueStatus.FAILED)
        # Don't show error dialog during batch processing

    def on_queue_all_finished(self):
        """Handle queue completion"""
        stats = self.queue_manager.get_queue_stats()
        self.statusBar.showMessage(
            t("legacy.main.queue_complete_status", completed=stats["completed"], failed=stats["failed"]),
            5000,
        )

        QMessageBox.information(
            self,
            t("legacy.main.queue_complete_title"),
            t("legacy.main.queue_complete_body", completed=stats["completed"], failed=stats["failed"]),
        )

    def clear_queue(self):
        """Clear completed items from queue"""
        self.queue_manager.clear_queue(clear_completed=False)
        self.queue_widget.refresh_display()
        self.statusBar.showMessage(t("legacy.main.cleared_completed"), 2000)

    def remove_queue_item(self, item_id):
        """Remove item from queue"""
        if self.queue_manager.remove_item(item_id):
            self.queue_widget.remove_item(item_id)
            self.statusBar.showMessage(t("legacy.main.removed_from_queue"), 2000)
        else:
            QMessageBox.warning(self, t("legacy.main.cannot_remove_title"), t("legacy.main.cannot_remove_body"))

    def apply_preset(self, preset: Preset):
        """Apply preset to UI settings"""

        # §RELEASE_MUST: Medium wird automatisch erkannt — kein manuelles Setzen
        # §RELEASE_MUST: Mode-Map: nur Restoration | Studio 2026
        mode_map_reverse = {"Restoration": 0, "Studio 2026": 1}

        # Set processing mode (only Restoration / Studio 2026)
        if hasattr(preset, "processing_mode") and preset.processing_mode in mode_map_reverse:
            self.mode_combo.setCurrentIndex(mode_map_reverse[preset.processing_mode])

        # §RELEASE_MUST: Musical Goals werden automatisch optimiert — keine manuellen Slider
        # self.goal_sliders ist leer (One-Button-Contract)

        # Set enhancements
        for enhancement_name, checkbox in self.enhancement_checks.items():
            if enhancement_name in preset.enhancements:
                checkbox.setChecked(preset.enhancements[enhancement_name])

        # Show message
        self.statusBar.showMessage(t("legacy.main.applied_preset", name=preset.name), 3000)
        QMessageBox.information(
            self,
            t("legacy.main.preset_applied_title"),
            t("legacy.main.preset_applied_body", name=preset.name, description=preset.description),
        )

    def apply_dark_theme(self):
        """Apply dark color scheme"""
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.black)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)

        self.setPalette(palette)
