import json
import os
import time

STATS_FILE = "stats.json"


class StatsTracker:
    def __init__(self):
        self.session_start = time.time()
        self.session_catches = 0
        self.total_catches = 0
        self._load()

    def _load(self):
        if not os.path.exists(STATS_FILE):
            return
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.total_catches = int(data.get("total_catches", 0))
        except Exception:
            pass

    def _save(self):
        try:
            with open(STATS_FILE, "w", encoding="utf-8") as f:
                json.dump({"total_catches": self.total_catches}, f, indent=2)
        except Exception:
            pass

    def record_catch(self):
        self.session_catches += 1
        self.total_catches += 1
        self._save()

    def reset_session(self):
        self.session_start = time.time()
        self.session_catches = 0

    def reset_total(self):
        self.total_catches = 0
        self._save()

    def session_elapsed_seconds(self):
        return max(0.0, time.time() - self.session_start)

    def catches_per_hour(self):
        elapsed_h = self.session_elapsed_seconds() / 3600.0
        if elapsed_h <= 0:
            return 0.0
        return round(self.session_catches / elapsed_h, 1)

    def summary(self):
        elapsed = int(self.session_elapsed_seconds())
        mins, secs = divmod(elapsed, 60)
        hours, mins = divmod(mins, 60)
        if hours:
            elapsed_str = f"{hours}j {mins}m"
        else:
            elapsed_str = f"{mins}m {secs}d"
        return {
            "session_catches": self.session_catches,
            "total_catches": self.total_catches,
            "session_elapsed": elapsed_str,
            "catches_per_hour": self.catches_per_hour(),
        }
