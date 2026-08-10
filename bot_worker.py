import time
import random
import ctypes
import math
import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from vision import Vision
from input_handler import InputHandler
from bait_manager import BaitManager
from food_manager import FoodManager
from stats_tracker import StatsTracker

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
    stats_updated = pyqtSignal(dict)   # {session_catches, total_catches, session_elapsed, catches_per_hour}
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
        self._tracked_float_pos = None
        self._splash_baseline_frame = None
        self._last_cast_x = 0
        self._last_cast_y = 0

        # --- Modul operasional ---
        self.bait_manager = BaitManager(config, log_fn=lambda msg: self.log_ready.emit(msg))
        self.food_manager = FoodManager(config, log_fn=lambda msg: self.log_ready.emit(msg))
        self.stats = StatsTracker()
        self._last_activity = time.time()
        self._stats_emit_counter = 0

    def toggle_active(self):
        if self.current_state == self.STATE_PAUSED:
            self._cast_phase = None
            self._last_activity = time.time()
            bot_mode = self.config.get("bot_mode", "full_auto")
            if bot_mode == "semi_auto":
                self.current_state = self.STATE_SEMI_WAITING
                self.status_changed.emit("semi_wait")
                self.log_ready.emit("[Start] Assist mode: waiting for mini-game...")
            else:
                self.current_state = self.STATE_CASTING
                self.status_changed.emit("ready")
                self.log_ready.emit("[Start] Bot ready — auto cast, watch, and mini-game.")
            self.stats_updated.emit(self.stats.summary())
            self.food_manager.reset_timer()
        else:
            self._cast_phase = None
            self.current_state = self.STATE_PAUSED
            InputHandler.hold_mouse_end()
            self.status_changed.emit("paused")
            self.log_ready.emit("[Pause] Bot stopped.")

    def _trigger_bite(self, source: str, water_center_x: int, water_center_y: int):
        # Humanize: bite delay
        humanize = self.config.get("humanize", {})
        if humanize.get("enabled", False):
            bite_delay_max = humanize.get("bite_delay_max_ms", 450)
            if bite_delay_max > 0:
                delay = random.randint(0, bite_delay_max) / 1000.0
                if delay > 0:
                    time.sleep(delay)
                    self.log_ready.emit(f"[🎭 HUMANIZE] Bite delay: {int(delay*1000)}ms")

        self.log_ready.emit(f"[🔥 TRIGGER] GIGITAN ({source})! Menarik ikan!")
        InputHandler.click_mouse(water_center_x, water_center_y)
        self._last_activity = time.time()
        return True

    def _on_catch_success(self):
        """Dipanggil setelah minigame selesai (ikan berhasil ditarik)."""
        self.stats.record_catch()
        self._stats_emit_counter += 1
        self.stats_updated.emit(self.stats.summary())

        # BaitManager: check & apply bait jika waktunya
        did_bait = self.bait_manager.on_catch()
        if did_bait:
            time.sleep(0.5)  # Tunggu setelah apply bait sebelum recast

        self._last_activity = time.time()

    def _get_cast_point(self, fallback_x: int, fallback_y: int):
        """Titik lempar = pusat zona air (+ jitter humanize opsional)."""
        humanize = self.config.get("humanize", {})
        x, y = fallback_x, fallback_y
        if humanize.get("enabled", False):
            jitter = humanize.get("coordinate_jitter_px", 0)
            if jitter > 0:
                x += random.randint(-jitter, jitter)
                y += random.randint(-jitter, jitter)
        return x, y

    def _humanize_cast_delay(self):
        """Terapkan delay acak sebelum recast."""
        humanize = self.config.get("humanize", {})
        if not humanize.get("enabled", False):
            return
        delay_min = humanize.get("cast_delay_min", 4.5)
        delay_max = humanize.get("cast_delay_max", 6.0)
        delay = random.uniform(delay_min, delay_max)
        self.log_ready.emit(f"[🎭 HUMANIZE] Delay recast: {delay:.1f}s")
        # Sleep in chunks agar thread tetap responsif
        end_time = time.time() + delay
        while time.time() < end_time and self.running and self.current_state != self.STATE_PAUSED:
            self.msleep(100)

    def _humanize_cast_power(self, base_power: float) -> float:
        """Terapkan variasi acak pada cast power."""
        humanize = self.config.get("humanize", {})
        if not humanize.get("enabled", False):
            return base_power
        variance_pct = humanize.get("cast_power_variance_pct", 5)
        if variance_pct <= 0:
            return base_power
        variance = base_power * (variance_pct / 100.0)
        result = base_power + random.uniform(-variance, variance)
        return round(max(0.18, min(1.15, result)), 2)

    def _check_watchdog(self):
        """Cek watchdog timeout — recast jika idle terlalu lama."""
        wd = self.config.get("watchdog", {})
        if not wd.get("enabled", False):
            return False
        timeout = wd.get("timeout_seconds", 45)
        idle = time.time() - self._last_activity
        if idle > timeout:
            self.log_ready.emit(f"[⏰ WATCHDOG] Idle {int(idle)}s > timeout {timeout}s — force recast!")
            return True
        return False

    def adapt_hsv_range(self, hsv_crop, current_lower, current_upper, mask=None):
        if mask is not None and cv2.countNonZero(mask) > 0:
            mean_val, std_val = cv2.meanStdDev(hsv_crop, mask=mask)
            mean_s, std_s = mean_val[1][0], std_val[1][0]
            mean_v, std_v = mean_val[2][0], std_val[2][0]
            
            # 2.5 std_dev membungkus ~98% variasi warna yang ada pada objek, memastikan akurasi mutlak
            s_tol = max(20, int(2.5 * std_s)) # minimal 20 agar tidak terlalu sensitif noise
            v_tol = max(20, int(2.5 * std_v))
        else:
            mean_val = cv2.mean(hsv_crop)[:3]
            mean_s, mean_v = mean_val[1], mean_val[2]
            
            s_tol = self.config.get("auto_hsv", {}).get("s_tol", 60)
            v_tol = self.config.get("auto_hsv", {}).get("v_tol", 60)

        new_s_min = max(0, int(mean_s - s_tol))
        new_s_max = min(255, int(mean_s + s_tol))
        new_v_min = max(0, int(mean_v - v_tol))
        new_v_max = min(255, int(mean_v + v_tol))

        lower = np.copy(current_lower)
        upper = np.copy(current_upper)

        # Update lebih cepat dengan moving average (60% old, 40% new)
        lower[1] = int(0.6 * lower[1] + 0.4 * new_s_min)
        upper[1] = int(0.6 * upper[1] + 0.4 * new_s_max)
        lower[2] = int(0.6 * lower[2] + 0.4 * new_v_min)
        upper[2] = int(0.6 * upper[2] + 0.4 * new_v_max)

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

    def _transition_to_casting(self, after_catch: bool = False):
        """Transisi ke STATE_CASTING dengan humanize delay opsional."""
        if after_catch:
            self._on_catch_success()
            self._humanize_cast_delay()
            # Re-check apakah masih running setelah delay
            if not self.running or self.current_state == self.STATE_PAUSED:
                return

        self._cast_phase = None
        bot_mode = self.config.get("bot_mode", "full_auto")
        if bot_mode == "semi_auto":
            self.current_state = self.STATE_SEMI_WAITING
            self.status_changed.emit("semi_wait")
        else:
            self.current_state = self.STATE_CASTING
            self.status_changed.emit("casting")

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

            base_x = water_region["left"] + water_region["width"] // 2
            base_y = water_region["top"] + water_region["height"] // 2
            water_center_x, water_center_y = self._get_cast_point(base_x, base_y)

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

            # Humanize: variance cast power
            cast_power_time = self._humanize_cast_power(cast_power_time)

            ui_frame_counter += 1
            now = time.time()
            should_update_ui = (now - last_ui_update >= UI_INTERVAL)

            if self.current_state != self.STATE_PAUSED and ui_frame_counter % 150 == 0:
                self.stats_updated.emit(self.stats.summary())

            if self.current_state != self.STATE_PAUSED:
                self.food_manager.tick()

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
                    self._last_cast_x = water_center_x
                    self._last_cast_y = water_center_y
                    InputHandler.hold_mouse_start(water_center_x, water_center_y)
                    current_lmb_state = True
                    self.log_ready.emit(
                        f"[Lempar] Menahan klik {cast_power_time}s ke tengah zona air "
                        f"({water_center_x}, {water_center_y})..."
                    )
                    self._last_activity = time.time()

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
                    self._tracked_float_pos = None
                    self._splash_baseline_frame = None
                    lost_frames_counter = 0
                    fishing_start_time = time.time()
                    self._last_activity = time.time()
                    self.current_state = self.STATE_FISHING
                    self.status_changed.emit("fishing")

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
                
                center = None
                bbox = None
                
                elapsed_time = time.time() - fishing_start_time
                
                if self._tracked_float_pos is not None:
                    # ROI Tracking Focus (Spotlight Overlay)
                    tx, ty = self._tracked_float_pos
                    window_size = 40  # 80x80 pixels window
                    rx1 = max(0, tx - window_size)
                    ry1 = max(0, ty - window_size)
                    rx2 = min(water_frame.shape[1], tx + window_size)
                    ry2 = min(water_frame.shape[0], ty + window_size)
                    
                    # Buat warna latar gelap yang menutupi seluruh zona air (seperti zona bar)
                    spotlight_frame = np.full_like(water_frame, (0, 40, 0)) # Hijau gelap (BGR)
                    
                    # Buat lubang transparan yang menampilkan pelampung
                    spotlight_frame[ry1:ry2, rx1:rx2] = water_frame[ry1:ry2, rx1:rx2]
                    
                    # Beri garis batas hijau terang agar fokus terlihat jelas
                    cv2.rectangle(spotlight_frame, (rx1, ry1), (rx2, ry2), (0, 255, 0), 2)
                    
                    # Gunakan spotlight_frame untuk deteksi dan GUI
                    water_frame = spotlight_frame
                    
                    # === R&D: Splash Frame Differencing ===
                    spotlight_crop = water_frame[ry1:ry2, rx1:rx2]
                    gray_crop = cv2.cvtColor(spotlight_crop, cv2.COLOR_BGR2GRAY)
                    
                    if elapsed_time > 1.5:
                        if self._splash_baseline_frame is None:
                            # Ambil Snapshot saat pelampung tenang (selesai grace period)
                            self._splash_baseline_frame = gray_crop.copy()
                        else:
                            # Bandingkan dengan snapshot
                            diff = cv2.absdiff(self._splash_baseline_frame, gray_crop)
                            _, thresh = cv2.threshold(diff, 35, 255, cv2.THRESH_BINARY)
                            changed_pixels = cv2.countNonZero(thresh)
                            
                            # Adaptasikan baseline secara perlahan (0.95 vs 0.05) untuk menormalisasi riak ombak lambat
                            cv2.addWeighted(self._splash_baseline_frame, 0.95, gray_crop, 0.05, 0, self._splash_baseline_frame)
                            
                            if changed_pixels > 250: # Trigger ledakan cipratan air (Threshold 250 pixels)
                                self.log_ready.emit(f"[VISUAL] CIPRATAN TERDETEKSI! ({changed_pixels} px berubah)")
                                self._trigger_bite("Splash", water_center_x, water_center_y)
                                self._splash_baseline_frame = None
                                self._tracked_float_pos = None
                                is_float_tracked = False
                                lost_frames_counter = 0
                                minigame_lost_frames = 0
                                self.current_state = self.STATE_MINIGAME
                                self.status_changed.emit("minigame")
                                continue
                    # =======================================
                    
                    # Cari pelampung (hanya akan mendeteksi di dalam lubang)
                    center, bbox = self.vision.find_color_object(water_frame, lower_float, upper_float, is_float=True)
                    
                    if center and self._tracked_float_pos is not None:
                        cx, cy = center
                        tx, ty = self._tracked_float_pos
                        
                        # Grace period: 1.5 detik pertama, pelampung masih menyesuaikan diri di air (mengikuti cipratan)
                        if elapsed_time < 1.5:
                            self._tracked_float_pos = center
                        else:
                            # Deteksi pergerakan fisik drastis ke bawah (ikan menarik pelampung)
                            if (cy - ty) > 12:
                                self.log_ready.emit("[VISUAL] Pelampung tertarik ke bawah! (Physical Dip)")
                                center = None  # Paksa bot menganggap pelampung hilang
                                lost_frames_counter = 999  # Paksa trigger gigitan secara instan
                else:
                    # Pencarian awal di seluruh frame
                    center, bbox = self.vision.find_color_object(water_frame, lower_float, upper_float, is_float=True)
                    if center:
                        self._tracked_float_pos = center  # Kunci posisi secara statis!

                if not is_float_tracked and elapsed_time > 4.0:
                    self.log_ready.emit("[⚠️ TIMEOUT] Pelampung tidak terdeteksi setelah lempar! Melempar ulang...")
                    self._cast_phase = None
                    self._last_activity = time.time()
                    self.current_state = self.STATE_CASTING
                    self.status_changed.emit("casting")
                    continue

                if elapsed_time > 25.0:
                    self.log_ready.emit("[⚠️ TIMEOUT] Waktu menunggu gigitan habis (25d)! Melempar ulang...")
                    self._cast_phase = None
                    self._last_activity = time.time()
                    self.current_state = self.STATE_CASTING
                    self.status_changed.emit("casting")
                    continue

                # Watchdog check
                if self._check_watchdog():
                    self._cast_phase = None
                    self._last_activity = time.time()
                    self.current_state = self.STATE_CASTING
                    self.status_changed.emit("casting")
                    continue

                bot_mode = self.config.get("bot_mode", "full_auto")

                if bot_mode == "full_auto":
                    if center and bbox:
                        lost_frames_counter = 0
                        if not is_float_tracked:
                            self.log_ready.emit("[Pantau] Pelampung ketemu — menunggu tarikan ikan...")
                        is_float_tracked = True
                        self._last_activity = time.time()

                        if auto_cfg.get("adaptive_float", False):
                            x, y, w, h = bbox
                            hsv_water = cv2.cvtColor(water_frame, cv2.COLOR_BGR2HSV)
                            crop = hsv_water[y:y + h, x:x + w]
                            if crop.size > 0:
                                crop_mask = cv2.inRange(crop, lower_float, upper_float)
                                if cv2.countNonZero(crop_mask) > 0:
                                    n_low, n_up = self.adapt_hsv_range(crop, lower_float, upper_float, mask=crop_mask)
                                    self.config["hsv"]["lower_float"] = n_low.tolist()
                                    self.config["hsv"]["upper_float"] = n_up.tolist()
                                    if ui_frame_counter % 5 == 0:
                                        self.hsv_updated.emit()
                    else:
                        if is_float_tracked:
                            lost_frames_counter += 1
                            target_frames = max(self.config.get("bite_sensitivity", 3), 4)
                            if lost_frames_counter >= target_frames:
                                if elapsed_time > 1.5:
                                    self._trigger_bite("Visual", water_center_x, water_center_y)
                                    is_float_tracked = False
                                    lost_frames_counter = 0
                                    minigame_lost_frames = 0
                                    self.current_state = self.STATE_MINIGAME
                                    self.status_changed.emit("minigame")

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

                self.msleep(15)

            # === STATUS 2: MINI-GAME ===
            elif self.current_state == self.STATE_MINIGAME:
                # Watchdog check juga di minigame
                if self._check_watchdog():
                    if current_lmb_state:
                        InputHandler.hold_mouse_end()
                        current_lmb_state = False
                    self._cast_phase = None
                    self._last_activity = time.time()
                    self.current_state = self.STATE_CASTING
                    self.status_changed.emit("casting")
                    continue

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
                    self._last_activity = time.time()

                    if auto_cfg.get("adaptive_zone", False):
                        crop = hsv_bar[zy:zy + zh, zx:zx + zw]
                        if crop.size > 0:
                            crop_mask = mask_zone[zy:zy + zh, zx:zx + zw]
                            if cv2.countNonZero(crop_mask) > 0:
                                n_low, n_up = self.adapt_hsv_range(crop, lower_zone, upper_zone, mask=crop_mask)
                                self.config["hsv"]["lower_zone"] = n_low.tolist()
                                self.config["hsv"]["upper_zone"] = n_up.tolist()
                                if ui_frame_counter % 5 == 0:
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
                    # Jika bar hijau hilang (minigame sukses/gagal), LANGSUNG lepaskan klik
                    # agar tidak menahan klik yang menyebabkan karakter tidak sengaja melempar pancingan.
                    if current_lmb_state:
                        InputHandler.hold_mouse_end()
                        current_lmb_state = False
                        
                    minigame_lost_frames += 1
                    if minigame_lost_frames >= 80:
                        self.log_ready.emit("[SYSTEM] Minigame selesai (Ikan ditarik / Lepas).")
                        self._transition_to_casting(after_catch=True)
                        continue

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

                self.msleep(15)

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
                    self.status_changed.emit("minigame")
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

