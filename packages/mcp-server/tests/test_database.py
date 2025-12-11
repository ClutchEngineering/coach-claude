"""Tests for Coach Claude database operations."""

import pytest
import tempfile
from pathlib import Path

from coach_claude.database import Database


@pytest.fixture
async def db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        database = Database(db_path)
        await database.init_db()
        yield database


class TestWaterLogging:
    """Tests for water logging functionality."""

    async def test_log_water_basic(self, db):
        """Test basic water logging."""
        log = await db.log_water(16, "oz")
        assert log.amount == 16
        assert log.unit == "oz"
        assert log.id is not None

    async def test_log_water_converts_bottles_to_oz(self, db):
        """Test that bottles are converted to oz."""
        log = await db.log_water(1, "bottle")
        assert log.amount == 16  # Default bottle size
        assert log.unit == "oz"

    async def test_log_water_converts_cups_to_oz(self, db):
        """Test that cups are converted to oz."""
        log = await db.log_water(2, "cups")
        assert log.amount == 16  # 2 cups = 16 oz
        assert log.unit == "oz"

    async def test_log_water_converts_ml_to_oz(self, db):
        """Test that ml is converted to oz."""
        log = await db.log_water(500, "ml")
        assert 16 < log.amount < 17  # ~16.9 oz
        assert log.unit == "oz"

    async def test_log_water_converts_liters_to_oz(self, db):
        """Test that liters are converted to oz."""
        log = await db.log_water(1, "liter")
        assert 33 < log.amount < 34  # ~33.8 oz
        assert log.unit == "oz"

    async def test_get_last_water(self, db):
        """Test getting the last water log."""
        await db.log_water(8, "oz", minutes_ago=5)
        await db.log_water(16, "oz", minutes_ago=0)

        last = await db.get_last_water()
        assert last is not None
        assert last.amount == 16

    async def test_delete_water(self, db):
        """Test deleting a water log."""
        log = await db.log_water(16, "oz")
        deleted = await db.delete_water(log.id)
        assert deleted is True

        last = await db.get_last_water()
        assert last is None


class TestWorkoutLogging:
    """Tests for workout logging functionality."""

    async def test_log_stretch(self, db):
        """Test logging a stretch."""
        log = await db.log_workout("stretch", "neck roll", 30)
        assert log.type == "stretch"
        assert log.name == "neck roll"
        assert log.duration == 30
        assert log.id is not None

    async def test_log_exercise_with_weight(self, db):
        """Test logging an exercise with weight and reps."""
        log = await db.log_workout(
            "exercise",
            "bench press",
            60,
            weight=135,
            reps=10,
            body_parts="chest,triceps,shoulders",
        )
        assert log.type == "exercise"
        assert log.weight == 135
        assert log.reps == 10
        assert log.body_parts == "chest,triceps,shoulders"

    async def test_get_last_workout(self, db):
        """Test getting the last workout."""
        await db.log_workout("stretch", "arm circles", 20, minutes_ago=5)
        await db.log_workout("exercise", "pushups", 30, reps=15, minutes_ago=0)

        last = await db.get_last_workout()
        assert last is not None
        assert last.name == "pushups"

    async def test_update_workout(self, db):
        """Test updating a workout."""
        log = await db.log_workout("exercise", "pushups", 30)
        updated = await db.update_workout(log.id, reps=20, body_parts="chest,triceps")

        assert updated is True

        last = await db.get_last_workout()
        assert last.reps == 20
        assert last.body_parts == "chest,triceps"

    async def test_delete_workout(self, db):
        """Test deleting a workout."""
        log = await db.log_workout("stretch", "neck roll", 30)
        deleted = await db.delete_workout(log.id)
        assert deleted is True

        last = await db.get_last_workout()
        assert last is None


class TestBodyWeight:
    """Tests for body weight tracking."""

    async def test_log_body_weight(self, db):
        """Test logging body weight."""
        log = await db.log_body_weight(180.5, "morning weight")
        assert log.weight == 180.5
        assert log.notes == "morning weight"

        # Should also update config
        config_weight = await db.get_config_value("body_weight")
        assert config_weight == "180.5"

    async def test_get_body_weight_history(self, db):
        """Test getting body weight history."""
        await db.log_body_weight(181)
        await db.log_body_weight(180.5)
        await db.log_body_weight(180)

        history = await db.get_body_weight_history(10)
        assert len(history) == 3
        # Check all weights are present
        weights = {h.weight for h in history}
        assert weights == {181, 180.5, 180}


class TestConfig:
    """Tests for configuration."""

    async def test_default_config_values(self, db):
        """Test that default config values are set."""
        water_threshold = await db.get_config_value("water_threshold_minutes")
        assert water_threshold == "60"

        workout_threshold = await db.get_config_value("workout_threshold_minutes")
        assert workout_threshold == "120"

    async def test_update_config(self, db):
        """Test updating config values."""
        await db.update_config("water_threshold_minutes", "45")
        value = await db.get_config_value("water_threshold_minutes")
        assert value == "45"

    async def test_get_all_config(self, db):
        """Test getting all config values."""
        config = await db.get_all_config()
        assert "water_threshold_minutes" in config
        assert "workout_threshold_minutes" in config
        assert "water_unit" in config


class TestReminders:
    """Tests for reminder functionality."""

    async def test_check_reminders_when_nothing_logged(self, db):
        """Test reminders show due when nothing is logged."""
        status = await db.check_reminders()
        assert status.water_due is True
        assert status.workout_due is True

    async def test_check_reminders_after_logging(self, db):
        """Test reminders not due right after logging."""
        await db.log_water(16, "oz")
        await db.log_workout("stretch", "neck roll", 30)

        status = await db.check_reminders()
        assert status.water_due is False
        assert status.workout_due is False
        assert status.last_water_minutes_ago == 0
        assert status.last_workout_minutes_ago == 0


class TestStats:
    """Tests for statistics."""

    async def test_get_stats_today(self, db):
        """Test getting today's stats."""
        await db.log_water(16, "oz")
        await db.log_water(8, "oz")
        await db.log_workout("stretch", "neck roll", 30)
        await db.log_workout("exercise", "pushups", 60)

        stats = await db.get_stats("today")
        assert stats.total_water == 24
        assert stats.workout_count == 2
        assert stats.stretch_count == 1
        assert stats.exercise_count == 1
        assert stats.total_workout_duration == 90


class TestBodyPartStats:
    """Tests for body part statistics."""

    async def test_get_body_part_stats(self, db):
        """Test getting body part stats."""
        await db.log_workout(
            "exercise", "bench press", 60, weight=100, reps=10, body_parts="chest,triceps"
        )
        await db.log_workout(
            "exercise", "pushups", 30, weight=150, reps=20, body_parts="chest,triceps,shoulders"
        )

        stats = await db.get_body_part_stats()
        assert stats["chest"] == 4000  # 100*10 + 150*20
        assert stats["triceps"] == 4000
        assert stats["shoulders"] == 3000  # Only from pushups

    async def test_get_body_part_stats_uses_body_weight(self, db):
        """Test that body weight is used for exercises without explicit weight."""
        await db.update_config("body_weight", "200")
        await db.log_workout(
            "exercise", "pushups", 30, reps=10, body_parts="chest,triceps,shoulders"
        )

        stats = await db.get_body_part_stats()
        assert stats["chest"] == 2000  # 200 * 10
