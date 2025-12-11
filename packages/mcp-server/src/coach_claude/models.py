"""Data models for Coach Claude."""

from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime


class WaterLog(BaseModel):
    """Water intake log entry."""

    id: Optional[int] = None
    amount: float = Field(gt=0, description="Amount of water")
    unit: str = Field(default="oz", description="Unit of measurement")
    timestamp: int = Field(description="Unix timestamp")
    notes: Optional[str] = None

    @property
    def datetime(self) -> datetime:
        """Get datetime from timestamp."""
        return datetime.fromtimestamp(self.timestamp)


class WorkoutLog(BaseModel):
    """Workout log entry."""

    id: Optional[int] = None
    type: str = Field(description="Type of workout: 'stretch' or 'exercise'")
    name: str = Field(description="Name of the workout")
    duration: int = Field(gt=0, description="Duration in seconds")
    timestamp: int = Field(description="Unix timestamp")
    notes: Optional[str] = None
    weight: Optional[float] = Field(default=None, description="Weight used in lbs")
    reps: Optional[int] = Field(default=None, description="Number of repetitions")
    body_parts: Optional[str] = Field(default=None, description="Comma-separated body parts worked")

    @property
    def datetime(self) -> datetime:
        """Get datetime from timestamp."""
        return datetime.fromtimestamp(self.timestamp)

    @property
    def total_weight_moved(self) -> Optional[float]:
        """Calculate total weight moved (weight * reps)."""
        if self.weight is not None and self.reps is not None:
            return self.weight * self.reps
        return None


class BodyWeightLog(BaseModel):
    """Body weight log entry."""

    id: Optional[int] = None
    weight: float = Field(gt=0, description="Body weight in lbs")
    timestamp: int = Field(description="Unix timestamp")
    notes: Optional[str] = None

    @property
    def datetime(self) -> datetime:
        """Get datetime from timestamp."""
        return datetime.fromtimestamp(self.timestamp)


class Streak(BaseModel):
    """Streak tracking for goals."""

    streak_type: str = Field(description="Type of streak: 'water' or 'workout'")
    current: int = Field(default=0, description="Current streak in days")
    longest: int = Field(default=0, description="Longest streak ever achieved")
    last_completed_date: Optional[str] = Field(
        default=None, description="Last date goal was met (YYYY-MM-DD)"
    )


class ConfigEntry(BaseModel):
    """Configuration entry."""

    key: str
    value: str
    updated_at: int


class Stats(BaseModel):
    """Statistics for a time period."""

    period: str
    total_water: float
    water_unit: str
    workout_count: int
    stretch_count: int
    exercise_count: int
    total_workout_duration: int
    last_water_minutes_ago: Optional[int] = None
    last_workout_minutes_ago: Optional[int] = None


class ReminderStatus(BaseModel):
    """Current reminder status."""

    water_due: bool
    workout_due: bool
    last_water_minutes_ago: Optional[int]
    last_workout_minutes_ago: Optional[int]
    water_threshold: int
    workout_threshold: int
    water_message: Optional[str] = None
    workout_message: Optional[str] = None
