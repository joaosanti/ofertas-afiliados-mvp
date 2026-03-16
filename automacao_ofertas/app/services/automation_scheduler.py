import os
import threading
from datetime import datetime, timedelta
from typing import Any, Callable

AUTO_SOCIAL_SUPPORTED_MODES: dict[str, tuple[str, ...]] = {
    "facebook": ("feed", "reel"),
    "instagram": ("feed", "reel"),
    "both": ("feed", "reel", "feed_story"),
    "facebook_instagram": ("feed", "reel", "feed_story"),
    "whatsapp": ("group",),
}


def _bool_env(name: str, default: bool = False) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on", "sim"}


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int((os.getenv(name) or "").strip() or default))
    except ValueError:
        return default


def _local_now() -> datetime:
    return datetime.now()


def _local_iso(value: datetime | None = None) -> str:
    current = value or _local_now()
    return current.replace(microsecond=0).isoformat()


def _parse_times(value: str) -> list[str]:
    items = []
    for raw in (value or "").split(","):
        item = raw.strip()
        if len(item) == 5 and item[2] == ":":
            hour, minute = item.split(":")
            if hour.isdigit() and minute.isdigit():
                hh = int(hour)
                mm = int(minute)
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    items.append(f"{hh:02d}:{mm:02d}")
    return sorted(set(items))


def _next_time_from_schedule(times: list[str], now: datetime) -> datetime | None:
    if not times:
        return None
    today = now.date()
    for item in times:
        hour, minute = item.split(":")
        candidate = datetime(today.year, today.month, today.day, int(hour), int(minute))
        if candidate > now:
            return candidate
    first_hour, first_minute = times[0].split(":")
    tomorrow = now + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, int(first_hour), int(first_minute))


def _normalize_auto_social_action(platform: str | None, mode: str | None) -> tuple[str, str]:
    normalized_platform = (platform or "facebook").strip().lower() or "facebook"
    if normalized_platform not in AUTO_SOCIAL_SUPPORTED_MODES:
        normalized_platform = "facebook"
    allowed_modes = AUTO_SOCIAL_SUPPORTED_MODES[normalized_platform]
    normalized_mode = (mode or allowed_modes[0]).strip().lower() or allowed_modes[0]
    if normalized_platform in {"both", "facebook_instagram"} and normalized_mode == "feed":
        normalized_mode = "feed_story"
    if normalized_mode not in allowed_modes:
        normalized_mode = allowed_modes[0]
    if normalized_platform == "facebook_instagram":
        normalized_platform = "both"
    return normalized_platform, normalized_mode


class AutomationScheduler:
    def __init__(
        self,
        *,
        import_runner: Callable[[list[str]], dict[str, Any]],
        social_runner: Callable[[str, str, int], dict[str, Any]],
    ) -> None:
        self._import_runner = import_runner
        self._social_runner = social_runner
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._status = self._build_status()

    def import_providers(self) -> list[str]:
        raw = (os.getenv("AUTO_IMPORT_PROVIDERS") or "mercadolivre").strip()
        return [item.strip() for item in raw.split(",") if item.strip()]

    def social_platform(self) -> str:
        platform, _ = _normalize_auto_social_action(
            os.getenv("AUTO_SOCIAL_PLATFORM") or "facebook",
            os.getenv("AUTO_SOCIAL_MODE") or "feed",
        )
        return platform

    def social_mode(self) -> str:
        _, mode = _normalize_auto_social_action(
            os.getenv("AUTO_SOCIAL_PLATFORM") or "facebook",
            os.getenv("AUTO_SOCIAL_MODE") or "feed",
        )
        return mode

    def social_limit(self) -> int:
        configured = _int_env("AUTO_SOCIAL_LIMIT", 1)
        if self.social_platform() in {"both", "facebook_instagram"} and self.social_mode() == "feed_story":
            return 1
        return configured

    def story_platform(self) -> str:
        return (os.getenv("AUTO_STORY_PLATFORM") or "instagram").strip().lower()

    def story_mode(self) -> str:
        return "story"

    def story_limit(self) -> int:
        return _int_env("AUTO_STORY_LIMIT", 1)

    def import_times(self) -> list[str]:
        return _parse_times(os.getenv("AUTO_IMPORT_TIMES") or "")

    def social_times(self) -> list[str]:
        return _parse_times(os.getenv("AUTO_SOCIAL_TIMES") or "")

    def story_times(self) -> list[str]:
        return _parse_times(os.getenv("AUTO_STORY_TIMES") or "")

    def _job_status(self, job_key: str, now: datetime) -> dict[str, Any]:
        if job_key == "import":
            enabled = _bool_env("AUTO_IMPORT_ENABLED", False)
            times = self.import_times()
            interval = _int_env("AUTO_IMPORT_INTERVAL_MINUTES", 180)
            return {
                "enabled": enabled,
                "interval_minutes": interval,
                "times": times,
                "providers": self.import_providers(),
                "last_run_at": None,
                "last_status": None,
                "last_result": None,
                "next_run_at": _local_iso(_next_time_from_schedule(times, now)) if enabled and times else _local_iso(now + timedelta(minutes=interval)) if enabled else None,
            }
        if job_key == "social":
            enabled = _bool_env("AUTO_SOCIAL_ENABLED", False)
            times = self.social_times()
            interval = _int_env("AUTO_SOCIAL_INTERVAL_MINUTES", 120)
            return {
                "enabled": enabled,
                "interval_minutes": interval,
                "times": times,
                "platform": self.social_platform(),
                "mode": self.social_mode(),
                "limit": self.social_limit(),
                "last_run_at": None,
                "last_status": None,
                "last_result": None,
                "next_run_at": _local_iso(_next_time_from_schedule(times, now)) if enabled and times else _local_iso(now + timedelta(minutes=interval)) if enabled else None,
            }

        enabled = _bool_env("AUTO_STORY_ENABLED", False)
        times = self.story_times()
        interval = _int_env("AUTO_STORY_INTERVAL_MINUTES", 240)
        return {
            "enabled": enabled,
            "interval_minutes": interval,
            "times": times,
            "platform": self.story_platform(),
            "mode": self.story_mode(),
            "limit": self.story_limit(),
            "last_run_at": None,
            "last_status": None,
            "last_result": None,
            "next_run_at": _local_iso(_next_time_from_schedule(times, now)) if enabled and times else _local_iso(now + timedelta(minutes=interval)) if enabled else None,
        }

    def _build_status(self) -> dict[str, Any]:
        now = _local_now()
        return {
            "running": False,
            "started_at": None,
            "jobs": {
                "import": self._job_status("import", now),
                "social": self._job_status("social", now),
                "story": self._job_status("story", now),
            },
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="automation-scheduler", daemon=True)
        with self._lock:
            self._status = self._build_status()
            self._status["running"] = True
            self._status["started_at"] = _local_iso()
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        with self._lock:
            self._status["running"] = False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._status["running"],
                "started_at": self._status["started_at"],
                "jobs": {
                    "import": dict(self._status["jobs"]["import"]),
                    "social": dict(self._status["jobs"]["social"]),
                    "story": dict(self._status["jobs"]["story"]),
                },
            }

    def _refresh_next_run(self, job: str) -> None:
        now = _local_now()
        with self._lock:
            current = self._status["jobs"][job]
            times = current.get("times") or []
            if current["enabled"] and times:
                current["next_run_at"] = _local_iso(_next_time_from_schedule(times, now))
            elif current["enabled"]:
                current["next_run_at"] = _local_iso(now + timedelta(minutes=int(current["interval_minutes"])))
            else:
                current["next_run_at"] = None

    def _record_result(self, job: str, *, status: str, result: Any) -> None:
        with self._lock:
            entry = self._status["jobs"][job]
            entry["last_run_at"] = _local_iso()
            entry["last_status"] = status
            entry["last_result"] = result
        self._refresh_next_run(job)

    def _should_run_by_time(self, job: str, now: datetime) -> bool:
        entry = self._status["jobs"][job]
        times = entry.get("times") or []
        if not times:
            return False
        current_hm = now.strftime("%H:%M")
        last_run = entry.get("last_run_at") or ""
        already_ran_today = last_run.startswith(now.strftime("%Y-%m-%d")) and current_hm in last_run
        return current_hm in times and not already_ran_today

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            now = _local_now()
            try:
                if _bool_env("AUTO_IMPORT_ENABLED", False):
                    if self.import_times():
                        if self._should_run_by_time("import", now):
                            result = self._import_runner(self.import_providers())
                            self._record_result("import", status="success", result=result)
                    else:
                        last_run = self.snapshot()["jobs"]["import"]["last_run_at"]
                        interval = _int_env("AUTO_IMPORT_INTERVAL_MINUTES", 180)
                        if not last_run or datetime.fromisoformat(last_run.replace("Z", "")) <= now - timedelta(minutes=interval):
                            result = self._import_runner(self.import_providers())
                            self._record_result("import", status="success", result=result)

                if _bool_env("AUTO_SOCIAL_ENABLED", False):
                    if self.social_times():
                        if self._should_run_by_time("social", now):
                            result = self._social_runner(self.social_platform(), self.social_mode(), self.social_limit())
                            self._record_result("social", status="success", result=result)
                    else:
                        last_run = self.snapshot()["jobs"]["social"]["last_run_at"]
                        interval = _int_env("AUTO_SOCIAL_INTERVAL_MINUTES", 120)
                        if not last_run or datetime.fromisoformat(last_run.replace("Z", "")) <= now - timedelta(minutes=interval):
                            result = self._social_runner(self.social_platform(), self.social_mode(), self.social_limit())
                            self._record_result("social", status="success", result=result)

                if _bool_env("AUTO_STORY_ENABLED", False):
                    if self.story_times():
                        if self._should_run_by_time("story", now):
                            result = self._social_runner(self.story_platform(), "story", self.story_limit())
                            self._record_result("story", status="success", result=result)
                    else:
                        last_run = self.snapshot()["jobs"]["story"]["last_run_at"]
                        interval = _int_env("AUTO_STORY_INTERVAL_MINUTES", 240)
                        if not last_run or datetime.fromisoformat(last_run.replace("Z", "")) <= now - timedelta(minutes=interval):
                            result = self._social_runner(self.story_platform(), "story", self.story_limit())
                            self._record_result("story", status="success", result=result)
            except Exception as exc:  # noqa: BLE001
                if _bool_env("AUTO_STORY_ENABLED", False):
                    target = "story"
                elif _bool_env("AUTO_SOCIAL_ENABLED", False):
                    target = "social"
                else:
                    target = "import"
                self._record_result(target, status="error", result={"error": str(exc)})
            self._stop_event.wait(30)
