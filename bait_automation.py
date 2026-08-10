import time

from input_control import InputHandler


class BaitManager:
    def __init__(self, config, log_fn=None):
        self.config = config
        self._log = log_fn or (lambda msg: None)
        self._catch_counter = 0

    def _cfg(self):
        return self.config.get(
            "auto_bait",
            {
                "enabled": False,
                "hotkey": "1",
                "every_n_catches": 10,
                "equip_from_inventory": False,
                "inventory_slot": {"x": 0, "y": 0},
            },
        )

    def is_enabled(self):
        return self._cfg().get("enabled", False)

    def on_catch(self):
        if not self.is_enabled():
            return False
        cfg = self._cfg()
        every_n = cfg.get("every_n_catches", cfg.get("cast_count", 10))
        self._catch_counter += 1
        if self._catch_counter < every_n:
            return False
        self._catch_counter = 0
        self.apply_bait()
        return True

    def apply_bait(self):
        cfg = self._cfg()
        hotkey = cfg.get("hotkey", "1")
        self._log(f"[BAIT] Using bait (key '{hotkey}')...")
        InputHandler.press_key(hotkey)
        time.sleep(0.8)
        if cfg.get("equip_from_inventory", False):
            slot = cfg.get("inventory_slot", {})
            sx, sy = slot.get("x", 0), slot.get("y", 0)
            if sx > 0 and sy > 0:
                self._log("[BAIT] Equip from inventory...")
                InputHandler.press_key("i")
                time.sleep(0.4)
                InputHandler.click_mouse(sx, sy, delay=0.05)
                time.sleep(0.3)
                InputHandler.press_key("i")
                time.sleep(0.3)

    def reset(self):
        self._catch_counter = 0
