import time
import ctypes
import math
import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from vision import Vision
from input_handler import InputHandler

try:
    ctypes.windll.winmm.timeBeginPeriod(1)
except Exception:
    pass


class BotWorker(QThread):
    water_frame_ready = pyqtSignal(np.ndarray)
    bar_frame_ready = pyqtSignal(np.ndarray)
    mask_float_ready = pyqtSignal(np.ndarray)
    mask_zone_ready = pyqtSignal(np.ndarray)
    log_ready = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    hsv_updated = pyqtSignal()

    STATE_PAUSED = -1
    STATE_CASTING = 0
    STATE_FISHING = 1
    STATE_MINIGAME = 2
    STATE_SEMI_WAITING = 3

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.vision = Vision()
        self.running = True
        self.current_state = self.STATE_PAUSED
        self._cast_phase = None      # None | 'hold' | 'wait'
        self._cast_start = 0.0
        self._audio_bite_triggered = False  # Flag dari AudioDetector

    def toggle_active(self):
        if self.current_state == self.STATE_PAUSED:
            self._cast_phase = None
            bot_mode = self.config.get("bot_mode", "full_auto_visual")
            if bot_mode == "semi_auto":
                self.current_state = self.STATE_SEMI_WAITING
                self.status_changed.emit("SEMI-AUTO (Menunggu Mini-Game)")
                self.log_ready.emit("[⚡ MULAI] Mode Semi-Auto: menunggu mini-game...")
            else:
                self.current_state = self.STATE_CASTING
                self.status_changed.emit("AKTIF (Melempar)")
                self.log_ready.emit("[⚡ MULAI] Bot dijalankan!")
        else:
            self._cast_phase = None
            self.current_state = self.STATE_PAUSED
            InputHandler.hold_mouse_end()
            self.status_changed.emit("JEDA")
            self.log_ready.emit("[💤 JEDA] Bot dihentikan!")

    def on_audio_bite_detected(self):
        """Slot dipanggil oleh AudioDetector saat suara gigitan terdeteksi."""
        bot_mode = self.config.get("bot_mode", "full_auto_visual")
        if self.current_state == self.STATE_FISHING and bot_mode == "full_auto_audio":
            self._audio_bite_triggered = True

    def adapt_hsv_range(self, hsv_crop, current_lower, current_upper):
        mean_hsv = cv2.mean(hsv_crop)[:3]
        mean_s, mean_v = mean_hsv[1], mean_hsv[2]

        s_tol = self.config.get("auto_hsv", {}).get("s_tol", 60)
        v_tol = self.config.get("auto_hsv", {}).get("v_tol", 60)

        new_s_min = max(0, int(mean_s - s_tol))
        new_s_max = min(255, int(mean_s + s_tol))
        new_v_min = max(0, int(mean_v - v_tol))
        new_v_max = min(255, int(mean_v + v_tol))

        lower = np.copy(current_lower)
        upper = np.copy(current_upper)

        lower[1] = int(0.85 * lower[1] + 0.15 * new_s_min)
        upper[1] = int(0.85 * upper[1] + 0.15 * new_s_max)
        lower[2] = int(0.85 * lower[2] + 0.15 * new_v_min)
        upper[2] = int(0.85 * upper[2] + 0.15 * new_v_max)

        return lower, upper

    def _emit_both_previews(self, water_region, bar_region, lower_float, upper_float,
                             lower_zone, upper_zone, water_label="", bar_label="",
                             water_overlays=None):
        """Capture dan emit kedua viewport + mask dalam satu panggilan."""
        water_frame = self.vision.capture_screen(water_region)
        bar_frame = self.vision.capture_screen(bar_region)

        hsv_water = cv2.cvtColor(water_frame, cv2.COLOR_BGR2HSV)
        mask_float = cv2.inRange(hsv_water, lower_float, upper_float)
        self.mask_float_ready.emit(mask_float)

        hsv_bar = cv2.cvtColor(bar_frame, cv2.COLOR_BGR2HSV)
        mask_zone = cv2.inRange(hsv_bar, lower_zone, upper_zone)
        self.mask_zone_ready.emit(mask_zone)

        if water_overlays:
            for fn in water_overlays:
                fn(water_frame)
        if water_label:
            cv2.putText(water_frame, water_label, (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        if bar_label:
            cv2.putText(bar_frame, bar_label, (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        self.water_frame_ready.emit(water_frame)
        self.bar_frame_ready.emit(bar_frame)
        return water_frame, bar_frame

    def run(self):
        is_float_tracked = False
        lost_frames_counter = 0
        minigame_lost_frames = 0
        fishing_start_time = time.time()

        ui_frame_counter = 0
        current_lmb_state = False
        last_ui_update = 0.0
        UI_INTERVAL = 0.033  # ~30 FPS untuk UI

        while self.running:
            water_region = self.config["water_region"]
            bar_region = self.config["bar_region"]
            cast_power_time = self.config.get("cast_power_time", 0.55)
            auto_cast_power = self.config.get("auto_cast_power", True)
            hsv_cfg = self.config["hsv"]
            auto_cfg = self.config.get("auto_hsv", {})
            mg_cfg = self.config.get("minigame", {"target_pct": 58, "danger_left_pct": 25, "danger_right_pct": 75})

            lower_float = np.array(hsv_cfg["lower_float"])
            upper_float = np.array(hsv_cfg["upper_float"])
            lower_zone = np.array(hsv_cfg["lower_zone"])
            upper_zone = np.array(hsv_cfg["upper_zone"])

            cast_cfg = self.config.get("cast_point", {})
            if cast_cfg.get("use_custom", False) and cast_cfg.get("x", 0) > 0:
                water_center_x = cast_cfg["x"]
                water_center_y = cast_cfg["y"]
            else:
                water_center_x = water_region["left"] + water_region["width"] // 2
                water_center_y = water_region["top"] + water_region["height"] // 2

            # 📏 АВТО-РАСЧЕТ СИЛЫ (ВРЕМЕНИ ЗАЖАТИЯ ЛКМ) ПО РАССРОЯНИЮ
            if auto_cast_power:
                # В Albion персонаж находится примерно в нижней центральной части зоны воды
                player_base_x = water_region["left"] + water_region["width"] // 2
                player_base_y = water_region["top"] + water_region["height"] + 50

                dist_px = math.hypot(water_center_x - player_base_x, water_center_y - player_base_y)
                # Динамическая интерполяция: от 0.22с (под ноги) до 1.05с (на максимум)
                max_expected_dist = max(300.0, float(water_region["height"] + water_region["width"] // 2))
                calc_time = 0.20 + (dist_px / max_expected_dist) * 0.75
                cast_power_time = round(max(0.18, min(1.15, calc_time)), 2)

            ui_frame_counter += 1
            now = time.time()
            should_update_ui = (now - last_ui_update >= UI_INTERVAL)

            # === STATUS: JEDA ===
            if self.current_state == self.STATE_PAUSED:
                self._emit_both_previews(
                    water_region, bar_region, lower_float, upper_float,
                    lower_zone, upper_zone, "PAUSED", "PAUSED")
                last_ui_update = now
                self.msleep(33)
                continue

            # === STATUS 0: LEMPAR KAIL (NON-BLOCKING) ===
            elif self.current_state == self.STATE_CASTING:
                # Inisialisasi fase casting
                if self._cast_phase is None:
                    self._cast_phase = 'hold'
                    self._cast_start = time.time()
                    InputHandler.hold_mouse_start(water_center_x, water_center_y)
                    current_lmb_state = True
                    self.log_ready.emit(
                        f"[ACTION] Melempar ({cast_power_time}s) ke titik ({water_center_x}, {water_center_y})...")

                cast_elapsed = time.time() - self._cast_start

                if self._cast_phase == 'hold' and cast_elapsed >= cast_power_time:
                    InputHandler.hold_mouse_end()
                    current_lmb_state = False
                    self._cast_phase = 'wait'
                    self._cast_start = time.time()
                    self.log_ready.emit("[ACTION] Menunggu pelampung jatuh...")

                elif self._cast_phase == 'wait' and cast_elapsed >= 2.2:
                    self._cast_phase = None
                    is_float_tracked = False
                    lost_frames_counter = 0
                    fishing_start_time = time.time()
                    self.current_state = self.STATE_FISHING
                    self.status_changed.emit("MEMANTAU PELAMPUNG")

                # Preview tetap live selama casting
                if should_update_ui and self.current_state == self.STATE_CASTING:
                    phase_text = "CASTING..." if self._cast_phase == 'hold' else "WAITING..."
                    self._emit_both_previews(
                        water_region, bar_region, lower_float, upper_float,
                        lower_zone, upper_zone, phase_text, phase_text)
                    last_ui_update = now

                self.msleep(33)

            # === STATUS 1: MEMANTAU PELAMPUNG ===
            elif self.current_state == self.STATE_FISHING:
                water_frame = self.vision.capture_screen(water_region)
                center, bbox = self.vision.find_color_object(water_frame, lower_float, upper_float, is_float=True)

                elapsed_time = time.time() - fishing_start_time

                if not is_float_tracked and elapsed_time > 4.0:
                    self.log_ready.emit("[⚠️ TIMEOUT] Pelampung tidak terdeteksi setelah lempar! Melempar ulang...")
                    self._cast_phase = None
                    self.current_state = self.STATE_CASTING
                    self.status_changed.emit("MELEMPAR")
                    continue

                if elapsed_time > 25.0:
                    self.log_ready.emit("[⚠️ TIMEOUT] Waktu menunggu gigitan habis (25d)! Melempar ulang...")
                    self._cast_phase = None
                    self.current_state = self.STATE_CASTING
                    self.status_changed.emit("MELEMPAR")
                    continue

                bot_mode = self.config.get("bot_mode", "full_auto_visual")

                # Cek trigger visual
                if bot_mode == "full_auto_visual":
                    if center and bbox:
                        lost_frames_counter = 0
                        if not is_float_tracked:
                            self.log_ready.emit("[FISHING] Pelampung ditemukan, memantau...")
                        is_float_tracked = True

                        if auto_cfg.get("adaptive_float", False):
                            x, y, w, h = bbox
                            hsv_water = cv2.cvtColor(water_frame, cv2.COLOR_BGR2HSV)
                            crop = hsv_water[y:y + h, x:x + w]
                            if crop.size > 0:
                                n_low, n_up = self.adapt_hsv_range(crop, lower_float, upper_float)
                                self.config["hsv"]["lower_float"] = n_low.tolist()
                                self.config["hsv"]["upper_float"] = n_up.tolist()
                                if ui_frame_counter % 30 == 0:
                                    self.hsv_updated.emit()
                    else:
                        if is_float_tracked:
                            lost_frames_counter += 1
                            if lost_frames_counter >= self.config.get("bite_sensitivity", 3):
                                self.log_ready.emit("[🔥 TRIGGER] GIGITAN (Visual)! Menarik ikan!")
                                InputHandler.click_mouse(water_center_x, water_center_y)

                                is_float_tracked = False
                                lost_frames_counter = 0
                                minigame_lost_frames = 0
                                self.current_state = self.STATE_MINIGAME
                                self.status_changed.emit("MINI-GAME")

                # Cek trigger audio
                if bot_mode == "full_auto_audio":
                    if self._audio_bite_triggered:
                        self._audio_bite_triggered = False
                        self.log_ready.emit("[🔊 TRIGGER] GIGITAN (Audio)! Menarik ikan!")
                        InputHandler.click_mouse(water_center_x, water_center_y)
                        is_float_tracked = False
                        lost_frames_counter = 0
                        minigame_lost_frames = 0
                        self.current_state = self.STATE_MINIGAME
                        self.status_changed.emit("MINI-GAME")

                # Update kedua viewport secara time-based
                if should_update_ui:
                    last_ui_update = now

                    # Water viewport dengan overlay deteksi
                    hsv_water = cv2.cvtColor(water_frame, cv2.COLOR_BGR2HSV)
                    mask_float = cv2.inRange(hsv_water, lower_float, upper_float)
                    self.mask_float_ready.emit(mask_float)

                    if center and bbox:
                        x, y, w, h = bbox
                        cv2.rectangle(water_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                        cv2.circle(water_frame, center, 4, (0, 0, 255), -1)
                    cv2.putText(water_frame, f"FISHING... ({int(elapsed_time)}s)", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    self.water_frame_ready.emit(water_frame)

                    # Bar viewport (live preview)
                    bar_frame = self.vision.capture_screen(bar_region)
                    hsv_bar = cv2.cvtColor(bar_frame, cv2.COLOR_BGR2HSV)
                    mask_zone = cv2.inRange(hsv_bar, lower_zone, upper_zone)
                    self.mask_zone_ready.emit(mask_zone)
                    cv2.putText(bar_frame, "STANDBY", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 100), 2)
                    self.bar_frame_ready.emit(bar_frame)

                self.msleep(1)

            # === STATUS 2: MINI-GAME ===
            elif self.current_state == self.STATE_MINIGAME:
                bar_frame = self.vision.capture_screen(bar_region)
                hsv_bar = cv2.cvtColor(bar_frame, cv2.COLOR_BGR2HSV)
                mask_zone = cv2.inRange(hsv_bar, lower_zone, upper_zone)

                kernel = np.ones((5, 21), np.uint8)
                mask_zone_closed = cv2.morphologyEx(mask_zone, cv2.MORPH_CLOSE, kernel)

                contours_zone, _ = cv2.findContours(mask_zone_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                zx, zy, zw, zh = 0, 0, 0, 0
                is_valid_bar = False

                if contours_zone:
                    for cnt in sorted(contours_zone, key=cv2.contourArea, reverse=True):
                        area = cv2.contourArea(cnt)
                        x, y, w, h = cv2.boundingRect(cnt)

                        if h > 0 and w >= 180 and h >= 12:
                            aspect_ratio = float(w) / h
                            if 4.5 <= aspect_ratio <= 14.0:
                                zx, zy, zw, zh = x, y, w, h
                                is_valid_bar = True
                                break

                if is_valid_bar:
                    minigame_lost_frames = 0

                    if auto_cfg.get("adaptive_zone", False):
                        crop = hsv_bar[zy:zy + zh, zx:zx + zw]
                        if crop.size > 0:
                            n_low, n_up = self.adapt_hsv_range(crop, lower_zone, upper_zone)
                            self.config["hsv"]["lower_zone"] = n_low.tolist()
                            self.config["hsv"]["upper_zone"] = n_up.tolist()
                            if ui_frame_counter % 30 == 0:
                                self.hsv_updated.emit()

                    float_x = None
                    if zw > 0:
                        x_start = max(0, zx - 50)
                        x_end = min(bar_region["width"], zx + zw + 50)

                        zone_roi_mask = mask_zone[:, x_start:x_end]
                        mask_inv_roi = cv2.bitwise_not(zone_roi_mask)

                        contours_inv, _ = cv2.findContours(mask_inv_roi, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

                        for cnt in contours_inv:
                            area = cv2.contourArea(cnt)
                            if 8 < area < 350:
                                fx, fy, fw, fh = cv2.boundingRect(cnt)
                                if zy - 10 <= fy <= zy + zh + 10:
                                    float_x = x_start + fx + fw // 2
                                    break

                    t_pct = mg_cfg.get("target_pct", 58) / 100.0
                    l_pct = mg_cfg.get("danger_left_pct", 25) / 100.0
                    r_pct = mg_cfg.get("danger_right_pct", 75) / 100.0

                    target_x = zx + int(zw * t_pct)
                    danger_left_bound = zx + int(zw * l_pct)
                    danger_right_bound = zx + int(zw * r_pct)

                    if float_x is not None and zw > 0:
                        if float_x < danger_left_bound:
                            if not current_lmb_state:
                                InputHandler.hold_mouse_start()
                                current_lmb_state = True
                        elif float_x > danger_right_bound:
                            if current_lmb_state:
                                InputHandler.hold_mouse_end()
                                current_lmb_state = False
                        else:
                            if float_x < target_x - 3:
                                if not current_lmb_state:
                                    InputHandler.hold_mouse_start()
                                    current_lmb_state = True
                            elif float_x > target_x + 3:
                                if current_lmb_state:
                                    InputHandler.hold_mouse_end()
                                    current_lmb_state = False

                    elif zw > 0:
                        if not current_lmb_state:
                            InputHandler.hold_mouse_start()
                            current_lmb_state = True

                    if should_update_ui and zw > 0:
                        cv2.rectangle(bar_frame, (zx, zy), (zx + zw, zy + zh), (0, 255, 0), 2)
                        target_draw_x = zx + int(zw * t_pct)
                        cv2.line(bar_frame, (target_draw_x, zy), (target_draw_x, zy + zh), (255, 255, 0), 2)

                        if float_x is not None:
                            cv2.circle(bar_frame, (float_x, zy + zh // 2), 5, (0, 0, 255), -1)

                else:
                    minigame_lost_frames += 1
                    if minigame_lost_frames >= 80:
                        self.log_ready.emit("[✔ SYSTEM] Ikan berhasil ditarik!")
                        if current_lmb_state:
                            InputHandler.hold_mouse_end()
                            current_lmb_state = False

                        self._cast_phase = None
                        self._mg_done_start = time.time()
                        # Kembali ke mode yang sesuai
                        bot_mode = self.config.get("bot_mode", "full_auto_visual")
                        if bot_mode == "semi_auto":
                            self.current_state = self.STATE_SEMI_WAITING
                            self.status_changed.emit("SEMI-AUTO (Menunggu Mini-Game)")
                        else:
                            self.current_state = self.STATE_CASTING
                            self.status_changed.emit("MELEMPAR")

                # Update kedua viewport secara time-based
                if should_update_ui:
                    last_ui_update = now
                    self.mask_zone_ready.emit(mask_zone)
                    cv2.putText(bar_frame, "MINIGAME...", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                    self.bar_frame_ready.emit(bar_frame)

                    # Water viewport (live preview)
                    water_frame = self.vision.capture_screen(water_region)
                    hsv_water = cv2.cvtColor(water_frame, cv2.COLOR_BGR2HSV)
                    mask_float = cv2.inRange(hsv_water, lower_float, upper_float)
                    self.mask_float_ready.emit(mask_float)
                    cv2.putText(water_frame, "MINI-GAME...", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                    self.water_frame_ready.emit(water_frame)

                self.msleep(0)

            # === STATUS 3: SEMI-AUTO (Menunggu Mini-Game) ===
            elif self.current_state == self.STATE_SEMI_WAITING:
                bar_frame = self.vision.capture_screen(bar_region)
                hsv_bar = cv2.cvtColor(bar_frame, cv2.COLOR_BGR2HSV)
                mask_zone = cv2.inRange(hsv_bar, lower_zone, upper_zone)

                # Cek apakah bar mini-game muncul
                kernel = np.ones((5, 21), np.uint8)
                mask_closed = cv2.morphologyEx(mask_zone, cv2.MORPH_CLOSE, kernel)
                contours, _ = cv2.findContours(mask_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                bar_found = False
                if contours:
                    for cnt in sorted(contours, key=cv2.contourArea, reverse=True):
                        x, y, w, h = cv2.boundingRect(cnt)
                        if h > 0 and w >= 180 and h >= 12:
                            aspect_ratio = float(w) / h
                            if 4.5 <= aspect_ratio <= 14.0:
                                bar_found = True
                                break

                if bar_found:
                    self.log_ready.emit("[🎮 SEMI-AUTO] Bar mini-game terdeteksi! Memulai otomatis...")
                    minigame_lost_frames = 0
                    self.current_state = self.STATE_MINIGAME
                    self.status_changed.emit("MINI-GAME")
                    continue

                # Update kedua viewport
                if should_update_ui:
                    last_ui_update = now
                    self.mask_zone_ready.emit(mask_zone)
                    cv2.putText(bar_frame, "SEMI-AUTO: WAITING...", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2)
                    self.bar_frame_ready.emit(bar_frame)

                    water_frame = self.vision.capture_screen(water_region)
                    hsv_water = cv2.cvtColor(water_frame, cv2.COLOR_BGR2HSV)
                    mask_float = cv2.inRange(hsv_water, lower_float, upper_float)
                    self.mask_float_ready.emit(mask_float)
                    cv2.putText(water_frame, "SEMI-AUTO: WAITING...", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2)
                    self.water_frame_ready.emit(water_frame)

                self.msleep(33)

    def stop(self):
        self.running = False
        InputHandler.hold_mouse_end()
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        self.wait()