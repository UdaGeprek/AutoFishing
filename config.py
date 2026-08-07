import json
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "water_region": {"top": 220, "left": 500, "width": 900, "height": 400},
    "bar_region": {"top": 830, "left": 597, "width": 250, "height": 30},
    "cast_power_time": 0.55,
    "auto_cast_power": True,
    "cast_point": {"x": 0, "y": 0, "use_custom": False},
    "bot_mode": "full_auto_visual",
    "bite_sensitivity": 3,
    "hsv": {
        "lower_float": [0, 100, 100],
        "upper_float": [10, 255, 255],
        "lower_zone": [35, 100, 100],
        "upper_zone": [85, 255, 255]
    },
    "auto_hsv": {
        "h_tol": 12,
        "s_tol": 60,
        "v_tol": 60,
        "adaptive_float": False,
        "adaptive_zone": False
    },
    "minigame": {
        "target_pct": 56,
        "danger_left_pct": 25,
        "danger_right_pct": 70
    },
    "audio": {
        "enabled": False,
        "device_index": -1,
        "threshold": 0.15,
        "cooldown": 3.0,
        "sensitivity": 2
    }
}

_MIGRATE_KEYS = [
    ("auto_hsv", DEFAULT_CONFIG["auto_hsv"]),
    ("minigame", DEFAULT_CONFIG["minigame"]),
    ("cast_point", DEFAULT_CONFIG["cast_point"]),
    ("auto_cast_power", DEFAULT_CONFIG["auto_cast_power"]),
    ("bot_mode", DEFAULT_CONFIG["bot_mode"]),
    ("bite_sensitivity", DEFAULT_CONFIG["bite_sensitivity"]),
    ("audio", DEFAULT_CONFIG["audio"]),
]

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                for key, default in _MIGRATE_KEYS:
                    if key not in cfg:
                        cfg[key] = default
                return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(config_data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f, indent=4)