import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
import time

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False


class AudioDetector(QThread):
    """Deteksi gigitan ikan melalui audio (VB-CABLE / perangkat audio lainnya)."""

    bite_detected = pyqtSignal()        # Emit saat gigitan terdeteksi
    level_updated = pyqtSignal(float)   # Emit level audio (0.0 - 1.0) untuk visualisasi

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = False
        self._last_trigger_time = 0.0
        self._current_level = 0.0
        self._consecutive_peaks = 0

    @staticmethod
    def is_available():
        """Cek apakah library sounddevice tersedia."""
        return SOUNDDEVICE_AVAILABLE

    @staticmethod
    def list_devices():
        """Daftar semua perangkat audio input yang tersedia."""
        if not SOUNDDEVICE_AVAILABLE:
            return []
        devices = []
        try:
            all_devs = sd.query_devices()
            for i, dev in enumerate(all_devs):
                if dev['max_input_channels'] > 0:
                    devices.append({
                        'index': i,
                        'name': dev['name'],
                        'channels': dev['max_input_channels'],
                        'samplerate': dev['default_samplerate']
                    })
        except Exception:
            pass
        return devices

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback yang dipanggil oleh sounddevice setiap chunk audio."""
        if not self.running:
            return

        # Hitung peak amplitude
        peak = np.max(np.abs(indata))
        self._current_level = float(peak)

        audio_cfg = self.config.get("audio", {})
        threshold = audio_cfg.get("threshold", 0.15)
        cooldown = audio_cfg.get("cooldown", 3.0)
        sensitivity = audio_cfg.get("sensitivity", 2) # jumlah chunk berturut-turut

        now = time.time()

        if peak > threshold:
            self._consecutive_peaks += 1
        else:
            self._consecutive_peaks = 0

        if self._consecutive_peaks >= sensitivity and (now - self._last_trigger_time) > cooldown:
            self._last_trigger_time = now
            self._consecutive_peaks = 0
            self.bite_detected.emit()

    def run(self):
        """Main loop: buka audio stream dan monitor level."""
        if not SOUNDDEVICE_AVAILABLE:
            return

        audio_cfg = self.config.get("audio", {})
        device_index = audio_cfg.get("device_index", -1)

        device = device_index if device_index >= 0 else None

        self.running = True
        self._last_trigger_time = 0.0
        self._consecutive_peaks = 0

        try:
            with sd.InputStream(
                device=device,
                channels=1,
                callback=self._audio_callback,
                samplerate=44100,
                blocksize=2048
            ):
                while self.running:
                    self.level_updated.emit(self._current_level)
                    self.msleep(50)  # Update UI ~20 FPS
        except Exception as e:
            self.level_updated.emit(0.0)
            print(f"[AUDIO ERROR] {e}")

    def stop(self):
        """Hentikan monitoring audio."""
        self.running = False
        self.wait(2000)
