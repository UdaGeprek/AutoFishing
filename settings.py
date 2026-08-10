import copy
import json
import os
import re
PROFILES_DIR = 'profiles'
META_FILE = os.path.join(PROFILES_DIR, '_meta.json')
DEFAULT_CONFIG = {'water_region': {'top': 230, 'left': 791, 'width': 106, 'height': 100}, 'bar_region': {'left': 832, 'top': 538, 'width': 250, 'height': 29}, 'cast_power_time': 0.4, 'auto_cast_power': False, 'bot_mode': 'full_auto', 'bite_sensitivity': 1, 'hsv': {'lower_float': [19, 24, 36], 'upper_float': [142, 149, 177], 'lower_zone': [46, 84, 106], 'upper_zone': [67, 247, 193]}, 'auto_hsv': {'h_tol': 31, 's_tol': 70, 'v_tol': 69, 'adaptive_float': False, 'adaptive_zone': False}, 'minigame': {'target_pct': 53, 'danger_left_pct': 25, 'danger_right_pct': 67}, 'auto_bait': {'enabled': False, 'hotkey': '1', 'every_n_catches': 12, 'equip_from_inventory': False, 'inventory_slot': {'x': 0, 'y': 0}}, 'auto_food': {'enabled': False, 'hotkey': '2', 'interval_minutes': 30}, 'humanize': {'enabled': False, 'cast_delay_min': 4.5, 'cast_delay_max': 6.0, 'cast_power_variance_pct': 5, 'bite_delay_max_ms': 450, 'coordinate_jitter_px': 20}, 'watchdog': {'enabled': False, 'timeout_seconds': 45}}
_PROFILE_NAME_RE = re.compile('^[a-zA-Z0-9_\\-\\s]{1,48}$')

def _ensure_profiles_dir():
    os.makedirs(PROFILES_DIR, exist_ok=True)

def _sanitize_profile_name(name: str) -> str:
    name = (name or '').strip()
    if not _PROFILE_NAME_RE.match(name):
        raise ValueError('Profile name: letters, numbers, spaces, - and _ only (max 48 chars).')
    return name

def _profile_path(name: str) -> str:
    safe = name.replace('/', '_').replace('\\', '_')
    return os.path.join(PROFILES_DIR, f'{safe}.json')

def _migrate_bot_mode(cfg: dict) -> None:
    mode = cfg.get('bot_mode', 'full_auto')
    if mode in ('full_auto_visual', 'full_auto_packet', 'full_auto_audio', 'hybrid'):
        cfg['bot_mode'] = 'full_auto'
    elif mode not in ('full_auto', 'semi_auto'):
        cfg['bot_mode'] = 'full_auto'

def _strip_removed_keys(cfg: dict) -> dict:
    out = copy.deepcopy(DEFAULT_CONFIG)
    for key in out:
        if key in cfg:
            out[key] = copy.deepcopy(cfg[key])
    _migrate_bot_mode(out)
    if 'auto_food' not in cfg:
        out['auto_food'] = copy.deepcopy(DEFAULT_CONFIG['auto_food'])
    else:
        out['auto_food'] = {**DEFAULT_CONFIG['auto_food'], **cfg.get('auto_food', {})}
    bait = cfg.get('auto_bait', {})
    if 'cast_count' in bait and 'every_n_catches' not in bait:
        bait = {**bait, 'every_n_catches': bait.pop('cast_count')}
    out['auto_bait'] = {**DEFAULT_CONFIG['auto_bait'], **bait}
    return out

def load_meta() -> dict:
    _ensure_profiles_dir()
    if os.path.exists(META_FILE):
        try:
            with open(META_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'active_profile': None, 'language': 'en'}

def get_language() -> str:
    return load_meta().get('language', 'en')

def save_language(lang: str) -> None:
    meta = load_meta()
    meta['language'] = lang
    save_meta(meta)

def save_meta(meta: dict) -> None:
    _ensure_profiles_dir()
    with open(META_FILE, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2)

def list_profiles() -> list[str]:
    _ensure_profiles_dir()
    names = []
    for fn in os.listdir(PROFILES_DIR):
        if fn.endswith('.json') and (not fn.startswith('_')):
            names.append(fn[:-5])
    return sorted(names, key=str.lower)

def load_profile(name: str) -> dict:
    name = _sanitize_profile_name(name)
    path = _profile_path(name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Profile '{name}' not found.")
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    return _strip_removed_keys(raw)

def save_profile(name: str, config_data: dict) -> None:
    name = _sanitize_profile_name(name)
    _ensure_profiles_dir()
    cleaned = _strip_removed_keys(config_data)
    with open(_profile_path(name), 'w', encoding='utf-8') as f:
        json.dump(cleaned, f, indent=4, ensure_ascii=False)
    meta = load_meta()
    meta['active_profile'] = name
    save_meta(meta)

def delete_profile(name: str) -> None:
    name = _sanitize_profile_name(name)
    path = _profile_path(name)
    if os.path.isfile(path):
        os.remove(path)
    meta = load_meta()
    if meta.get('active_profile') == name:
        meta['active_profile'] = None
        save_meta(meta)

def load_startup_config() -> dict:
    meta = load_meta()
    active = meta.get('active_profile')
    if active:
        try:
            return load_profile(active)
        except Exception:
            meta = load_meta()
            meta['active_profile'] = None
            save_meta(meta)
    return copy.deepcopy(DEFAULT_CONFIG)

def reset_to_factory_default() -> dict:
    return copy.deepcopy(DEFAULT_CONFIG)
