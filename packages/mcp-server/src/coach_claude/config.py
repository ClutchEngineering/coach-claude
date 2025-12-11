"""Configuration management for Coach Claude."""

import os
from pathlib import Path
from typing import Dict, Any

# Default server port
DEFAULT_PORT = 8787

DEFAULT_CONFIG: Dict[str, Any] = {
    "water_threshold_minutes": 60,
    "workout_threshold_minutes": 120,
    "water_unit": "oz",
    "bottle_size_oz": 16,  # Size of a "bottle" in oz
    "daily_water_goal": 64,
    "session_start_check": True,
    "periodic_check_enabled": True,
    "quick_stretch_min": 30,
    "quick_stretch_max": 120,
    "short_exercise_min": 120,
    "short_exercise_max": 300,
    # Bedtime settings (24-hour format)
    "bedtime_hour": 22,  # 10 PM
    "bedtime_minute": 0,
    "wakeup_hour": 7,  # 7 AM
    "wakeup_minute": 0,
    # Body weight for bodyweight exercise calculations (in lbs)
    "body_weight": 0,  # 0 means not set
}


def get_db_path() -> Path:
    """Get the database path from environment or default."""
    db_path = os.getenv("COACH_CLAUDE_DB")
    if db_path:
        return Path(db_path).expanduser()

    coach_dir = Path.home() / ".coach-claude"
    coach_dir.mkdir(exist_ok=True)
    return coach_dir / "coach.db"


def get_logs_dir() -> Path:
    """Get the logs directory."""
    logs_dir = Path.home() / ".coach-claude" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir
