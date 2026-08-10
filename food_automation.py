import time

from input_control import InputHandler


class FoodManager:
    def __init__(self, config, log_fn=None):
        self.config = config
        self._log = log_fn or (lambda _msg: None)
        self._last_eat = time.time()

    def _cfg(self):
        default = {"enabled": False, "hotkey": "2", "interval_minutes": 30}
        return {**default, **self.config.get("auto_food", {})}

    def reset_timer(self):
        self._last_eat = time.time()

    def tick(self):
        cfg = self._cfg()
        if not cfg.get("enabled"):
            return
        minutes = max(1, int(cfg.get("interval_minutes", 30)))
        interval_sec = minutes * 60
        if time.time() - self._last_eat < interval_sec:
            return
        self._last_eat = time.time()
        hotkey = str(cfg.get("hotkey", "2"))
        self._log(f"[FOOD] Eating (key '{hotkey}') every {minutes} min.")
        InputHandler.press_key(hotkey)
        time.sleep(0.6)
