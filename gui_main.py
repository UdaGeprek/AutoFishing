import sys
import cv2
import numpy as np
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QSlider,
                             QTextEdit, QTabWidget, QGroupBox, QFormLayout, QSpinBox,
                             QDoubleSpinBox, QCheckBox, QRadioButton, QComboBox,
                             QProgressBar, QButtonGroup)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QKeySequence, QShortcut
import qdarktheme

from config import load_config, save_config
from region_selector import RegionSelector, PointSelector
from bot_worker import BotWorker
from audio_detector import AudioDetector


class ClickableLabel(QLabel):
    clicked_image_pos = pyqtSignal(int, int)

    def __init__(self, text=""):
        super().__init__(text)
        self.last_frame = None

    def update_frame(self, frame):
        self.last_frame = frame
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        qt_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_BGR888)
        self.setPixmap(QPixmap.fromImage(qt_img).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.last_frame is not None:
            lbl_w, lbl_h = self.width(), self.height()
            img_h, img_w, _ = self.last_frame.shape

            scale = min(lbl_w / img_w, lbl_h / img_h)
            disp_w = img_w * scale
            disp_h = img_h * scale

            off_x = (lbl_w - disp_w) / 2
            off_y = (lbl_h - disp_h) / 2

            click_x = event.position().x()
            click_y = event.position().y()

            if off_x <= click_x <= off_x + disp_w and off_y <= click_y <= off_y + disp_h:
                real_x = int((click_x - off_x) / scale)
                real_y = int((click_y - off_y) / scale)
                real_x = max(0, min(real_x, img_w - 1))
                real_y = max(0, min(real_y, img_h - 1))
                self.clicked_image_pos.emit(real_x, real_y)

        super().mousePressEvent(event)


class BotGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.is_overlay = False

        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Albion Fishing Bot")
        self.resize(540, 1080)

        self.init_ui()

        self.worker = BotWorker(self.config)
        self.worker.water_frame_ready.connect(self.update_water_viewport)
        self.worker.bar_frame_ready.connect(self.update_bar_viewport)
        self.worker.mask_float_ready.connect(self.update_mask_float)
        self.worker.mask_zone_ready.connect(self.update_mask_zone)
        self.worker.log_ready.connect(self.log)
        self.worker.status_changed.connect(self.update_status)
        self.worker.hsv_updated.connect(self.sync_hsv_ui_from_config)
        self.worker.start()

        # Audio Detector
        self.audio_detector = None
        if self.config.get("audio", {}).get("enabled", False):
            self._start_audio_detector()

        self.shortcut_f1 = QShortcut(QKeySequence("F1"), self)
        self.shortcut_f1.activated.connect(self.worker.toggle_active)

        self.shortcut_overlay = QShortcut(QKeySequence("Shift+Tab"), self)
        self.shortcut_overlay.activated.connect(self.toggle_overlay_mode)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_layout_widget := QWidget())
        main_layout = QVBoxLayout(main_layout_widget)

        # ---------------------------------------------------------------------
        # ВИДОИСКАТЕЛИ
        # ---------------------------------------------------------------------
        viewports_layout = QHBoxLayout()

        box_water = QVBoxLayout()
        box_water.addWidget(QLabel("🌊 Zona Air (Klik = Pipet Warna)"), alignment=Qt.AlignmentFlag.AlignCenter)
        self.viewport_water = ClickableLabel("Memuat...")
        self.viewport_water.setFixedSize(240, 160)
        self.viewport_water.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewport_water.setStyleSheet("border: 2px solid #2e7d32; background: #000; border-radius: 4px;")
        self.viewport_water.clicked_image_pos.connect(lambda x, y: self.handle_pipette_click("water", x, y))
        box_water.addWidget(self.viewport_water)

        box_bar = QVBoxLayout()
        box_bar.addWidget(QLabel("📊 Zona Bar (Klik = Pipet Warna)"), alignment=Qt.AlignmentFlag.AlignCenter)
        self.viewport_bar = ClickableLabel("Memuat...")
        self.viewport_bar.setFixedSize(240, 160)
        self.viewport_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewport_bar.setStyleSheet("border: 2px solid #0288d1; background: #000; border-radius: 4px;")
        self.viewport_bar.clicked_image_pos.connect(lambda x, y: self.handle_pipette_click("bar", x, y))
        box_bar.addWidget(self.viewport_bar)

        viewports_layout.addLayout(box_water)
        viewports_layout.addLayout(box_bar)
        main_layout.addLayout(viewports_layout)

        # ---------------------------------------------------------------------
        # ВКЛАДКИ
        # ---------------------------------------------------------------------
        tabs = QTabWidget()

        # --- ВКЛАДКА 1: Управление ---
        tab_control = QWidget()
        control_layout = QVBoxLayout(tab_control)

        self.lbl_status = QLabel("STATUS: JEDA")
        self.lbl_status.setStyleSheet("font-size: 15px; font-weight: bold; color: #ff5252;")
        control_layout.addWidget(self.lbl_status)

        # --- MODE BOT ---
        group_mode = QGroupBox("🤖 Mode Bot")
        mode_layout = QHBoxLayout(group_mode)
        self.radio_full_auto_visual = QRadioButton("Full Auto (Visual)")
        self.radio_full_auto_audio = QRadioButton("Full Auto (Audio)")
        self.radio_semi_auto = QRadioButton("Semi Auto (Mini-Game saja)")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_full_auto_visual)
        self.mode_group.addButton(self.radio_full_auto_audio)
        self.mode_group.addButton(self.radio_semi_auto)
        current_mode = self.config.get("bot_mode", "full_auto_visual")
        if current_mode == "semi_auto":
            self.radio_semi_auto.setChecked(True)
        elif current_mode == "full_auto_audio":
            self.radio_full_auto_audio.setChecked(True)
        else:
            self.radio_full_auto_visual.setChecked(True)
        self.radio_full_auto_visual.toggled.connect(self.update_bot_mode)
        self.radio_full_auto_audio.toggled.connect(self.update_bot_mode)
        self.radio_semi_auto.toggled.connect(self.update_bot_mode)
        mode_layout.addWidget(self.radio_full_auto_visual)
        mode_layout.addWidget(self.radio_full_auto_audio)
        mode_layout.addWidget(self.radio_semi_auto)
        control_layout.addWidget(group_mode)

        self.btn_start = QPushButton("▶ MULAI / JEDA (F1)")
        self.btn_start.setFixedHeight(38)
        self.btn_start.setStyleSheet("background-color: #2e7d32; font-weight: bold; font-size: 13px;")
        self.btn_start.clicked.connect(lambda: self.worker.toggle_active())
        control_layout.addWidget(self.btn_start)

        self.btn_overlay = QPushButton("👁️ Overlay (Shift+Tab)")
        self.btn_overlay.clicked.connect(self.toggle_overlay_mode)
        control_layout.addWidget(self.btn_overlay)

        # --- SENSITIVITAS GIGITAN ---
        group_bite = QGroupBox("🎣 Deteksi Gigitan")
        bite_layout = QFormLayout(group_bite)
        bite_val = self.config.get("bite_sensitivity", 3)

        bite_row = QHBoxLayout()
        self.slider_bite = QSlider(Qt.Orientation.Horizontal)
        self.slider_bite.setRange(1, 20)
        self.slider_bite.setValue(bite_val)
        self.spin_bite = QSpinBox()
        self.spin_bite.setRange(1, 20)
        self.spin_bite.setValue(bite_val)
        self.spin_bite.setFixedWidth(55)
        self.slider_bite.valueChanged.connect(self.spin_bite.setValue)
        self.spin_bite.valueChanged.connect(self.slider_bite.setValue)
        self.slider_bite.valueChanged.connect(self.update_bite_sensitivity)
        bite_row.addWidget(self.slider_bite)
        bite_row.addWidget(self.spin_bite)

        bite_layout.addRow("Sensitivitas (frame):", bite_row)
        lbl_bite_hint = QLabel("Rendah = sensitif (mudah trigger), Tinggi = lambat (perlu lebih banyak frame)")
        lbl_bite_hint.setStyleSheet("color: #888; font-size: 10px;")
        bite_layout.addRow(lbl_bite_hint)
        control_layout.addWidget(group_bite)

        group_regions = QGroupBox("Pilih Area dengan Mouse")
        reg_layout = QVBoxLayout(group_regions)

        lay_btns = QHBoxLayout()
        btn_select_water = QPushButton("🌊 Zona AIR")
        btn_select_water.clicked.connect(lambda: self.start_region_select("water_region"))
        lay_btns.addWidget(btn_select_water)

        btn_select_bar = QPushButton("📊 Zona BAR")
        btn_select_bar.clicked.connect(lambda: self.start_region_select("bar_region"))
        lay_btns.addWidget(btn_select_bar)
        reg_layout.addLayout(lay_btns)

        # 📍 ВЫБОР ТОЧКИ ЗАБРОСА
        lay_cast = QHBoxLayout()
        btn_select_cast_point = QPushButton("📍 Pilih Titik Lempar")
        btn_select_cast_point.clicked.connect(self.start_point_select)
        lay_cast.addWidget(btn_select_cast_point)

        cast_cfg = self.config.get("cast_point", {})
        self.chk_custom_cast = QCheckBox("Gunakan titik kustom")
        self.chk_custom_cast.setChecked(cast_cfg.get("use_custom", False))
        self.chk_custom_cast.stateChanged.connect(self.update_cast_point_config)
        lay_cast.addWidget(self.chk_custom_cast)
        reg_layout.addLayout(lay_cast)

        self.lbl_cast_point_info = QLabel(self.get_cast_point_info_text())
        self.lbl_cast_point_info.setStyleSheet("color: #888; font-size: 11px;")
        reg_layout.addWidget(self.lbl_cast_point_info)

        # 🎣 СИЛА И ДАЛЬНОСТЬ ЗАБРОСА
        form_cast_power = QFormLayout()
        self.spin_cast_power_time = QDoubleSpinBox()
        self.spin_cast_power_time.setRange(0.10, 2.00)
        self.spin_cast_power_time.setSingleStep(0.05)
        self.spin_cast_power_time.setValue(self.config.get("cast_power_time", 0.55))
        self.spin_cast_power_time.setSuffix(" dtk")
        self.spin_cast_power_time.valueChanged.connect(self.update_cast_power_config)

        self.chk_auto_cast_power = QCheckBox("Hitung otomatis kekuatan berdasarkan jarak")
        self.chk_auto_cast_power.setChecked(self.config.get("auto_cast_power", True))
        self.chk_auto_cast_power.stateChanged.connect(self.update_cast_power_config)

        form_cast_power.addRow("Kekuatan lempar (waktu):", self.spin_cast_power_time)
        reg_layout.addLayout(form_cast_power)
        reg_layout.addWidget(self.chk_auto_cast_power)

        control_layout.addWidget(group_regions)

        # 🎯 БЛОК НАСТРОЙКИ ЗОН МИНИ-ИГРЫ (%)
        group_mg_cfg = QGroupBox("🎯 Perilaku Mini-Game (% lebar zona)")
        mg_form = QFormLayout(group_mg_cfg)

        mg_cfg = self.config.get("minigame", {"target_pct": 58, "danger_left_pct": 25, "danger_right_pct": 75})

        self.spin_target_pct = QSpinBox()
        self.spin_target_pct.setRange(30, 70)
        self.spin_target_pct.setValue(mg_cfg.get("target_pct", 58))
        self.spin_target_pct.setSuffix(" %")
        self.spin_target_pct.valueChanged.connect(self.update_minigame_config)

        self.spin_danger_left = QSpinBox()
        self.spin_danger_left.setRange(5, 45)
        self.spin_danger_left.setValue(mg_cfg.get("danger_left_pct", 25))
        self.spin_danger_left.setSuffix(" %")
        self.spin_danger_left.valueChanged.connect(self.update_minigame_config)

        self.spin_danger_right = QSpinBox()
        self.spin_danger_right.setRange(55, 95)
        self.spin_danger_right.setValue(mg_cfg.get("danger_right_pct", 75))
        self.spin_danger_right.setSuffix(" %")
        self.spin_danger_right.valueChanged.connect(self.update_minigame_config)

        mg_form.addRow("Titik target (Sasaran):", self.spin_target_pct)
        mg_form.addRow("Zona bahaya kiri (<):", self.spin_danger_left)
        mg_form.addRow("Zona bahaya kanan (>):", self.spin_danger_right)

        control_layout.addWidget(group_mg_cfg)

        group_bar_manual = QGroupBox("Pengaturan presisi BAR (piksel)")
        bar_form = QFormLayout(group_bar_manual)

        bar_cfg = self.config["bar_region"]

        self.spin_bar_left = QSpinBox()
        self.spin_bar_left.setRange(0, 3840)
        self.spin_bar_left.setValue(bar_cfg["left"])
        self.spin_bar_left.valueChanged.connect(self.update_manual_bar_region)

        self.spin_bar_top = QSpinBox()
        self.spin_bar_top.setRange(0, 2160)
        self.spin_bar_top.setValue(bar_cfg["top"])
        self.spin_bar_top.valueChanged.connect(self.update_manual_bar_region)

        self.spin_bar_width = QSpinBox()
        self.spin_bar_width.setRange(10, 2000)
        self.spin_bar_width.setValue(bar_cfg["width"])
        self.spin_bar_width.valueChanged.connect(self.update_manual_bar_region)

        self.spin_bar_height = QSpinBox()
        self.spin_bar_height.setRange(10, 2000)
        self.spin_bar_height.setValue(bar_cfg["height"])
        self.spin_bar_height.valueChanged.connect(self.update_manual_bar_region)

        bar_form.addRow("X (Left):", self.spin_bar_left)
        bar_form.addRow("Y (Top):", self.spin_bar_top)
        bar_form.addRow("Lebar (Width):", self.spin_bar_width)
        bar_form.addRow("Tinggi (Height):", self.spin_bar_height)

        control_layout.addWidget(group_bar_manual)
        control_layout.addStretch()
        tabs.addTab(tab_control, "Kontrol")

        # =====================================================================
        # TAB AUDIO
        # =====================================================================
        tab_audio = QWidget()
        audio_layout = QVBoxLayout(tab_audio)

        group_audio_main = QGroupBox("🔊 Deteksi Audio (VB-CABLE)")
        audio_main_layout = QVBoxLayout(group_audio_main)

        self.chk_audio_enabled = QCheckBox("Aktifkan Deteksi Audio")
        self.chk_audio_enabled.setChecked(self.config.get("audio", {}).get("enabled", False))
        self.chk_audio_enabled.stateChanged.connect(self.toggle_audio_detection)
        audio_main_layout.addWidget(self.chk_audio_enabled)

        # Device selector
        device_layout = QHBoxLayout()
        device_layout.addWidget(QLabel("Perangkat:"))
        self.combo_audio_device = QComboBox()
        self.combo_audio_device.setMinimumWidth(200)
        device_layout.addWidget(self.combo_audio_device, stretch=1)
        btn_refresh_devices = QPushButton("🔄")
        btn_refresh_devices.setFixedWidth(35)
        btn_refresh_devices.clicked.connect(self.refresh_audio_devices)
        device_layout.addWidget(btn_refresh_devices)
        audio_main_layout.addLayout(device_layout)

        # Threshold
        audio_form = QFormLayout()
        threshold_row = QHBoxLayout()
        self.slider_audio_threshold = QSlider(Qt.Orientation.Horizontal)
        self.slider_audio_threshold.setRange(1, 1000)
        audio_thresh = self.config.get("audio", {}).get("threshold", 0.15)
        self.slider_audio_threshold.setValue(int(audio_thresh * 100))
        self.spin_audio_threshold = QDoubleSpinBox()
        self.spin_audio_threshold.setRange(0.01, 10.0)
        self.spin_audio_threshold.setSingleStep(0.01)
        self.spin_audio_threshold.setValue(audio_thresh)
        self.spin_audio_threshold.setFixedWidth(70)
        self.slider_audio_threshold.valueChanged.connect(
            lambda v: self.spin_audio_threshold.setValue(v / 100.0))
        self.spin_audio_threshold.valueChanged.connect(
            lambda v: self.slider_audio_threshold.setValue(int(v * 100)))
        self.spin_audio_threshold.valueChanged.connect(self.update_audio_config)
        threshold_row.addWidget(self.slider_audio_threshold)
        threshold_row.addWidget(self.spin_audio_threshold)
        audio_form.addRow("Ambang Batas:", threshold_row)

        # Cooldown
        self.spin_audio_cooldown = QDoubleSpinBox()
        self.spin_audio_cooldown.setRange(0.5, 30.0)
        self.spin_audio_cooldown.setSingleStep(0.5)
        self.spin_audio_cooldown.setSuffix(" dtk")
        self.spin_audio_cooldown.setValue(self.config.get("audio", {}).get("cooldown", 3.0))
        self.spin_audio_cooldown.valueChanged.connect(self.update_audio_config)
        audio_form.addRow("Cooldown:", self.spin_audio_cooldown)

        # Sensitivity
        self.spin_audio_sensitivity = QSpinBox()
        self.spin_audio_sensitivity.setRange(1, 100)
        self.spin_audio_sensitivity.setSuffix(" chunk")
        self.spin_audio_sensitivity.setValue(self.config.get("audio", {}).get("sensitivity", 2))
        self.spin_audio_sensitivity.valueChanged.connect(self.update_audio_config)
        audio_form.addRow("Sensitivitas:", self.spin_audio_sensitivity)
        lbl_sens_hint = QLabel("Berapa kali suara harus berturut-turut melebihi ambang batas\nagar tidak mudah terpancing noise kecil.")
        lbl_sens_hint.setStyleSheet("color: #888; font-size: 10px;")
        audio_form.addRow(lbl_sens_hint)

        audio_main_layout.addLayout(audio_form)

        # Level meter
        level_layout = QHBoxLayout()
        level_layout.addWidget(QLabel("Level:"))
        self.audio_level_bar = QProgressBar()
        self.audio_level_bar.setRange(0, 100)
        self.audio_level_bar.setValue(0)
        self.audio_level_bar.setTextVisible(True)
        self.audio_level_bar.setFormat("%v%")
        self.audio_level_bar.setFixedHeight(22)
        self.audio_level_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #555; border-radius: 3px; background: #1e1e1e; }"
            "QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 #4caf50, stop:0.6 #ffeb3b, stop:1 #f44336); }")
        level_layout.addWidget(self.audio_level_bar, stretch=1)
        audio_main_layout.addLayout(level_layout)

        # Status
        self.lbl_audio_status = QLabel("Status: Tidak aktif")
        self.lbl_audio_status.setStyleSheet("color: #888; font-size: 11px;")
        audio_main_layout.addWidget(self.lbl_audio_status)

        # Hint
        lbl_audio_hint = QLabel(
            "Petunjuk: Arahkan audio game ke VB-CABLE Input di pengaturan suara Windows.\n"
            "Pilih 'CABLE Output' sebagai perangkat di atas untuk menangkap suara gigitan ikan.")
        lbl_audio_hint.setStyleSheet("color: #666; font-size: 10px;")
        lbl_audio_hint.setWordWrap(True)
        audio_main_layout.addWidget(lbl_audio_hint)

        audio_layout.addWidget(group_audio_main)
        audio_layout.addStretch()
        tabs.addTab(tab_audio, "🔊 Audio")

        # Populate audio devices
        self.refresh_audio_devices()

        # --- ВКЛАДКА 2: HSV КАЛИБРОВКА ---
        tab_hsv_main = QWidget()
        hsv_main_layout = QVBoxLayout(tab_hsv_main)

        group_auto = QGroupBox("⚡ Pengaturan Otomatis & Adaptasi")
        auto_layout = QVBoxLayout(group_auto)

        form_tol = QFormLayout()
        auto_cfg = self.config.get("auto_hsv", {})

        self.spin_h_tol = QSpinBox()
        self.spin_h_tol.setRange(1, 90)
        self.spin_h_tol.setValue(auto_cfg.get("h_tol", 12))
        self.spin_h_tol.valueChanged.connect(self.update_auto_config)

        self.spin_s_tol = QSpinBox()
        self.spin_s_tol.setRange(5, 127)
        self.spin_s_tol.setValue(auto_cfg.get("s_tol", 60))
        self.spin_s_tol.valueChanged.connect(self.update_auto_config)

        self.spin_v_tol = QSpinBox()
        self.spin_v_tol.setRange(5, 127)
        self.spin_v_tol.setValue(auto_cfg.get("v_tol", 60))
        self.spin_v_tol.valueChanged.connect(self.update_auto_config)

        form_tol.addRow("Toleransi H (Hue ±):", self.spin_h_tol)
        form_tol.addRow("Toleransi S (Sat ±):", self.spin_s_tol)
        form_tol.addRow("Toleransi V (Val ±):", self.spin_v_tol)
        auto_layout.addLayout(form_tol)

        pipette_target_lay = QHBoxLayout()
        pipette_target_lay.addWidget(QLabel("Target pipet saat klik:"))
        self.radio_pipette_float = QRadioButton("🔴 Pelampung")
        self.radio_pipette_zone = QRadioButton("🟢 Bar Hijau")
        self.radio_pipette_float.setChecked(True)
        pipette_target_lay.addWidget(self.radio_pipette_float)
        pipette_target_lay.addWidget(self.radio_pipette_zone)
        auto_layout.addLayout(pipette_target_lay)

        lay_adaptive = QHBoxLayout()
        self.chk_adapt_float = QCheckBox("🔄 Adaptasi Otomatis Pelampung")
        self.chk_adapt_float.setChecked(auto_cfg.get("adaptive_float", False))
        self.chk_adapt_float.stateChanged.connect(self.update_auto_config)

        self.chk_adapt_zone = QCheckBox("🔄 Adaptasi Otomatis Bar")
        self.chk_adapt_zone.setChecked(auto_cfg.get("adaptive_zone", False))
        self.chk_adapt_zone.stateChanged.connect(self.update_auto_config)

        lay_adaptive.addWidget(self.chk_adapt_float)
        lay_adaptive.addWidget(self.chk_adapt_zone)
        auto_layout.addLayout(lay_adaptive)

        hsv_main_layout.addWidget(group_auto)

        hsv_sub_tabs = QTabWidget()

        sub_float = QWidget()
        layout_float = QVBoxLayout(sub_float)
        self.mask_float_view = QLabel("Mask pelampung")
        self.mask_float_view.setFixedSize(220, 110)
        self.mask_float_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mask_float_view.setStyleSheet("border: 1px solid #ff5252; background: #000;")
        layout_float.addWidget(self.mask_float_view, alignment=Qt.AlignmentFlag.AlignCenter)

        form_float = QFormLayout()
        lay_fh_min, self.s_fh_min, self.sp_fh_min = self.create_hsv_control(0, 179, self.config["hsv"]["lower_float"][0], self.update_hsv_float)
        lay_fs_min, self.s_fs_min, self.sp_fs_min = self.create_hsv_control(0, 255, self.config["hsv"]["lower_float"][1], self.update_hsv_float)
        lay_fv_min, self.s_fv_min, self.sp_fv_min = self.create_hsv_control(0, 255, self.config["hsv"]["lower_float"][2], self.update_hsv_float)
        lay_fh_max, self.s_fh_max, self.sp_fh_max = self.create_hsv_control(0, 179, self.config["hsv"]["upper_float"][0], self.update_hsv_float)
        lay_fs_max, self.s_fs_max, self.sp_fs_max = self.create_hsv_control(0, 255, self.config["hsv"]["upper_float"][1], self.update_hsv_float)
        lay_fv_max, self.s_fv_max, self.sp_fv_max = self.create_hsv_control(0, 255, self.config["hsv"]["upper_float"][2], self.update_hsv_float)

        form_float.addRow("H Min:", lay_fh_min)
        form_float.addRow("S Min:", lay_fs_min)
        form_float.addRow("V Min:", lay_fv_min)
        form_float.addRow("H Max:", lay_fh_max)
        form_float.addRow("S Max:", lay_fs_max)
        form_float.addRow("V Max:", lay_fv_max)
        layout_float.addLayout(form_float)
        hsv_sub_tabs.addTab(sub_float, "🔴 Pelampung")

        sub_zone = QWidget()
        layout_zone = QVBoxLayout(sub_zone)
        self.mask_zone_view = QLabel("Mask bar")
        self.mask_zone_view.setFixedSize(220, 110)
        self.mask_zone_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mask_zone_view.setStyleSheet("border: 1px solid #69f0ae; background: #000;")
        layout_zone.addWidget(self.mask_zone_view, alignment=Qt.AlignmentFlag.AlignCenter)

        form_zone = QFormLayout()
        lay_zh_min, self.s_zh_min, self.sp_zh_min = self.create_hsv_control(0, 179, self.config["hsv"]["lower_zone"][0], self.update_hsv_zone)
        lay_zs_min, self.s_zs_min, self.sp_zs_min = self.create_hsv_control(0, 255, self.config["hsv"]["lower_zone"][1], self.update_hsv_zone)
        lay_zv_min, self.s_zv_min, self.sp_zv_min = self.create_hsv_control(0, 255, self.config["hsv"]["lower_zone"][2], self.update_hsv_zone)
        lay_zh_max, self.s_zh_max, self.sp_zh_max = self.create_hsv_control(0, 179, self.config["hsv"]["upper_zone"][0], self.update_hsv_zone)
        lay_zs_max, self.s_zs_max, self.sp_zs_max = self.create_hsv_control(0, 255, self.config["hsv"]["upper_zone"][1], self.update_hsv_zone)
        lay_zv_max, self.s_zv_max, self.sp_zv_max = self.create_hsv_control(0, 255, self.config["hsv"]["upper_zone"][2], self.update_hsv_zone)

        form_zone.addRow("H Min:", lay_zh_min)
        form_zone.addRow("S Min:", lay_zs_min)
        form_zone.addRow("V Min:", lay_zv_min)
        form_zone.addRow("H Max:", lay_zh_max)
        form_zone.addRow("S Max:", lay_zs_max)
        form_zone.addRow("V Max:", lay_zv_max)
        layout_zone.addLayout(form_zone)
        hsv_sub_tabs.addTab(sub_zone, "🟢 Bar Hijau")

        hsv_main_layout.addWidget(hsv_sub_tabs)
        tabs.addTab(tab_hsv_main, "Kalibrasi HSV")

        main_layout.addWidget(tabs)

        self.log_output = QTextEdit()
        self.log_output.setFixedHeight(140)
        self.log_output.setReadOnly(True)
        self.log_output.placeholderText = "Log sistem..."
        main_layout.addWidget(self.log_output)

    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ---
    def create_hsv_control(self, min_val, max_val, default_val, callback):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(default_val)

        spinbox = QSpinBox()
        spinbox.setRange(min_val, max_val)
        spinbox.setValue(default_val)
        spinbox.setFixedWidth(65)

        slider.valueChanged.connect(spinbox.setValue)
        spinbox.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(callback)

        layout.addWidget(slider)
        layout.addWidget(spinbox)

        return layout, slider, spinbox

    def get_cast_point_info_text(self):
        cp = self.config.get("cast_point", {})
        if cp.get("use_custom", False) and cp.get("x", 0) > 0:
            return f"Titik saat ini: X={cp['x']}, Y={cp['y']}"
        return "Titik saat ini: Pusat Zona Air (default)"

    def start_point_select(self):
        self.hide()
        self.point_selector = PointSelector()
        self.point_selector.point_selected.connect(self.finish_point_select)
        self.point_selector.selection_cancelled.connect(self.cancel_region_select)
        self.point_selector.show()

    def finish_point_select(self, point):
        self.config["cast_point"] = {
            "x": point["x"],
            "y": point["y"],
            "use_custom": True
        }
        save_config(self.config)
        self.chk_custom_cast.blockSignals(True)
        self.chk_custom_cast.setChecked(True)
        self.chk_custom_cast.blockSignals(False)
        self.lbl_cast_point_info.setText(self.get_cast_point_info_text())
        self.log(f"[CONFIG] Titik lempar tersimpan: ({point['x']}, {point['y']})")
        self.show()

    def update_cast_point_config(self):
        if "cast_point" not in self.config:
            self.config["cast_point"] = {"x": 0, "y": 0, "use_custom": False}
        self.config["cast_point"]["use_custom"] = self.chk_custom_cast.isChecked()
        save_config(self.config)
        self.lbl_cast_point_info.setText(self.get_cast_point_info_text())

    def update_cast_power_config(self):
        self.config["cast_power_time"] = self.spin_cast_power_time.value()
        self.config["auto_cast_power"] = self.chk_auto_cast_power.isChecked()
        save_config(self.config)

    def update_minigame_config(self):
        self.config["minigame"] = {
            "target_pct": self.spin_target_pct.value(),
            "danger_left_pct": self.spin_danger_left.value(),
            "danger_right_pct": self.spin_danger_right.value()
        }
        save_config(self.config)

    def handle_pipette_click(self, source_viewport, x, y):
        frame = self.viewport_water.last_frame if source_viewport == "water" else self.viewport_bar.last_frame
        if frame is None:
            return

        y1, y2 = max(0, y-1), min(frame.shape[0], y+2)
        x1, x2 = max(0, x-1), min(frame.shape[1], x+2)
        crop_bgr = frame[y1:y2, x1:x2]
        crop_hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
        avg_hsv = cv2.mean(crop_hsv)[:3]

        h, s, v = int(avg_hsv[0]), int(avg_hsv[1]), int(avg_hsv[2])

        h_tol = self.spin_h_tol.value()
        s_tol = self.spin_s_tol.value()
        v_tol = self.spin_v_tol.value()

        lower = [max(0, h - h_tol), max(0, s - s_tol), max(0, v - v_tol)]
        upper = [min(179, h + h_tol), min(255, s + s_tol), min(255, v + v_tol)]

        target_is_float = self.radio_pipette_float.isChecked()
        target_name = "PELAMPUNG" if target_is_float else "BAR"

        if target_is_float:
            self.config["hsv"]["lower_float"] = lower
            self.config["hsv"]["upper_float"] = upper
        else:
            self.config["hsv"]["lower_zone"] = lower
            self.config["hsv"]["upper_zone"] = upper

        save_config(self.config)
        self.sync_hsv_ui_from_config()

        self.log(f"[🎯 PIPET] Warna HSV({h}, {s}, {v}) dipilih untuk [{target_name}]. Mask: {lower} - {upper}")

    def update_auto_config(self):
        self.config["auto_hsv"] = {
            "h_tol": self.spin_h_tol.value(),
            "s_tol": self.spin_s_tol.value(),
            "v_tol": self.spin_v_tol.value(),
            "adaptive_float": self.chk_adapt_float.isChecked(),
            "adaptive_zone": self.chk_adapt_zone.isChecked()
        }
        save_config(self.config)

    def sync_hsv_ui_from_config(self):
        lf = self.config["hsv"]["lower_float"]
        uf = self.config["hsv"]["upper_float"]
        lz = self.config["hsv"]["lower_zone"]
        uz = self.config["hsv"]["upper_zone"]

        self.s_fh_min.setValue(lf[0])
        self.s_fs_min.setValue(lf[1])
        self.s_fv_min.setValue(lf[2])
        self.s_fh_max.setValue(uf[0])
        self.s_fs_max.setValue(uf[1])
        self.s_fv_max.setValue(uf[2])

        self.s_zh_min.setValue(lz[0])
        self.s_zs_min.setValue(lz[1])
        self.s_zv_min.setValue(lz[2])
        self.s_zh_max.setValue(uz[0])
        self.s_zs_max.setValue(uz[1])
        self.s_zv_max.setValue(uz[2])

    def update_manual_bar_region(self):
        self.config["bar_region"] = {
            "left": self.spin_bar_left.value(),
            "top": self.spin_bar_top.value(),
            "width": self.spin_bar_width.value(),
            "height": self.spin_bar_height.value()
        }
        save_config(self.config)

    def sync_spinboxes_with_config(self):
        bar_cfg = self.config["bar_region"]
        self.spin_bar_left.blockSignals(True)
        self.spin_bar_top.blockSignals(True)
        self.spin_bar_width.blockSignals(True)
        self.spin_bar_height.blockSignals(True)

        self.spin_bar_left.setValue(bar_cfg["left"])
        self.spin_bar_top.setValue(bar_cfg["top"])
        self.spin_bar_width.setValue(bar_cfg["width"])
        self.spin_bar_height.setValue(bar_cfg["height"])

        self.spin_bar_left.blockSignals(False)
        self.spin_bar_top.blockSignals(False)
        self.spin_bar_width.blockSignals(False)
        self.spin_bar_height.blockSignals(False)

    def update_hsv_float(self):
        self.config["hsv"]["lower_float"] = [self.s_fh_min.value(), self.s_fs_min.value(), self.s_fv_min.value()]
        self.config["hsv"]["upper_float"] = [self.s_fh_max.value(), self.s_fs_max.value(), self.s_fv_max.value()]
        save_config(self.config)

    def update_hsv_zone(self):
        self.config["hsv"]["lower_zone"] = [self.s_zh_min.value(), self.s_zs_min.value(), self.s_zv_min.value()]
        self.config["hsv"]["upper_zone"] = [self.s_zh_max.value(), self.s_zs_max.value(), self.s_zv_max.value()]
        save_config(self.config)

    def update_bot_mode(self):
        if self.radio_full_auto_visual.isChecked():
            mode = "full_auto_visual"
        elif self.radio_full_auto_audio.isChecked():
            mode = "full_auto_audio"
        else:
            mode = "semi_auto"
        self.config["bot_mode"] = mode
        save_config(self.config)
        self.log(f"[CONFIG] Mode bot diubah ke: {mode}")

    def update_bite_sensitivity(self, value):
        self.config["bite_sensitivity"] = value
        save_config(self.config)

    # --- AUDIO METHODS ---
    def refresh_audio_devices(self):
        self.combo_audio_device.clear()
        self.combo_audio_device.addItem("-- Pilih Perangkat --", -1)
        if not AudioDetector.is_available():
            self.combo_audio_device.addItem("(sounddevice tidak tersedia)", -1)
            return
        devices = AudioDetector.list_devices()
        saved_idx = self.config.get("audio", {}).get("device_index", -1)
        select_idx = 0
        for dev in devices:
            label = f"{dev['name']} (ch:{dev['channels']})"
            self.combo_audio_device.addItem(label, dev['index'])
            if dev['index'] == saved_idx:
                select_idx = self.combo_audio_device.count() - 1
        if select_idx > 0:
            self.combo_audio_device.setCurrentIndex(select_idx)
        self.combo_audio_device.currentIndexChanged.connect(self.on_audio_device_changed)

    def on_audio_device_changed(self, idx):
        dev_index = self.combo_audio_device.currentData()
        if dev_index is not None:
            if "audio" not in self.config:
                self.config["audio"] = {}
            self.config["audio"]["device_index"] = dev_index
            save_config(self.config)

    def update_audio_config(self):
        if "audio" not in self.config:
            self.config["audio"] = {}
        self.config["audio"]["threshold"] = self.spin_audio_threshold.value()
        self.config["audio"]["cooldown"] = self.spin_audio_cooldown.value()
        self.config["audio"]["sensitivity"] = self.spin_audio_sensitivity.value()
        save_config(self.config)

    def toggle_audio_detection(self, state):
        enabled = bool(state)
        if "audio" not in self.config:
            self.config["audio"] = {}
        self.config["audio"]["enabled"] = enabled
        save_config(self.config)

        if enabled:
            self._start_audio_detector()
        else:
            self._stop_audio_detector()

    def _start_audio_detector(self):
        if not AudioDetector.is_available():
            self.lbl_audio_status.setText("Status: ❌ Library sounddevice tidak tersedia")
            self.log("[AUDIO] ERROR: Library sounddevice tidak tersedia. Install: pip install sounddevice")
            return
        self._stop_audio_detector()
        self.audio_detector = AudioDetector(self.config)
        self.audio_detector.bite_detected.connect(self.worker.on_audio_bite_detected)
        self.audio_detector.bite_detected.connect(
            lambda: self.log("[🔊 AUDIO] Suara gigitan terdeteksi!"))
        self.audio_detector.level_updated.connect(self._update_audio_level)
        self.audio_detector.start()
        self.lbl_audio_status.setText("Status: ✅ Mendengarkan...")
        self.log("[AUDIO] Deteksi audio diaktifkan")

    def _stop_audio_detector(self):
        if self.audio_detector is not None:
            self.audio_detector.stop()
            self.audio_detector = None
        self.audio_level_bar.setValue(0)
        self.lbl_audio_status.setText("Status: Tidak aktif")

    def _update_audio_level(self, level):
        self.audio_level_bar.setValue(min(100, int(level * 100)))

    def update_status(self, text):
        self.lbl_status.setText(f"STATUS: {text}")
        if any(w in text for w in ["AKTIF", "MEMANTAU", "MINI-GAME", "SEMI-AUTO"]):
            self.lbl_status.setStyleSheet("font-size: 15px; font-weight: bold; color: #69f0ae;")
        else:
            self.lbl_status.setStyleSheet("font-size: 15px; font-weight: bold; color: #ff5252;")

    def log(self, text):
        self.log_output.append(text)

    def update_water_viewport(self, frame):
        self.viewport_water.update_frame(frame)

    def update_bar_viewport(self, frame):
        self.viewport_bar.update_frame(frame)

    def update_mask_float(self, mask):
        h, w = mask.shape
        qt_img = QImage(mask.data, w, h, w, QImage.Format.Format_Grayscale8)
        self.mask_float_view.setPixmap(QPixmap.fromImage(qt_img).scaled(
            self.mask_float_view.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def update_mask_zone(self, mask):
        h, w = mask.shape
        qt_img = QImage(mask.data, w, h, w, QImage.Format.Format_Grayscale8)
        self.mask_zone_view.setPixmap(QPixmap.fromImage(qt_img).scaled(
            self.mask_zone_view.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def toggle_overlay_mode(self):
        self.is_overlay = not self.is_overlay
        if self.is_overlay:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
            self.setWindowOpacity(0.75)
            self.log("[UI] Mode Overlay diaktifkan")
        else:
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
            self.setWindowOpacity(1.0)
            self.log("[UI] Mode jendela normal (selalu di atas)")
        self.show()

    def start_region_select(self, region_key):
        self.hide()
        self.selector = RegionSelector()
        self.selector.region_selected.connect(lambda rect: self.finish_region_select(region_key, rect))
        self.selector.selection_cancelled.connect(self.cancel_region_select)
        self.selector.show()

    def finish_region_select(self, region_key, rect):
        self.config[region_key] = rect
        save_config(self.config)
        self.sync_spinboxes_with_config()
        self.log(f"[CONFIG] Zona '{region_key}' tersimpan: {rect}")
        self.show()

    def cancel_region_select(self):
        self.show()

    def closeEvent(self, event):
        if hasattr(self, 'audio_detector') and self.audio_detector is not None:
            self.audio_detector.stop()
        if hasattr(self, 'worker'):
            self.worker.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    try:
        qdarktheme.setup_theme()
    except AttributeError:
        app.setStyleSheet(qdarktheme.load_stylesheet())

    gui = BotGUI()
    gui.show()
    sys.exit(app.exec())