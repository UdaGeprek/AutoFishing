import copy
import sys

import cv2
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bot_worker import BotWorker
from config import (
    delete_profile,
    get_language,
    list_profiles,
    load_meta,
    load_profile,
    load_startup_config,
    reset_to_factory_default,
    save_language,
    save_profile,
)
from i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, Translator
from region_selector import RegionSelector
from ui_theme import VIEWPORT_BAR_BORDER, VIEWPORT_WATER_BORDER, apply_app_theme
from ui_widgets import InfoIcon


class ClickableLabel(QLabel):
    clicked_image_pos = pyqtSignal(int, int)

    def __init__(self, text=""):
        super().__init__(text)
        self.last_frame = None

    def update_frame(self, frame):
        self.last_frame = frame
        h, w, ch = frame.shape
        qt_img = QImage(frame.data, w, h, ch * w, QImage.Format.Format_BGR888)
        self.setPixmap(
            QPixmap.fromImage(qt_img).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.last_frame is not None:
            lbl_w, lbl_h = self.width(), self.height()
            img_h, img_w, _ = self.last_frame.shape
            scale = min(lbl_w / img_w, lbl_h / img_h)
            disp_w, disp_h = img_w * scale, img_h * scale
            off_x, off_y = (lbl_w - disp_w) / 2, (lbl_h - disp_h) / 2
            cx, cy = event.position().x(), event.position().y()
            if off_x <= cx <= off_x + disp_w and off_y <= cy <= off_y + disp_h:
                rx = max(0, min(int((cx - off_x) / scale), img_w - 1))
                ry = max(0, min(int((cy - off_y) / scale), img_h - 1))
                self.clicked_image_pos.emit(rx, ry)
        super().mousePressEvent(event)


class BotGUI(QMainWindow):
    PROFILE_FACTORY = "__factory__"

    def __init__(self):
        super().__init__()
        self.config = load_startup_config()
        self.i18n = Translator(get_language())
        self._session_dirty = False
        self._loading_ui = False
        self._status_key = "paused"
        self.is_overlay = False
        meta = load_meta()
        self._active_saved_profile = meta.get("active_profile")

        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        self.resize(920, 720)

        self.init_ui()

        self.worker = BotWorker(self.config)
        self.worker.water_frame_ready.connect(self.update_water_viewport)
        self.worker.bar_frame_ready.connect(self.update_bar_viewport)
        self.worker.mask_float_ready.connect(self.update_mask_float)
        self.worker.mask_zone_ready.connect(self.update_mask_zone)
        self.worker.log_ready.connect(self.log)
        self.worker.status_changed.connect(self.update_status)
        self.worker.hsv_updated.connect(self.sync_hsv_ui_from_config)
        self.worker.stats_updated.connect(self.update_stats_ui)
        self.worker.start()

        self.btn_start.clicked.connect(self.worker.toggle_active)
        self.shortcut_f1 = QShortcut(QKeySequence("F1"), self)
        self.shortcut_f1.activated.connect(self.worker.toggle_active)
        self.shortcut_overlay = QShortcut(QKeySequence("Shift+Tab"), self)
        self.shortcut_overlay.activated.connect(self.toggle_overlay_mode)

        idx = self.combo_lang.findData(self.i18n.lang)
        if idx >= 0:
            self.combo_lang.blockSignals(True)
            self.combo_lang.setCurrentIndex(idx)
            self.combo_lang.blockSignals(False)
        self._refresh_profile_combo()
        self._loading_ui = True
        self.apply_translations()
        self._loading_ui = False

    def tr(self, key: str, **kwargs) -> str:
        return self.i18n.tr(key, **kwargs)

    # ------------------------------------------------------------------ UI build
    def init_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(8)

        # Language bar
        lang_row = QHBoxLayout()
        self.lbl_lang = QLabel()
        lang_row.addWidget(self.lbl_lang)
        self.combo_lang = QComboBox()
        for code, label in SUPPORTED_LANGUAGES.items():
            self.combo_lang.addItem(label, code)
        self.combo_lang.currentIndexChanged.connect(self.on_language_changed)
        lang_row.addWidget(self.combo_lang)
        lang_row.addStretch()
        outer.addLayout(lang_row)

        body = QHBoxLayout()
        body.setSpacing(10)

        # --- Left: live previews (fixed, no scroll) ---
        preview = QVBoxLayout()
        preview.setSpacing(6)
        self._preview_heads = []
        for attr, border, handler in (
            ("viewport_water", VIEWPORT_WATER_BORDER, lambda x, y: self.handle_pipette_click("water", x, y)),
            ("viewport_bar", VIEWPORT_BAR_BORDER, lambda x, y: self.handle_pipette_click("bar", x, y)),
        ):
            head = QHBoxLayout()
            title = QLabel()
            tip = InfoIcon("")
            head.addWidget(title)
            head.addWidget(tip)
            head.addStretch()
            preview.addLayout(head)
            self._preview_heads.append((title, tip, attr))

            vp = ClickableLabel()
            vp.setFixedSize(220, 130)
            vp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vp.setStyleSheet(f"border: 2px solid {border}; background: #000; border-radius: 4px;")
            vp.clicked_image_pos.connect(handler)
            setattr(self, attr, vp)
            preview.addWidget(vp)
        preview.addStretch()
        body.addLayout(preview)

        # --- Right: contextual tabs ---
        self.tabs = QTabWidget()
        self._build_tab_dashboard()
        self._build_tab_regions()
        self._build_tab_fishing()
        self._build_tab_colors()
        self._build_tab_automation()
        self._build_tab_profiles()
        body.addWidget(self.tabs, stretch=1)
        outer.addLayout(body, stretch=1)

        # --- Bottom: stats + log ---
        stats_row = QHBoxLayout()
        self.lbl_stats_session = QLabel()
        self.lbl_stats_total = QLabel()
        self.lbl_stats_rate = QLabel()
        self.lbl_stats_time = QLabel()
        for lbl in (self.lbl_stats_session, self.lbl_stats_total, self.lbl_stats_rate, self.lbl_stats_time):
            lbl.setStyleSheet("color: #4fc3f7; font-weight: bold; font-size: 11px;")
            stats_row.addWidget(lbl)
        stats_row.addStretch()
        outer.addLayout(stats_row)

        self.log_output = QTextEdit()
        self.log_output.setObjectName("logPanel")
        self.log_output.setFixedHeight(100)
        self.log_output.setReadOnly(True)
        outer.addWidget(self.log_output)

    def _scroll_tab(self, widget: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(widget)
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)
        return wrap

    def _build_tab_dashboard(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("statusPaused")
        lay.addWidget(self.lbl_status)

        self.grp_mode = QGroupBox()
        mode_lay = QVBoxLayout(self.grp_mode)
        self._tip_mode = InfoIcon("")
        mode_lay.addWidget(self._tip_mode)
        self.radio_full = QRadioButton()
        self.radio_semi = QRadioButton()
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_full)
        self.mode_group.addButton(self.radio_semi)
        if self.config.get("bot_mode") == "semi_auto":
            self.radio_semi.setChecked(True)
        else:
            self.radio_full.setChecked(True)
        self.radio_full.toggled.connect(self.update_bot_mode)
        self.radio_semi.toggled.connect(self.update_bot_mode)
        mode_lay.addWidget(self.radio_full)
        mode_lay.addWidget(self.radio_semi)
        lay.addWidget(self.grp_mode)

        self.btn_start = QPushButton()
        self.btn_start.setObjectName("btnPrimary")
        self.btn_start.setFixedHeight(40)
        lay.addWidget(self.btn_start)
        self.btn_overlay = QPushButton()
        self.btn_overlay.clicked.connect(self.toggle_overlay_mode)
        lay.addWidget(self.btn_overlay)
        lay.addStretch()
        self.tabs.addTab(self._scroll_tab(tab), "")

    def _build_tab_regions(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.grp_regions = QGroupBox()
        reg = QVBoxLayout(self.grp_regions)
        self._tip_regions = InfoIcon("")
        reg.addWidget(self._tip_regions)
        row = QHBoxLayout()
        self.btn_water = QPushButton()
        self.btn_water.clicked.connect(lambda: self.start_region_select("water_region"))
        self.btn_bar = QPushButton()
        self.btn_bar.clicked.connect(lambda: self.start_region_select("bar_region"))
        row.addWidget(self.btn_water)
        row.addWidget(self.btn_bar)
        reg.addLayout(row)
        cast_form = QFormLayout()
        self.spin_cast_power = QDoubleSpinBox()
        self.spin_cast_power.setRange(0.10, 2.00)
        self.spin_cast_power.setSingleStep(0.05)
        self.spin_cast_power.setValue(self.config.get("cast_power_time", 0.4))
        self.spin_cast_power.valueChanged.connect(self.update_cast_power_config)
        self.lbl_cast_hold = QLabel()
        cast_form.addRow(self.lbl_cast_hold, self.spin_cast_power)
        reg.addLayout(cast_form)
        self.chk_auto_cast = QCheckBox()
        self.chk_auto_cast.setChecked(self.config.get("auto_cast_power", False))
        self.chk_auto_cast.stateChanged.connect(self.update_cast_power_config)
        reg.addWidget(self.chk_auto_cast)
        lay.addWidget(self.grp_regions)

        self.grp_bar_px = QGroupBox()
        bar_form = QFormLayout(self.grp_bar_px)
        bar = self.config["bar_region"]
        self.spin_bar_left = QSpinBox()
        self.spin_bar_left.setRange(0, 3840)
        self.spin_bar_left.setValue(bar["left"])
        self.spin_bar_left.valueChanged.connect(self.update_manual_bar_region)
        self.spin_bar_top = QSpinBox()
        self.spin_bar_top.setRange(0, 2160)
        self.spin_bar_top.setValue(bar["top"])
        self.spin_bar_top.valueChanged.connect(self.update_manual_bar_region)
        self.spin_bar_width = QSpinBox()
        self.spin_bar_width.setRange(10, 2000)
        self.spin_bar_width.setValue(bar["width"])
        self.spin_bar_width.valueChanged.connect(self.update_manual_bar_region)
        self.spin_bar_height = QSpinBox()
        self.spin_bar_height.setRange(10, 2000)
        self.spin_bar_height.setValue(bar["height"])
        self.spin_bar_height.valueChanged.connect(self.update_manual_bar_region)
        self._lbl_bar_x, self._lbl_bar_y = QLabel(), QLabel()
        self._lbl_bar_w, self._lbl_bar_h = QLabel(), QLabel()
        bar_form.addRow(self._lbl_bar_x, self.spin_bar_left)
        bar_form.addRow(self._lbl_bar_y, self.spin_bar_top)
        bar_form.addRow(self._lbl_bar_w, self.spin_bar_width)
        bar_form.addRow(self._lbl_bar_h, self.spin_bar_height)
        lay.addWidget(self.grp_bar_px)
        lay.addStretch()
        self.tabs.addTab(self._scroll_tab(tab), "")

    def _build_tab_fishing(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.grp_bite = QGroupBox()
        bite_form = QFormLayout(self.grp_bite)
        bite_row = QHBoxLayout()
        self.slider_bite = QSlider(Qt.Orientation.Horizontal)
        self.slider_bite.setRange(1, 20)
        self.slider_bite.setValue(self.config.get("bite_sensitivity", 1))
        self.spin_bite = QSpinBox()
        self.spin_bite.setRange(1, 20)
        self.spin_bite.setValue(self.config.get("bite_sensitivity", 1))
        self.spin_bite.setFixedWidth(52)
        self.slider_bite.valueChanged.connect(self.spin_bite.setValue)
        self.spin_bite.valueChanged.connect(self.slider_bite.setValue)
        self.slider_bite.valueChanged.connect(self.update_bite_sensitivity)
        bite_row.addWidget(self.slider_bite)
        bite_row.addWidget(self.spin_bite)
        self._tip_bite = InfoIcon("")
        bite_row.addWidget(self._tip_bite)
        self.lbl_sensitivity = QLabel()
        bite_form.addRow(self.lbl_sensitivity, bite_row)
        lay.addWidget(self.grp_bite)

        self.grp_mg = QGroupBox()
        mg_form = QFormLayout(self.grp_mg)
        mg = self.config.get("minigame", {})
        self.spin_target_pct = QSpinBox()
        self.spin_target_pct.setRange(30, 70)
        self.spin_target_pct.setValue(mg.get("target_pct", 53))
        self.spin_target_pct.setSuffix(" %")
        self.spin_target_pct.valueChanged.connect(self.update_minigame_config)
        self.spin_danger_left = QSpinBox()
        self.spin_danger_left.setRange(5, 45)
        self.spin_danger_left.setValue(mg.get("danger_left_pct", 25))
        self.spin_danger_left.setSuffix(" %")
        self.spin_danger_left.valueChanged.connect(self.update_minigame_config)
        self.spin_danger_right = QSpinBox()
        self.spin_danger_right.setRange(55, 95)
        self.spin_danger_right.setValue(mg.get("danger_right_pct", 67))
        self.spin_danger_right.setSuffix(" %")
        self.spin_danger_right.valueChanged.connect(self.update_minigame_config)
        self._lbl_target, self._lbl_dleft, self._lbl_dright = QLabel(), QLabel(), QLabel()
        mg_form.addRow(self._lbl_target, self.spin_target_pct)
        mg_form.addRow(self._lbl_dleft, self.spin_danger_left)
        mg_form.addRow(self._lbl_dright, self.spin_danger_right)
        self._tip_minigame = InfoIcon("")
        mg_form.addRow("", self._tip_minigame)
        lay.addWidget(self.grp_mg)
        lay.addStretch()
        self.tabs.addTab(self._scroll_tab(tab), "")

    def _build_tab_colors(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.grp_hsv = QGroupBox()
        auto = QVBoxLayout(self.grp_hsv)
        form_tol = QFormLayout()
        ac = self.config.get("auto_hsv", {})
        self.spin_h_tol = QSpinBox()
        self.spin_h_tol.setRange(1, 90)
        self.spin_h_tol.setValue(ac.get("h_tol", 31))
        self.spin_h_tol.valueChanged.connect(self.update_auto_config)
        self.spin_s_tol = QSpinBox()
        self.spin_s_tol.setRange(5, 127)
        self.spin_s_tol.setValue(ac.get("s_tol", 70))
        self.spin_s_tol.valueChanged.connect(self.update_auto_config)
        self.spin_v_tol = QSpinBox()
        self.spin_v_tol.setRange(5, 127)
        self.spin_v_tol.setValue(ac.get("v_tol", 69))
        self.spin_v_tol.valueChanged.connect(self.update_auto_config)
        self._lbl_tol_h, self._lbl_tol_s, self._lbl_tol_v = QLabel(), QLabel(), QLabel()
        form_tol.addRow(self._lbl_tol_h, self.spin_h_tol)
        form_tol.addRow(self._lbl_tol_s, self.spin_s_tol)
        form_tol.addRow(self._lbl_tol_v, self.spin_v_tol)
        auto.addLayout(form_tol)
        pip_row = QHBoxLayout()
        self.lbl_pipette_target = QLabel()
        pip_row.addWidget(self.lbl_pipette_target)
        self.radio_pipette_float = QRadioButton()
        self.radio_pipette_zone = QRadioButton()
        self.radio_pipette_float.setChecked(True)
        pip_row.addWidget(self.radio_pipette_float)
        pip_row.addWidget(self.radio_pipette_zone)
        auto.addLayout(pip_row)
        adapt_row = QHBoxLayout()
        self.chk_adapt_float = QCheckBox()
        self.chk_adapt_float.setChecked(ac.get("adaptive_float", False))
        self.chk_adapt_float.stateChanged.connect(self.update_auto_config)
        self.chk_adapt_zone = QCheckBox()
        self.chk_adapt_zone.setChecked(ac.get("adaptive_zone", False))
        self.chk_adapt_zone.stateChanged.connect(self.update_auto_config)
        adapt_row.addWidget(self.chk_adapt_float)
        adapt_row.addWidget(self.chk_adapt_zone)
        auto.addLayout(adapt_row)
        lay.addWidget(self.grp_hsv)

        self.hsv_sub = QTabWidget()
        self._build_hsv_subtab_float()
        self._build_hsv_subtab_zone()
        lay.addWidget(self.hsv_sub)
        self.tabs.addTab(self._scroll_tab(tab), "")

    def _build_hsv_subtab_float(self):
        sub = QWidget()
        sl = QVBoxLayout(sub)
        self.mask_float_view = QLabel()
        self.mask_float_view.setFixedSize(200, 90)
        self.mask_float_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mask_float_view.setStyleSheet("border: 1px solid #ff5252; background: #000;")
        sl.addWidget(self.mask_float_view, alignment=Qt.AlignmentFlag.AlignCenter)
        form = QFormLayout()
        lf, uf = self.config["hsv"]["lower_float"], self.config["hsv"]["upper_float"]
        for label_key, val, attr in (
            ("h_min", lf[0], "fh_min"), ("s_min", lf[1], "fs_min"), ("v_min", lf[2], "fv_min"),
            ("h_max", uf[0], "fh_max"), ("s_max", uf[1], "fs_max"), ("v_max", uf[2], "fv_max"),
        ):
            mx = 179 if label_key.startswith("h") else 255
            row, sld, _sp = self.create_hsv_control(0, mx, val, self.update_hsv_float)
            form.addRow(QLabel(), row)
            setattr(self, f"s_{attr}", sld)
        sl.addLayout(form)
        self.hsv_sub.addTab(sub, "")

    def _build_hsv_subtab_zone(self):
        sub = QWidget()
        sl = QVBoxLayout(sub)
        self.mask_zone_view = QLabel()
        self.mask_zone_view.setFixedSize(200, 90)
        self.mask_zone_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mask_zone_view.setStyleSheet("border: 1px solid #69f0ae; background: #000;")
        sl.addWidget(self.mask_zone_view, alignment=Qt.AlignmentFlag.AlignCenter)
        form = QFormLayout()
        lz, uz = self.config["hsv"]["lower_zone"], self.config["hsv"]["upper_zone"]
        for label_key, val, attr in (
            ("h_min", lz[0], "zh_min"), ("s_min", lz[1], "zs_min"), ("v_min", lz[2], "zv_min"),
            ("h_max", uz[0], "zh_max"), ("s_max", uz[1], "zs_max"), ("v_max", uz[2], "zv_max"),
        ):
            mx = 179 if label_key.startswith("h") else 255
            row, sld, _sp = self.create_hsv_control(0, mx, val, self.update_hsv_zone)
            form.addRow(QLabel(), row)
            setattr(self, f"s_{attr}", sld)
        sl.addLayout(form)
        self.hsv_sub.addTab(sub, "")

    def _build_tab_automation(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.grp_hum = QGroupBox()
        hum = QFormLayout(self.grp_hum)
        self.chk_humanize = QCheckBox()
        hum_cfg = self.config.get("humanize", {})
        self.chk_humanize.setChecked(hum_cfg.get("enabled", False))
        self.chk_humanize.stateChanged.connect(self.update_ops_config)
        hum.addRow(self.chk_humanize)
        self.spin_cast_min = QDoubleSpinBox()
        self.spin_cast_min.setRange(0.0, 10.0)
        self.spin_cast_min.setValue(hum_cfg.get("cast_delay_min", 4.5))
        self.spin_cast_min.valueChanged.connect(self.update_ops_config)
        self.spin_cast_max = QDoubleSpinBox()
        self.spin_cast_max.setRange(0.0, 10.0)
        self.spin_cast_max.setValue(hum_cfg.get("cast_delay_max", 6.0))
        self.spin_cast_max.valueChanged.connect(self.update_ops_config)
        self._lbl_cast_min, self._lbl_cast_max = QLabel(), QLabel()
        hum.addRow(self._lbl_cast_min, self.spin_cast_min)
        hum.addRow(self._lbl_cast_max, self.spin_cast_max)
        self._tip_humanize = InfoIcon("")
        hum.addRow("", self._tip_humanize)
        lay.addWidget(self.grp_hum)

        self.grp_wd = QGroupBox()
        wd = QFormLayout(self.grp_wd)
        wd_cfg = self.config.get("watchdog", {})
        self.chk_wd = QCheckBox()
        self.chk_wd.setChecked(wd_cfg.get("enabled", False))
        self.chk_wd.stateChanged.connect(self.update_ops_config)
        self.spin_wd_timeout = QSpinBox()
        self.spin_wd_timeout.setRange(10, 300)
        self.spin_wd_timeout.setValue(wd_cfg.get("timeout_seconds", 45))
        self.spin_wd_timeout.valueChanged.connect(self.update_ops_config)
        self._lbl_wd_timeout = QLabel()
        wd.addRow(self.chk_wd)
        wd.addRow(self._lbl_wd_timeout, self.spin_wd_timeout)
        lay.addWidget(self.grp_wd)

        self.grp_bait = QGroupBox()
        bait = QFormLayout(self.grp_bait)
        bait_cfg = self.config.get("auto_bait", {})
        self.chk_bait = QCheckBox()
        self.chk_bait.setChecked(bait_cfg.get("enabled", False))
        self.chk_bait.stateChanged.connect(self.update_ops_config)
        self.combo_bait_key = QComboBox()
        self._fill_hotkey_combo(self.combo_bait_key, bait_cfg.get("hotkey", "1"))
        self.combo_bait_key.currentIndexChanged.connect(self.update_ops_config)
        self.spin_bait_every = QSpinBox()
        self.spin_bait_every.setRange(1, 999)
        self.spin_bait_every.setValue(bait_cfg.get("every_n_catches", 12))
        self.spin_bait_every.valueChanged.connect(self.update_ops_config)
        self._lbl_bait_key, self._lbl_bait_every = QLabel(), QLabel()
        bait.addRow(self.chk_bait)
        bait.addRow(self._lbl_bait_key, self.combo_bait_key)
        bait.addRow(self._lbl_bait_every, self.spin_bait_every)
        self._tip_bait = InfoIcon("")
        bait.addRow("", self._tip_bait)
        lay.addWidget(self.grp_bait)

        self.grp_food = QGroupBox()
        food = QFormLayout(self.grp_food)
        food_cfg = self.config.get("auto_food", {})
        self.chk_food = QCheckBox()
        self.chk_food.setChecked(food_cfg.get("enabled", False))
        self.chk_food.stateChanged.connect(self.update_ops_config)
        self.combo_food_key = QComboBox()
        self._fill_hotkey_combo(self.combo_food_key, food_cfg.get("hotkey", "2"))
        self.combo_food_key.currentIndexChanged.connect(self.update_ops_config)
        self.spin_food_minutes = QSpinBox()
        self.spin_food_minutes.setRange(1, 240)
        self.spin_food_minutes.setValue(int(food_cfg.get("interval_minutes", 30)))
        self.spin_food_minutes.valueChanged.connect(self.update_ops_config)
        self._lbl_food_key, self._lbl_food_iv = QLabel(), QLabel()
        food.addRow(self.chk_food)
        food.addRow(self._lbl_food_key, self.combo_food_key)
        food.addRow(self._lbl_food_iv, self.spin_food_minutes)
        self._tip_food = InfoIcon("")
        food.addRow("", self._tip_food)
        lay.addWidget(self.grp_food)
        lay.addStretch()
        self.tabs.addTab(self._scroll_tab(tab), "")

    def _build_tab_profiles(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.grp_prof = QGroupBox()
        prof = QVBoxLayout(self.grp_prof)
        row = QHBoxLayout()
        self.lbl_active_prof = QLabel()
        self._tip_profile = InfoIcon("")
        row.addWidget(self.lbl_active_prof)
        row.addWidget(self._tip_profile)
        row.addStretch()
        self.combo_profile = QComboBox()
        row.addWidget(self.combo_profile, stretch=1)
        prof.addLayout(row)
        btn_row = QHBoxLayout()
        self.btn_save_profile = QPushButton()
        self.btn_save_profile.setObjectName("btnPrimary")
        self.btn_save_profile.clicked.connect(self.on_save_profile)
        self.btn_new_profile = QPushButton()
        self.btn_new_profile.clicked.connect(self.on_new_profile)
        self.btn_delete_profile = QPushButton()
        self.btn_delete_profile.setObjectName("btnDanger")
        self.btn_delete_profile.clicked.connect(self.on_delete_profile)
        self.btn_load_profile = QPushButton()
        self.btn_load_profile.setObjectName("btnGhost")
        self.btn_load_profile.clicked.connect(self.on_load_profile)
        self.btn_reset_factory = QPushButton()
        self.btn_reset_factory.setObjectName("btnGhost")
        self.btn_reset_factory.clicked.connect(self.on_reset_factory)
        for b in (
            self.btn_save_profile, self.btn_new_profile, self.btn_delete_profile,
            self.btn_load_profile, self.btn_reset_factory,
        ):
            btn_row.addWidget(b)
        prof.addLayout(btn_row)
        self.lbl_dirty = QLabel()
        self.lbl_dirty.setObjectName("dirtyBanner")
        self.lbl_dirty.setWordWrap(True)
        prof.addWidget(self.lbl_dirty)
        lay.addWidget(self.grp_prof)
        lay.addStretch()
        self.tabs.addTab(tab, "")

    # ---------------------------------------------------------------- i18n
    def apply_translations(self):
        self.setWindowTitle(self.tr("window_title"))
        self.lbl_lang.setText(self.tr("language"))
        tab_keys = ("tab_dashboard", "tab_regions", "tab_fishing", "tab_colors", "tab_automation", "tab_profiles")
        for i, key in enumerate(tab_keys):
            self.tabs.setTabText(i, self.tr(key))

        tips = ("tip_water", "tip_bar")
        titles = ("water_zone", "bar_zone")
        for i, ((title_lbl, tip_w, attr), tk, tipk) in enumerate(zip(self._preview_heads, titles, tips)):
            title_lbl.setText(self.tr(tk))
            tip_w.setToolTip(self.tr(tipk))
            getattr(self, attr).setText(self.tr("loading"))

        self.lbl_status.setText(self.tr(f"status_{self._status_key}"))
        self.grp_mode.setTitle(self.tr("bot_mode_group"))
        self._tip_mode.setToolTip(self.tr("tip_mode"))
        self.radio_full.setText(self.tr("mode_full"))
        self.radio_semi.setText(self.tr("mode_semi"))
        self.btn_start.setText(self.tr("btn_start"))
        self.btn_overlay.setText(self.tr("btn_overlay"))

        self.grp_regions.setTitle(self.tr("regions_group"))
        self._tip_regions.setToolTip(self.tr("tip_regions"))
        self.btn_water.setText(self.tr("btn_water"))
        self.btn_bar.setText(self.tr("btn_bar"))
        self.lbl_cast_hold.setText(self.tr("cast_hold"))
        self.spin_cast_power.setSuffix(self.tr("sec_suffix"))
        self.chk_auto_cast.setText(self.tr("auto_cast_power"))
        self.grp_bar_px.setTitle(self.tr("bar_pixels_group"))
        self._lbl_bar_x.setText(self.tr("bar_x"))
        self._lbl_bar_y.setText(self.tr("bar_y"))
        self._lbl_bar_w.setText(self.tr("bar_w"))
        self._lbl_bar_h.setText(self.tr("bar_h"))

        self.grp_bite.setTitle(self.tr("bite_group"))
        self.lbl_sensitivity.setText(self.tr("sensitivity"))
        self._tip_bite.setToolTip(self.tr("tip_bite"))
        self.grp_mg.setTitle(self.tr("minigame_group"))
        self._lbl_target.setText(self.tr("target_pct"))
        self._lbl_dleft.setText(self.tr("danger_left"))
        self._lbl_dright.setText(self.tr("danger_right"))
        self._tip_minigame.setToolTip(self.tr("tip_minigame"))

        self.grp_hsv.setTitle(self.tr("hsv_group"))
        self._lbl_tol_h.setText(self.tr("tol_h"))
        self._lbl_tol_s.setText(self.tr("tol_s"))
        self._lbl_tol_v.setText(self.tr("tol_v"))
        self.lbl_pipette_target.setText(self.tr("pipette_target"))
        self.radio_pipette_float.setText(self.tr("bobber"))
        self.radio_pipette_zone.setText(self.tr("green_bar"))
        self.chk_adapt_float.setText(self.tr("adapt_bobber"))
        self.chk_adapt_zone.setText(self.tr("adapt_bar"))
        self.hsv_sub.setTabText(0, self.tr("bobber"))
        self.hsv_sub.setTabText(1, self.tr("green_bar"))
        self.mask_float_view.setText(self.tr("mask_bobber"))
        self.mask_zone_view.setText(self.tr("mask_bar"))

        self.grp_hum.setTitle(self.tr("humanize_group"))
        self.chk_humanize.setText(self.tr("humanize_enable"))
        self._lbl_cast_min.setText(self.tr("cast_delay_min"))
        self._lbl_cast_max.setText(self.tr("cast_delay_max"))
        self._tip_humanize.setToolTip(self.tr("tip_humanize"))
        self.grp_wd.setTitle(self.tr("watchdog_group"))
        self.chk_wd.setText(self.tr("watchdog_enable"))
        self._lbl_wd_timeout.setText(self.tr("watchdog_timeout"))
        self.grp_bait.setTitle(self.tr("bait_group"))
        self.chk_bait.setText(self.tr("bait_enable"))
        self._lbl_bait_key.setText(self.tr("bait_key"))
        self._lbl_bait_every.setText(self.tr("bait_every"))
        self._tip_bait.setToolTip(self.tr("tip_bait"))
        self.grp_food.setTitle(self.tr("food_group"))
        self.chk_food.setText(self.tr("food_enable"))
        self._lbl_food_key.setText(self.tr("food_key"))
        self._lbl_food_iv.setText(self.tr("food_interval"))
        self.spin_food_minutes.setSuffix(self.tr("min_suffix"))
        self._tip_food.setToolTip(self.tr("tip_food"))

        self.grp_prof.setTitle(self.tr("profile_group"))
        self.lbl_active_prof.setText(self.tr("active_profile"))
        self._tip_profile.setToolTip(self.tr("tip_profile"))
        self.btn_save_profile.setText(self.tr("save_profile"))
        self.btn_new_profile.setText(self.tr("new_profile"))
        self.btn_delete_profile.setText(self.tr("delete_profile"))
        self.btn_load_profile.setText(self.tr("load_profile"))
        self.btn_reset_factory.setText(self.tr("reset_factory"))
        self.log_output.setPlaceholderText(self.tr("log_placeholder"))
        self._refresh_profile_combo()
        self._update_dirty_banner()
        self.update_stats_ui({"session_catches": 0, "total_catches": 0, "catches_per_hour": 0.0, "session_elapsed": "0m"})

    def on_language_changed(self, _idx=None):
        if self._loading_ui:
            return
        lang = self.combo_lang.currentData() or DEFAULT_LANGUAGE
        if lang == self.i18n.lang:
            return
        self.i18n.set_language(lang)
        save_language(lang)
        self.apply_translations()

    # ---------------------------------------------------------------- helpers
    def _fill_hotkey_combo(self, combo: QComboBox, current: str):
        combo.blockSignals(True)
        combo.clear()
        keys = [str(i) for i in range(1, 10)] + ["0"] + [chr(c) for c in range(ord("q"), ord("z") + 1)]
        for k in keys:
            combo.addItem(k.upper(), k)
        idx = combo.findData(str(current).lower())
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def create_hsv_control(self, min_val, max_val, default_val, callback):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(default_val)
        spinbox = QSpinBox()
        spinbox.setRange(min_val, max_val)
        spinbox.setValue(default_val)
        spinbox.setFixedWidth(58)
        slider.valueChanged.connect(spinbox.setValue)
        spinbox.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(callback)
        layout.addWidget(slider)
        layout.addWidget(spinbox)
        return layout, slider, spinbox

    def _mark_dirty(self):
        if self._loading_ui:
            return
        self._session_dirty = True
        self._update_dirty_banner()

    def _update_dirty_banner(self):
        if self._session_dirty:
            self.lbl_dirty.setText(self.tr("dirty_banner"))
            self.lbl_dirty.show()
        else:
            self.lbl_dirty.hide()

    def _refresh_profile_combo(self):
        self.combo_profile.blockSignals(True)
        cur = self.combo_profile.currentData()
        self.combo_profile.clear()
        self.combo_profile.addItem(self.tr("factory_default"), self.PROFILE_FACTORY)
        for name in list_profiles():
            self.combo_profile.addItem(name, name)
        idx = self.combo_profile.findData(self._active_saved_profile or cur)
        if idx >= 0:
            self.combo_profile.setCurrentIndex(idx)
        self.combo_profile.blockSignals(False)

    def _apply_config_dict(self, new_cfg: dict):
        self._loading_ui = True
        self.config.clear()
        self.config.update(copy.deepcopy(new_cfg))
        self.sync_all_ui_from_config()
        self._loading_ui = False
        self._session_dirty = False
        self._update_dirty_banner()
        self.worker.food_manager.reset_timer()

    def sync_all_ui_from_config(self):
        self._loading_ui = True
        self.radio_full.setChecked(self.config.get("bot_mode", "full_auto") != "semi_auto")
        self.slider_bite.setValue(self.config.get("bite_sensitivity", 1))
        self.spin_cast_power.setValue(self.config.get("cast_power_time", 0.4))
        self.chk_auto_cast.setChecked(self.config.get("auto_cast_power", False))
        mg = self.config.get("minigame", {})
        self.spin_target_pct.setValue(mg.get("target_pct", 53))
        self.spin_danger_left.setValue(mg.get("danger_left_pct", 25))
        self.spin_danger_right.setValue(mg.get("danger_right_pct", 67))
        bar = self.config["bar_region"]
        self.spin_bar_left.setValue(bar["left"])
        self.spin_bar_top.setValue(bar["top"])
        self.spin_bar_width.setValue(bar["width"])
        self.spin_bar_height.setValue(bar["height"])
        ac = self.config.get("auto_hsv", {})
        self.spin_h_tol.setValue(ac.get("h_tol", 31))
        self.spin_s_tol.setValue(ac.get("s_tol", 70))
        self.spin_v_tol.setValue(ac.get("v_tol", 69))
        self.chk_adapt_float.setChecked(ac.get("adaptive_float", False))
        self.chk_adapt_zone.setChecked(ac.get("adaptive_zone", False))
        self.sync_hsv_ui_from_config()
        hum = self.config.get("humanize", {})
        self.chk_humanize.setChecked(hum.get("enabled", False))
        self.spin_cast_min.setValue(hum.get("cast_delay_min", 4.5))
        self.spin_cast_max.setValue(hum.get("cast_delay_max", 6.0))
        wd = self.config.get("watchdog", {})
        self.chk_wd.setChecked(wd.get("enabled", False))
        self.spin_wd_timeout.setValue(wd.get("timeout_seconds", 45))
        bait = self.config.get("auto_bait", {})
        self.chk_bait.setChecked(bait.get("enabled", False))
        self._fill_hotkey_combo(self.combo_bait_key, bait.get("hotkey", "1"))
        self.spin_bait_every.setValue(bait.get("every_n_catches", 12))
        food = self.config.get("auto_food", {})
        self.chk_food.setChecked(food.get("enabled", False))
        self._fill_hotkey_combo(self.combo_food_key, food.get("hotkey", "2"))
        self.spin_food_minutes.setValue(int(food.get("interval_minutes", 30)))
        self._loading_ui = False

    # ---------------------------------------------------------------- profiles
    def on_save_profile(self):
        data = self.combo_profile.currentData()
        if data == self.PROFILE_FACTORY:
            name, ok = QInputDialog.getText(self, self.tr("dlg_save_profile"), self.tr("dlg_new_profile_name"))
            if not ok or not name.strip():
                return
            name = name.strip()
        else:
            name = data
        try:
            save_profile(name, self.config)
            self._active_saved_profile = name
            self._session_dirty = False
            self._refresh_profile_combo()
            self._update_dirty_banner()
            self.log(self.tr("log_profile_saved", name=name))
        except ValueError as e:
            QMessageBox.warning(self, self.tr("dlg_profile_title"), str(e))

    def on_new_profile(self):
        name, ok = QInputDialog.getText(self, self.tr("dlg_new_profile"), self.tr("dlg_profile_name"))
        if not ok or not name.strip():
            return
        try:
            save_profile(name.strip(), self.config)
            self._active_saved_profile = name.strip()
            self._session_dirty = False
            self._refresh_profile_combo()
            self.log(self.tr("log_profile_created", name=name.strip()))
        except ValueError as e:
            QMessageBox.warning(self, self.tr("dlg_profile_title"), str(e))

    def on_delete_profile(self):
        data = self.combo_profile.currentData()
        if data == self.PROFILE_FACTORY:
            QMessageBox.information(self, self.tr("dlg_profile_title"), self.tr("factory_no_delete"))
            return
        reply = QMessageBox.question(
            self, self.tr("dlg_delete_title"), self.tr("dlg_delete_msg", name=data),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        delete_profile(data)
        if self._active_saved_profile == data:
            self._active_saved_profile = None
        self._refresh_profile_combo()
        self.log(self.tr("log_profile_deleted", name=data))

    def on_load_profile(self):
        data = self.combo_profile.currentData()
        if data == self.PROFILE_FACTORY:
            self._apply_config_dict(reset_to_factory_default())
            self.log(self.tr("log_factory_loaded"))
        else:
            try:
                self._apply_config_dict(load_profile(data))
                self.log(self.tr("log_profile_loaded", name=data))
            except FileNotFoundError:
                QMessageBox.warning(self, self.tr("dlg_profile_title"), self.tr("profile_not_found"))

    def on_reset_factory(self):
        reply = QMessageBox.question(
            self, self.tr("dlg_reset_title"), self.tr("dlg_reset_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._apply_config_dict(reset_to_factory_default())
            self.log(self.tr("log_factory_reset"))

    # ---------------------------------------------------------------- config handlers
    def update_bot_mode(self):
        self.config["bot_mode"] = "semi_auto" if self.radio_semi.isChecked() else "full_auto"
        self._mark_dirty()
        self.log(self.tr("log_mode_updated"))

    def update_bite_sensitivity(self, value):
        self.config["bite_sensitivity"] = value
        self._mark_dirty()

    def update_cast_power_config(self):
        self.config["cast_power_time"] = self.spin_cast_power.value()
        self.config["auto_cast_power"] = self.chk_auto_cast.isChecked()
        self._mark_dirty()

    def update_minigame_config(self):
        self.config["minigame"] = {
            "target_pct": self.spin_target_pct.value(),
            "danger_left_pct": self.spin_danger_left.value(),
            "danger_right_pct": self.spin_danger_right.value(),
        }
        self._mark_dirty()

    def update_manual_bar_region(self):
        self.config["bar_region"] = {
            "left": self.spin_bar_left.value(),
            "top": self.spin_bar_top.value(),
            "width": self.spin_bar_width.value(),
            "height": self.spin_bar_height.value(),
        }
        self._mark_dirty()

    def update_auto_config(self):
        self.config["auto_hsv"] = {
            "h_tol": self.spin_h_tol.value(),
            "s_tol": self.spin_s_tol.value(),
            "v_tol": self.spin_v_tol.value(),
            "adaptive_float": self.chk_adapt_float.isChecked(),
            "adaptive_zone": self.chk_adapt_zone.isChecked(),
        }
        self._mark_dirty()

    def update_hsv_float(self):
        self.config["hsv"]["lower_float"] = [self.s_fh_min.value(), self.s_fs_min.value(), self.s_fv_min.value()]
        self.config["hsv"]["upper_float"] = [self.s_fh_max.value(), self.s_fs_max.value(), self.s_fv_max.value()]
        self._mark_dirty()

    def update_hsv_zone(self):
        self.config["hsv"]["lower_zone"] = [self.s_zh_min.value(), self.s_zs_min.value(), self.s_zv_min.value()]
        self.config["hsv"]["upper_zone"] = [self.s_zh_max.value(), self.s_zs_max.value(), self.s_zv_max.value()]
        self._mark_dirty()

    def update_ops_config(self):
        self.config["humanize"] = {
            **self.config.get("humanize", {}),
            "enabled": self.chk_humanize.isChecked(),
            "cast_delay_min": self.spin_cast_min.value(),
            "cast_delay_max": self.spin_cast_max.value(),
        }
        self.config["watchdog"] = {"enabled": self.chk_wd.isChecked(), "timeout_seconds": self.spin_wd_timeout.value()}
        self.config["auto_bait"] = {
            **self.config.get("auto_bait", {}),
            "enabled": self.chk_bait.isChecked(),
            "hotkey": self.combo_bait_key.currentData(),
            "every_n_catches": self.spin_bait_every.value(),
        }
        self.config["auto_food"] = {
            "enabled": self.chk_food.isChecked(),
            "hotkey": self.combo_food_key.currentData(),
            "interval_minutes": self.spin_food_minutes.value(),
        }
        self._mark_dirty()
        if hasattr(self, "worker"):
            self.worker.food_manager.reset_timer()

    def sync_hsv_ui_from_config(self):
        lf, uf = self.config["hsv"]["lower_float"], self.config["hsv"]["upper_float"]
        lz, uz = self.config["hsv"]["lower_zone"], self.config["hsv"]["upper_zone"]
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

    def handle_pipette_click(self, source_viewport, x, y):
        frame = self.viewport_water.last_frame if source_viewport == "water" else self.viewport_bar.last_frame
        if frame is None:
            return
        y1, y2 = max(0, y - 1), min(frame.shape[0], y + 2)
        x1, x2 = max(0, x - 1), min(frame.shape[1], x + 2)
        crop_hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
        h, s, v = [int(x) for x in cv2.mean(crop_hsv)[:3]]
        h_tol, s_tol, v_tol = self.spin_h_tol.value(), self.spin_s_tol.value(), self.spin_v_tol.value()
        lower = [max(0, h - h_tol), max(0, s - s_tol), max(0, v - v_tol)]
        upper = [min(179, h + h_tol), min(255, s + s_tol), min(255, v + v_tol)]
        if self.radio_pipette_float.isChecked():
            self.config["hsv"]["lower_float"], self.config["hsv"]["upper_float"] = lower, upper
            target = self.tr("target_bobber")
        else:
            self.config["hsv"]["lower_zone"], self.config["hsv"]["upper_zone"] = lower, upper
            target = self.tr("target_bar")
        self.sync_hsv_ui_from_config()
        self._mark_dirty()
        self.log(self.tr("log_pipette", target=target, h=h, s=s, v=v))

    # ---------------------------------------------------------------- runtime
    def log(self, text):
        self.log_output.append(text)

    def update_status(self, key: str):
        self._status_key = key
        self.lbl_status.setText(self.tr(f"status_{key}"))
        active = key in ("ready", "casting", "fishing", "minigame", "semi_wait")
        self.lbl_status.setObjectName("statusActive" if active else "statusPaused")
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)

    def update_stats_ui(self, stats: dict):
        self.lbl_stats_session.setText(f"{self.tr('stats_session')}: {stats.get('session_catches', 0)}")
        self.lbl_stats_total.setText(f"{self.tr('stats_total')}: {stats.get('total_catches', 0)}")
        self.lbl_stats_rate.setText(f"{stats.get('catches_per_hour', 0.0)} {self.tr('stats_rate')}")
        self.lbl_stats_time.setText(stats.get("session_elapsed", "0m"))

    def update_water_viewport(self, frame):
        self.viewport_water.update_frame(frame)

    def update_bar_viewport(self, frame):
        self.viewport_bar.update_frame(frame)

    def update_mask_float(self, mask):
        h, w = mask.shape
        qt_img = QImage(mask.data, w, h, w, QImage.Format.Format_Grayscale8)
        self.mask_float_view.setPixmap(
            QPixmap.fromImage(qt_img).scaled(
                self.mask_float_view.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def update_mask_zone(self, mask):
        h, w = mask.shape
        qt_img = QImage(mask.data, w, h, w, QImage.Format.Format_Grayscale8)
        self.mask_zone_view.setPixmap(
            QPixmap.fromImage(qt_img).scaled(
                self.mask_zone_view.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def toggle_overlay_mode(self):
        self.is_overlay = not self.is_overlay
        if self.is_overlay:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
            self.setWindowOpacity(0.75)
            self.log(self.tr("overlay_on"))
        else:
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
            self.setWindowOpacity(1.0)
            self.log(self.tr("overlay_off"))
        self.show()

    def start_region_select(self, region_key):
        self.hide()
        self.selector = RegionSelector()
        self.selector.region_selected.connect(lambda rect: self.finish_region_select(region_key, rect))
        self.selector.selection_cancelled.connect(self.cancel_region_select)
        self.selector.show()

    def finish_region_select(self, region_key, rect):
        self.config[region_key] = rect
        self.sync_all_ui_from_config()
        self._mark_dirty()
        self.log(self.tr("log_region_updated", key=region_key, rect=rect))
        self.show()

    def cancel_region_select(self):
        self.show()

    def closeEvent(self, event):
        if hasattr(self, "worker"):
            self.worker.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    apply_app_theme(app)
    gui = BotGUI()
    gui.show()
    sys.exit(app.exec())
