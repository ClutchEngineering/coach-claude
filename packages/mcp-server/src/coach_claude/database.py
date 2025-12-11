"""Database operations for Coach Claude."""

import aiosqlite
import time
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime, timedelta

from .config import DEFAULT_CONFIG, get_db_path
from .models import WaterLog, WorkoutLog, BodyWeightLog, Stats, ReminderStatus


class Database:
    """SQLite database manager for Coach Claude."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_db_path()

    async def init_db(self):
        """Initialize database schema and default configuration."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS water_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount REAL NOT NULL,
                    unit TEXT NOT NULL DEFAULT 'oz',
                    timestamp INTEGER NOT NULL,
                    notes TEXT
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS workout_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    duration INTEGER NOT NULL,
                    timestamp INTEGER NOT NULL,
                    notes TEXT,
                    weight REAL,
                    reps INTEGER,
                    body_parts TEXT
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ignored_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reminder_type TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    notes TEXT
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS body_weight_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    weight REAL NOT NULL,
                    timestamp INTEGER NOT NULL,
                    notes TEXT
                )
                """
            )

            await db.commit()

            # Migrate existing workout_logs table to add new columns
            cursor = await db.execute("PRAGMA table_info(workout_logs)")
            columns = [row[1] for row in await cursor.fetchall()]

            if "weight" not in columns:
                await db.execute("ALTER TABLE workout_logs ADD COLUMN weight REAL")
            if "reps" not in columns:
                await db.execute("ALTER TABLE workout_logs ADD COLUMN reps INTEGER")
            if "body_parts" not in columns:
                await db.execute("ALTER TABLE workout_logs ADD COLUMN body_parts TEXT")

            await db.commit()

            # Initialize default configuration
            for key, value in DEFAULT_CONFIG.items():
                existing = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
                if not await existing.fetchone():
                    await db.execute(
                        "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)",
                        (key, str(value), int(time.time())),
                    )

            await db.commit()

    async def log_water(
        self,
        amount: float,
        unit: Optional[str] = None,
        notes: Optional[str] = None,
        minutes_ago: int = 0,
    ) -> WaterLog:
        """Log water intake. Converts all units to oz for consistency."""
        standard_unit = await self.get_config_value("water_unit")

        # Convert to oz if a different unit is provided
        if unit is None:
            unit = standard_unit

        # Normalize the amount to oz
        unit_lower = unit.lower().strip()
        if unit_lower in ("oz", "ounce", "ounces"):
            normalized_amount = amount
        elif unit_lower in ("ml", "milliliter", "milliliters"):
            normalized_amount = amount / 29.5735  # ml to oz
        elif unit_lower in ("l", "liter", "liters", "litre", "litres"):
            normalized_amount = amount * 33.814  # liters to oz
        elif unit_lower in ("cup", "cups"):
            normalized_amount = amount * 8  # cups to oz
        elif unit_lower in ("bottle", "bottles"):
            bottle_size = float(await self.get_config_value("bottle_size_oz"))
            normalized_amount = amount * bottle_size
        elif unit_lower in ("glass", "glasses"):
            normalized_amount = amount * 8  # assume 8oz glass
        else:
            # Unknown unit, store as-is but warn
            normalized_amount = amount

        timestamp = int(time.time()) - (minutes_ago * 60)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO water_logs (amount, unit, timestamp, notes) VALUES (?, ?, ?, ?)",
                (normalized_amount, standard_unit, timestamp, notes),
            )
            await db.commit()
            log_id = cursor.lastrowid

        return WaterLog(
            id=log_id, amount=normalized_amount, unit=standard_unit, timestamp=timestamp, notes=notes
        )

    async def log_workout(
        self,
        type: str,
        name: str,
        duration: int,
        notes: Optional[str] = None,
        minutes_ago: int = 0,
        weight: Optional[float] = None,
        reps: Optional[int] = None,
        body_parts: Optional[str] = None,
    ) -> WorkoutLog:
        """Log a workout."""
        timestamp = int(time.time()) - (minutes_ago * 60)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO workout_logs (type, name, duration, timestamp, notes, weight, reps, body_parts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (type, name, duration, timestamp, notes, weight, reps, body_parts),
            )
            await db.commit()
            log_id = cursor.lastrowid

        return WorkoutLog(
            id=log_id,
            type=type,
            name=name,
            duration=duration,
            timestamp=timestamp,
            notes=notes,
            weight=weight,
            reps=reps,
            body_parts=body_parts,
        )

    async def get_last_water(self) -> Optional[WaterLog]:
        """Get the most recent water log."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM water_logs ORDER BY timestamp DESC LIMIT 1")
            row = await cursor.fetchone()

        if row:
            return WaterLog(
                id=row["id"],
                amount=row["amount"],
                unit=row["unit"],
                timestamp=row["timestamp"],
                notes=row["notes"],
            )
        return None

    async def get_last_workout(self) -> Optional[WorkoutLog]:
        """Get the most recent workout log."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM workout_logs ORDER BY timestamp DESC LIMIT 1")
            row = await cursor.fetchone()

        if row:
            return WorkoutLog(
                id=row["id"],
                type=row["type"],
                name=row["name"],
                duration=row["duration"],
                timestamp=row["timestamp"],
                notes=row["notes"],
                weight=row["weight"],
                reps=row["reps"],
                body_parts=row["body_parts"],
            )
        return None

    async def get_stats(self, period: str = "today") -> Stats:
        """Get statistics for a time period."""
        now = int(time.time())

        if period == "today":
            # Use wake-up time instead of midnight
            wakeup_hour = int(await self.get_config_value("wakeup_hour"))
            wakeup_minute = int(await self.get_config_value("wakeup_minute"))
            now_dt = datetime.now()
            todays_wakeup = now_dt.replace(
                hour=wakeup_hour, minute=wakeup_minute, second=0, microsecond=0
            )
            # If before today's wake-up, use yesterday's wake-up
            if now_dt < todays_wakeup:
                last_wakeup = todays_wakeup - timedelta(days=1)
            else:
                last_wakeup = todays_wakeup
            start_timestamp = int(last_wakeup.timestamp())
        elif period == "week":
            start_of_week = datetime.now() - timedelta(days=datetime.now().weekday())
            start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
            start_timestamp = int(start_of_week.timestamp())
        elif period == "month":
            start_of_month = datetime.now().replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            start_timestamp = int(start_of_month.timestamp())
        else:
            start_timestamp = 0

        async with aiosqlite.connect(self.db_path) as db:
            # Water stats
            cursor = await db.execute(
                "SELECT COALESCE(SUM(amount), 0) as total, unit FROM water_logs "
                "WHERE timestamp >= ? GROUP BY unit",
                (start_timestamp,),
            )
            water_rows = await cursor.fetchall()
            total_water = sum(row[0] for row in water_rows)
            water_unit = (
                water_rows[0][1] if water_rows else await self.get_config_value("water_unit")
            )

            # Workout stats
            cursor = await db.execute(
                "SELECT COUNT(*) as count, type, COALESCE(SUM(duration), 0) as total_duration "
                "FROM workout_logs WHERE timestamp >= ? GROUP BY type",
                (start_timestamp,),
            )
            workout_rows = await cursor.fetchall()

            workout_count = sum(row[0] for row in workout_rows)
            stretch_count = next((row[0] for row in workout_rows if row[1] == "stretch"), 0)
            exercise_count = next((row[0] for row in workout_rows if row[1] == "exercise"), 0)
            total_workout_duration = sum(row[2] for row in workout_rows)

        # Get time since last entries
        last_water = await self.get_last_water()
        last_workout = await self.get_last_workout()

        last_water_minutes = None
        if last_water:
            last_water_minutes = (now - last_water.timestamp) // 60

        last_workout_minutes = None
        if last_workout:
            last_workout_minutes = (now - last_workout.timestamp) // 60

        return Stats(
            period=period,
            total_water=total_water,
            water_unit=water_unit,
            workout_count=workout_count,
            stretch_count=stretch_count,
            exercise_count=exercise_count,
            total_workout_duration=total_workout_duration,
            last_water_minutes_ago=last_water_minutes,
            last_workout_minutes_ago=last_workout_minutes,
        )

    async def check_reminders(self) -> ReminderStatus:
        """Check if any reminders are due."""
        now = int(time.time())

        water_threshold = int(await self.get_config_value("water_threshold_minutes"))
        workout_threshold = int(await self.get_config_value("workout_threshold_minutes"))

        last_water = await self.get_last_water()
        last_workout = await self.get_last_workout()

        water_minutes_ago = None
        workout_minutes_ago = None

        water_due = False
        workout_due = False
        water_message = None
        workout_message = None

        if last_water:
            water_minutes_ago = (now - last_water.timestamp) // 60
            if water_minutes_ago >= water_threshold:
                water_due = True
                water_message = f"It's been {water_minutes_ago} minutes since your last water. Time for a drink!"
        else:
            water_due = True
            water_message = "No water logged yet today. Stay hydrated!"

        if last_workout:
            workout_minutes_ago = (now - last_workout.timestamp) // 60
            if workout_minutes_ago >= workout_threshold:
                workout_due = True
                workout_message = f"It's been {workout_minutes_ago} minutes since your last movement. Time for a quick stretch or exercise!"
        else:
            workout_due = True
            workout_message = "No workouts logged yet today. Take a movement break!"

        return ReminderStatus(
            water_due=water_due,
            workout_due=workout_due,
            last_water_minutes_ago=water_minutes_ago,
            last_workout_minutes_ago=workout_minutes_ago,
            water_threshold=water_threshold,
            workout_threshold=workout_threshold,
            water_message=water_message if water_due else None,
            workout_message=workout_message if workout_due else None,
        )

    async def get_config_value(self, key: str) -> str:
        """Get a configuration value."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = await cursor.fetchone()

        if row:
            return row[0]

        # Return default if not found
        return str(DEFAULT_CONFIG.get(key, ""))

    async def get_all_config(self) -> Dict[str, str]:
        """Get all configuration values."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT key, value FROM config")
            rows = await cursor.fetchall()

        return {row["key"]: row["value"] for row in rows}

    async def update_config(self, key: str, value: str):
        """Update a configuration value."""
        timestamp = int(time.time())

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO config (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, timestamp),
            )
            await db.commit()

    async def delete_water(self, log_id: int) -> bool:
        """Delete a water log entry by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM water_logs WHERE id = ?", (log_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def delete_workout(self, log_id: int) -> bool:
        """Delete a workout log entry by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM workout_logs WHERE id = ?", (log_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def update_workout(self, log_id: int, **kwargs) -> bool:
        """Update a workout log entry by ID. Only updates provided fields."""
        if not kwargs:
            return False

        # Build dynamic UPDATE query
        allowed_fields = {"name", "duration", "notes", "weight", "reps", "body_parts"}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

        if not updates:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [log_id]

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE workout_logs SET {set_clause} WHERE id = ?",
                values,
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_recent_water(self, limit: int = 5) -> List[WaterLog]:
        """Get recent water logs."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM water_logs ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()

        return [
            WaterLog(
                id=row["id"],
                amount=row["amount"],
                unit=row["unit"],
                timestamp=row["timestamp"],
                notes=row["notes"],
            )
            for row in rows
        ]

    async def get_recent_workouts(self, limit: int = 5) -> List[WorkoutLog]:
        """Get recent workout logs."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM workout_logs ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()

        return [
            WorkoutLog(
                id=row["id"],
                type=row["type"],
                name=row["name"],
                duration=row["duration"],
                timestamp=row["timestamp"],
                notes=row["notes"],
                weight=row["weight"],
                reps=row["reps"],
                body_parts=row["body_parts"],
            )
            for row in rows
        ]

    async def get_todays_workouts(self) -> List[WorkoutLog]:
        """Get all workouts logged since the last wake-up time."""
        # Get wake-up time from config
        wakeup_hour = int(await self.get_config_value("wakeup_hour"))
        wakeup_minute = int(await self.get_config_value("wakeup_minute"))

        now = datetime.now()
        # Calculate today's wake-up time
        todays_wakeup = now.replace(hour=wakeup_hour, minute=wakeup_minute, second=0, microsecond=0)

        # If we're before today's wake-up time, use yesterday's wake-up time
        if now < todays_wakeup:
            last_wakeup = todays_wakeup - timedelta(days=1)
        else:
            last_wakeup = todays_wakeup

        start_timestamp = int(last_wakeup.timestamp())

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM workout_logs WHERE timestamp >= ? ORDER BY timestamp ASC",
                (start_timestamp,),
            )
            rows = await cursor.fetchall()

        return [
            WorkoutLog(
                id=row["id"],
                type=row["type"],
                name=row["name"],
                duration=row["duration"],
                timestamp=row["timestamp"],
                notes=row["notes"],
                weight=row["weight"],
                reps=row["reps"],
                body_parts=row["body_parts"],
            )
            for row in rows
        ]

    async def get_body_part_stats(self) -> Dict[str, float]:
        """Get total weight moved per body part since last wake-up."""
        workouts = await self.get_todays_workouts()
        body_weight = float(await self.get_config_value("body_weight") or 0)

        stats: Dict[str, float] = {}
        for w in workouts:
            if w.reps and w.body_parts:
                # Use explicit weight if set, otherwise use body weight for bodyweight exercises
                weight = w.weight if w.weight else body_weight
                if weight > 0:
                    total = weight * w.reps
                    for part in w.body_parts.split(","):
                        part = part.strip().lower()
                        if part:
                            stats[part] = stats.get(part, 0) + total
        return stats

    async def log_ignored_reminder(self, reminder_type: str, notes: Optional[str] = None) -> None:
        """Log when the user ignores a health reminder."""
        timestamp = int(time.time())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO ignored_reminders (reminder_type, timestamp, notes) VALUES (?, ?, ?)",
                (reminder_type, timestamp, notes),
            )
            await db.commit()

    async def get_ignored_reminder_count(self, reminder_type: str) -> int:
        """Get the count of ignored reminders for a specific type."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM ignored_reminders WHERE reminder_type = ?",
                (reminder_type,),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_all_ignored_reminder_counts(self) -> Dict[str, int]:
        """Get counts of all ignored reminders by type."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT reminder_type, COUNT(*) as count FROM ignored_reminders GROUP BY reminder_type"
            )
            rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    async def log_body_weight(
        self,
        weight: float,
        notes: Optional[str] = None,
    ) -> BodyWeightLog:
        """Log body weight and update config."""
        timestamp = int(time.time())

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO body_weight_logs (weight, timestamp, notes) VALUES (?, ?, ?)",
                (weight, timestamp, notes),
            )
            await db.commit()
            log_id = cursor.lastrowid

        # Also update the config for quick access
        await self.update_config("body_weight", str(weight))

        return BodyWeightLog(id=log_id, weight=weight, timestamp=timestamp, notes=notes)

    async def get_latest_body_weight(self) -> Optional[BodyWeightLog]:
        """Get the most recent body weight log."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM body_weight_logs ORDER BY timestamp DESC LIMIT 1"
            )
            row = await cursor.fetchone()

        if row:
            return BodyWeightLog(
                id=row["id"],
                weight=row["weight"],
                timestamp=row["timestamp"],
                notes=row["notes"],
            )
        return None

    async def get_body_weight_history(self, limit: int = 30) -> List[BodyWeightLog]:
        """Get body weight history."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM body_weight_logs ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()

        return [
            BodyWeightLog(
                id=row["id"],
                weight=row["weight"],
                timestamp=row["timestamp"],
                notes=row["notes"],
            )
            for row in rows
        ]

    async def get_daily_water_stats(self, days: int = 30) -> List[Dict]:
        """Get daily water intake for the last N days."""
        now = datetime.now()
        start = now - timedelta(days=days)
        start_timestamp = int(start.timestamp())

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT date(timestamp, 'unixepoch', 'localtime') as day,
                       SUM(amount) as total,
                       unit
                FROM water_logs
                WHERE timestamp >= ?
                GROUP BY day, unit
                ORDER BY day DESC
                """,
                (start_timestamp,),
            )
            rows = await cursor.fetchall()

        return [{"date": row[0], "total": row[1], "unit": row[2]} for row in rows]

    async def get_daily_body_part_stats(self, days: int = 30) -> Dict[str, Dict[str, float]]:
        """Get daily weight moved per body part for the last N days."""
        now = datetime.now()
        start = now - timedelta(days=days)
        start_timestamp = int(start.timestamp())
        body_weight = float(await self.get_config_value("body_weight") or 0)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT date(timestamp, 'unixepoch', 'localtime') as day,
                       weight, reps, body_parts
                FROM workout_logs
                WHERE timestamp >= ? AND reps IS NOT NULL AND body_parts IS NOT NULL
                ORDER BY day DESC
                """,
                (start_timestamp,),
            )
            rows = await cursor.fetchall()

        # Aggregate by day and body part
        daily_stats: Dict[str, Dict[str, float]] = {}
        for row in rows:
            day = row["day"]
            reps = row["reps"]
            parts = row["body_parts"]
            weight = row["weight"] if row["weight"] else body_weight

            if not reps or not parts or weight <= 0:
                continue

            if day not in daily_stats:
                daily_stats[day] = {}

            total = weight * reps
            for part in parts.split(","):
                part = part.strip().lower()
                if part:
                    daily_stats[day][part] = daily_stats[day].get(part, 0) + total

        return daily_stats
