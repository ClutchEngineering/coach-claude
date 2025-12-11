"""Coach Claude MCP Server."""

import argparse
import asyncio
import sys
import time
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .database import Database
from .config import get_db_path, DEFAULT_PORT


# Initialize database
db = Database(get_db_path())

# Track active SSE sessions
active_sessions: dict[str, dict] = {}  # session_id -> {connected_at, last_seen}

# Track WebSocket dashboard connections for real-time updates
dashboard_websockets: set = set()

# Create MCP server
app = Server("coach-claude")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="log_water",
            description="Log water intake with amount and optional unit",
            inputSchema={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Amount of water consumed",
                    },
                    "unit": {
                        "type": "string",
                        "description": "Unit of measurement (oz, ml, cups, etc.). Optional, defaults to user's configured unit",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes about this water intake",
                    },
                    "minutes_ago": {
                        "type": "integer",
                        "description": "How many minutes ago this happened. Use for logging past events. Defaults to 0 (now).",
                    },
                },
                "required": ["amount"],
            },
        ),
        Tool(
            name="log_workout",
            description="Log a workout or stretch with type, name, and duration",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["stretch", "exercise"],
                        "description": "Type of workout: 'stretch' for quick stretches, 'exercise' for longer exercises",
                    },
                    "name": {
                        "type": "string",
                        "description": "Name of the workout (e.g., 'neck roll', 'pushups', 'walk')",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Duration in seconds",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes about this workout",
                    },
                    "minutes_ago": {
                        "type": "integer",
                        "description": "How many minutes ago this happened. Use for logging past events. Defaults to 0 (now).",
                    },
                    "weight": {
                        "type": "number",
                        "description": "Weight used in lbs (e.g., 25 for 25lb dumbbells)",
                    },
                    "reps": {
                        "type": "integer",
                        "description": "Number of repetitions performed",
                    },
                    "body_parts": {
                        "type": "string",
                        "description": "Comma-separated body parts worked (e.g., 'chest,triceps,shoulders')",
                    },
                },
                "required": ["type", "name", "duration"],
            },
        ),
        Tool(
            name="get_last_water",
            description="Get the most recent water intake log",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_last_workout",
            description="Get the most recent workout log",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="check_reminders",
            description="Check if water or workout reminders are due based on configured thresholds. This is the primary tool for the Coach Claude skill to determine when to suggest breaks.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_stats",
            description="Get statistics for a time period (today, week, month)",
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["today", "week", "month"],
                        "description": "Time period for statistics. Defaults to 'today'",
                    },
                },
            },
        ),
        Tool(
            name="update_config",
            description="Update a configuration value",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Configuration key (e.g., 'water_threshold_minutes', 'workout_threshold_minutes', 'water_unit', 'bedtime_hour', 'bedtime_minute', 'wakeup_hour', 'wakeup_minute')",
                    },
                    "value": {
                        "type": "string",
                        "description": "New value for the configuration",
                    },
                },
                "required": ["key", "value"],
            },
        ),
        Tool(
            name="get_config",
            description="Get configuration value(s). If no key provided, returns all configuration.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Optional configuration key to retrieve. If not provided, returns all config.",
                    },
                },
            },
        ),
        Tool(
            name="list_recent_water",
            description="List recent water intake logs with their IDs (useful for finding entries to delete)",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of entries to return. Defaults to 5.",
                    },
                },
            },
        ),
        Tool(
            name="list_recent_workouts",
            description="List recent workout logs with their IDs (useful for finding entries to delete)",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of entries to return. Defaults to 5.",
                    },
                },
            },
        ),
        Tool(
            name="delete_water",
            description="Delete a water intake log entry by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "The ID of the water log entry to delete",
                    },
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="delete_workout",
            description="Delete a workout log entry by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "The ID of the workout log entry to delete",
                    },
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="update_workout",
            description="Update an existing workout log entry. Only provided fields will be updated.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "The ID of the workout log entry to update",
                    },
                    "name": {
                        "type": "string",
                        "description": "New name for the workout",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "New duration in seconds",
                    },
                    "notes": {
                        "type": "string",
                        "description": "New notes",
                    },
                    "weight": {
                        "type": "number",
                        "description": "Weight used in lbs",
                    },
                    "reps": {
                        "type": "integer",
                        "description": "Number of repetitions",
                    },
                    "body_parts": {
                        "type": "string",
                        "description": "Comma-separated body parts worked",
                    },
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="log_ignored_reminder",
            description="Log when the user ignores a health reminder and keeps working anyway. Use this when you've suggested a break, water, or sleep and the user continues working instead.",
            inputSchema={
                "type": "object",
                "properties": {
                    "reminder_type": {
                        "type": "string",
                        "enum": ["water", "workout", "sleep"],
                        "description": "Type of reminder that was ignored",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional context about what the user chose to do instead",
                    },
                },
                "required": ["reminder_type"],
            },
        ),
        Tool(
            name="get_ignored_reminders",
            description="Get the count of ignored reminders by type",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_body_part_stats",
            description="Get total weight moved per body part today (since wake-up time)",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="log_body_weight",
            description="Log body weight measurement. This also updates the body_weight config used for bodyweight exercises.",
            inputSchema={
                "type": "object",
                "properties": {
                    "weight": {
                        "type": "number",
                        "description": "Body weight in lbs",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes (e.g., 'morning weight', 'after workout')",
                    },
                },
                "required": ["weight"],
            },
        ),
        Tool(
            name="get_body_weight_history",
            description="Get body weight history over time",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of entries to return. Defaults to 30.",
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "log_water":
            amount = arguments["amount"]
            unit = arguments.get("unit")
            notes = arguments.get("notes")
            minutes_ago = arguments.get("minutes_ago", 0)

            log = await db.log_water(amount, unit, notes, minutes_ago)
            time_str = f" ({minutes_ago} minutes ago)" if minutes_ago > 0 else ""
            return [
                TextContent(
                    type="text",
                    text=f"Logged {log.amount} {log.unit} of water at {log.datetime.strftime('%I:%M %p')}{time_str}",
                )
            ]

        elif name == "log_workout":
            workout_type = arguments["type"]
            name_arg = arguments["name"]
            duration = arguments["duration"]
            notes = arguments.get("notes")
            minutes_ago = arguments.get("minutes_ago", 0)
            weight = arguments.get("weight")
            reps = arguments.get("reps")
            body_parts = arguments.get("body_parts")

            log = await db.log_workout(
                workout_type, name_arg, duration, notes, minutes_ago, weight, reps, body_parts
            )
            duration_str = (
                f"{duration // 60}m {duration % 60}s" if duration >= 60 else f"{duration}s"
            )
            time_str = f" ({minutes_ago} minutes ago)" if minutes_ago > 0 else ""

            # Build response with weight info if provided
            response = f"Logged {log.type}: '{log.name}' for {duration_str}"
            if weight and reps:
                total_weight = weight * reps
                response += f" ({reps} reps × {weight}lb = {total_weight}lb total)"
                if body_parts:
                    response += f" [{body_parts}]"
            response += f" at {log.datetime.strftime('%I:%M %p')}{time_str}"

            return [TextContent(type="text", text=response)]

        elif name == "get_last_water":
            log = await db.get_last_water()
            if log:
                import time

                minutes_ago = (int(time.time()) - log.timestamp) // 60
                return [
                    TextContent(
                        type="text",
                        text=f"Last water: {log.amount} {log.unit} at {log.datetime.strftime('%I:%M %p')} ({minutes_ago} minutes ago)",
                    )
                ]
            return [TextContent(type="text", text="No water logged yet")]

        elif name == "get_last_workout":
            log = await db.get_last_workout()
            if log:
                import time

                minutes_ago = (int(time.time()) - log.timestamp) // 60
                duration_str = (
                    f"{log.duration // 60}m {log.duration % 60}s"
                    if log.duration >= 60
                    else f"{log.duration}s"
                )
                return [
                    TextContent(
                        type="text",
                        text=f"Last workout: {log.type} - '{log.name}' ({duration_str}) at {log.datetime.strftime('%I:%M %p')} ({minutes_ago} minutes ago)",
                    )
                ]
            return [TextContent(type="text", text="No workouts logged yet")]

        elif name == "check_reminders":
            from datetime import datetime

            status = await db.check_reminders()

            # Get time context
            now = datetime.now()
            current_time = now.strftime("%I:%M %p")
            current_date = now.strftime("%A, %B %d, %Y")

            # Get bedtime info
            bedtime_hour = int(await db.get_config_value("bedtime_hour"))
            bedtime_minute = int(await db.get_config_value("bedtime_minute"))
            wakeup_hour = int(await db.get_config_value("wakeup_hour"))
            wakeup_minute = int(await db.get_config_value("wakeup_minute"))

            current_minutes = now.hour * 60 + now.minute
            bedtime_minutes = bedtime_hour * 60 + bedtime_minute
            wakeup_minutes = wakeup_hour * 60 + wakeup_minute

            # Calculate time to bedtime
            time_to_bed = bedtime_minutes - current_minutes
            if time_to_bed < 0:
                time_to_bed += 1440  # Add 24 hours
            hours_to_bed = time_to_bed // 60
            mins_to_bed = time_to_bed % 60

            # Check if past bedtime
            past_bedtime = False
            if bedtime_minutes > wakeup_minutes:
                past_bedtime = (
                    current_minutes >= bedtime_minutes or current_minutes < wakeup_minutes
                )
            else:
                past_bedtime = (
                    current_minutes >= bedtime_minutes and current_minutes < wakeup_minutes
                )

            result_parts = []
            result_parts.append(f"🕐 Time: {current_time} ({current_date})")

            if past_bedtime:
                result_parts.append("🌙 Status: PAST BEDTIME - user should be sleeping!")
            elif hours_to_bed < 2:
                result_parts.append(
                    f"🌙 Bedtime: {hours_to_bed}h {mins_to_bed}m away - approaching bedtime"
                )
            else:
                result_parts.append(f"🌙 Bedtime: {hours_to_bed}h {mins_to_bed}m away")

            result_parts.append("")  # Empty line

            if status.water_due and status.water_message:
                result_parts.append(f"💧 Water: {status.water_message}")
            elif status.last_water_minutes_ago is not None:
                result_parts.append(
                    f"💧 Water: OK (last drink {status.last_water_minutes_ago} minutes ago, threshold: {status.water_threshold} minutes)"
                )
            else:
                result_parts.append("💧 Water: No logs yet")

            if status.workout_due and status.workout_message:
                result_parts.append(f"🏃 Workout: {status.workout_message}")
            elif status.last_workout_minutes_ago is not None:
                result_parts.append(
                    f"🏃 Workout: OK (last workout {status.last_workout_minutes_ago} minutes ago, threshold: {status.workout_threshold} minutes)"
                )
            else:
                result_parts.append("🏃 Workout: No logs yet")

            return [TextContent(type="text", text="\n".join(result_parts))]

        elif name == "get_stats":
            period = arguments.get("period", "today")
            stats = await db.get_stats(period)

            result = f"📊 Stats for {stats.period}:\n\n"
            result += f"💧 Water: {stats.total_water} {stats.water_unit}\n"
            result += f"🏃 Workouts: {stats.workout_count} total "
            result += f"({stats.stretch_count} stretches, {stats.exercise_count} exercises)\n"

            if stats.total_workout_duration > 0:
                minutes = stats.total_workout_duration // 60
                seconds = stats.total_workout_duration % 60
                result += f"⏱️  Total duration: {minutes}m {seconds}s\n"

            if stats.last_water_minutes_ago is not None:
                result += f"\n⏰ Last water: {stats.last_water_minutes_ago} minutes ago"
            if stats.last_workout_minutes_ago is not None:
                result += f"\n⏰ Last workout: {stats.last_workout_minutes_ago} minutes ago"

            return [TextContent(type="text", text=result)]

        elif name == "update_config":
            key = arguments["key"]
            value = arguments["value"]

            await db.update_config(key, value)
            return [TextContent(type="text", text=f"Updated {key} = {value}")]

        elif name == "get_config":
            key = arguments.get("key")

            if key:
                value = await db.get_config_value(key)
                return [TextContent(type="text", text=f"{key} = {value}")]
            else:
                config = await db.get_all_config()
                result = "Configuration:\n\n"
                for k, v in sorted(config.items()):
                    result += f"{k} = {v}\n"
                return [TextContent(type="text", text=result)]

        elif name == "list_recent_water":
            import time

            limit = arguments.get("limit", 5)
            logs = await db.get_recent_water(limit)
            if not logs:
                return [TextContent(type="text", text="No water logs found")]

            result = "Recent water logs:\n\n"
            for log in logs:
                minutes_ago = (int(time.time()) - log.timestamp) // 60
                result += f"ID {log.id}: {log.amount} {log.unit} at {log.datetime.strftime('%I:%M %p')} ({minutes_ago} min ago)\n"
            return [TextContent(type="text", text=result)]

        elif name == "list_recent_workouts":
            import time

            limit = arguments.get("limit", 5)
            logs = await db.get_recent_workouts(limit)
            if not logs:
                return [TextContent(type="text", text="No workout logs found")]

            result = "Recent workout logs:\n\n"
            for log in logs:
                minutes_ago = (int(time.time()) - log.timestamp) // 60
                duration_str = (
                    f"{log.duration // 60}m {log.duration % 60}s"
                    if log.duration >= 60
                    else f"{log.duration}s"
                )
                result += f"ID {log.id}: {log.type} - '{log.name}' ({duration_str}) at {log.datetime.strftime('%I:%M %p')} ({minutes_ago} min ago)\n"
            return [TextContent(type="text", text=result)]

        elif name == "delete_water":
            log_id = arguments["id"]
            deleted = await db.delete_water(log_id)
            if deleted:
                return [TextContent(type="text", text=f"Deleted water log ID {log_id}")]
            return [TextContent(type="text", text=f"Water log ID {log_id} not found")]

        elif name == "delete_workout":
            log_id = arguments["id"]
            deleted = await db.delete_workout(log_id)
            if deleted:
                return [TextContent(type="text", text=f"Deleted workout log ID {log_id}")]
            return [TextContent(type="text", text=f"Workout log ID {log_id} not found")]

        elif name == "update_workout":
            log_id = arguments["id"]
            updates = {k: v for k, v in arguments.items() if k != "id" and v is not None}
            if not updates:
                return [TextContent(type="text", text="No fields to update")]
            updated = await db.update_workout(log_id, **updates)
            if updated:
                return [TextContent(type="text", text=f"Updated workout ID {log_id}: {updates}")]
            return [TextContent(type="text", text=f"Workout log ID {log_id} not found")]

        elif name == "log_ignored_reminder":
            reminder_type = arguments["reminder_type"]
            notes = arguments.get("notes")
            await db.log_ignored_reminder(reminder_type, notes)
            count = await db.get_ignored_reminder_count(reminder_type)
            return [
                TextContent(
                    type="text",
                    text=f"Logged ignored {reminder_type} reminder. Total ignored {reminder_type} reminders: {count}",
                )
            ]

        elif name == "get_ignored_reminders":
            counts = await db.get_all_ignored_reminder_counts()
            if not counts:
                return [TextContent(type="text", text="No ignored reminders recorded. Good job!")]
            result = "Ignored reminders:\n"
            for rtype, count in counts.items():
                result += f"  {rtype}: {count}\n"
            return [TextContent(type="text", text=result)]

        elif name == "get_body_part_stats":
            stats = await db.get_body_part_stats()
            if not stats:
                return [
                    TextContent(
                        type="text", text="No weight training logged today (since wake-up)."
                    )
                ]
            result = "💪 Weight moved today by body part:\n\n"
            for part, total in sorted(stats.items(), key=lambda x: -x[1]):
                result += f"  {part}: {total:.0f} lbs\n"
            return [TextContent(type="text", text=result)]

        elif name == "log_body_weight":
            weight = arguments["weight"]
            notes = arguments.get("notes")
            log = await db.log_body_weight(weight, notes)
            result = (
                f"⚖️ Logged body weight: {log.weight} lbs at {log.datetime.strftime('%I:%M %p')}"
            )
            if notes:
                result += f" ({notes})"
            return [TextContent(type="text", text=result)]

        elif name == "get_body_weight_history":
            limit = arguments.get("limit", 30)
            logs = await db.get_body_weight_history(limit)
            if not logs:
                return [TextContent(type="text", text="No body weight logs found")]

            result = "⚖️ Body weight history:\n\n"
            for log in logs:
                date_str = log.datetime.strftime("%Y-%m-%d %I:%M %p")
                notes_str = f" ({log.notes})" if log.notes else ""
                result += f"  {date_str}: {log.weight} lbs{notes_str}\n"
            return [TextContent(type="text", text=result)]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main_stdio():
    """Run the MCP server with stdio transport."""
    # Initialize database
    await db.init_db()

    # Run server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run_sse(host: str, port: int):
    """Run the MCP server with SSE transport."""
    import uvicorn
    from mcp.server.sse import SseServerTransport

    # Create SSE transport
    sse = SseServerTransport("/messages/")

    async def render_stats_page() -> bytes:
        """Render a terminal-style stats page."""
        from datetime import datetime

        stats = await db.get_stats("today")
        last_water = await db.get_last_water()
        last_workout = await db.get_last_workout()

        # Get bedtime config
        bedtime_hour = int(await db.get_config_value("bedtime_hour"))
        bedtime_minute = int(await db.get_config_value("bedtime_minute"))
        wakeup_hour = int(await db.get_config_value("wakeup_hour"))
        wakeup_minute = int(await db.get_config_value("wakeup_minute"))

        # Calculate bedtime progress
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        bedtime_minutes = bedtime_hour * 60 + bedtime_minute
        wakeup_minutes = wakeup_hour * 60 + wakeup_minute

        # Calculate awake period (handles overnight bedtime)
        if bedtime_minutes > wakeup_minutes:
            # Normal case: wake up in morning, sleep at night
            awake_duration = bedtime_minutes - wakeup_minutes
            if current_minutes >= wakeup_minutes:
                elapsed = current_minutes - wakeup_minutes
            else:
                # Before wakeup time (late night)
                elapsed = awake_duration + (current_minutes + 1440 - bedtime_minutes)
        else:
            # Edge case: bedtime before wakeup (e.g., night shift)
            awake_duration = 1440 - wakeup_minutes + bedtime_minutes
            if current_minutes >= wakeup_minutes:
                elapsed = current_minutes - wakeup_minutes
            else:
                elapsed = current_minutes + 1440 - wakeup_minutes

        # Calculate percentage
        if awake_duration > 0:
            bedtime_percent = min(100, (elapsed / awake_duration) * 100)
        else:
            bedtime_percent = 0

        # Check if past bedtime
        past_bedtime = False
        if bedtime_minutes > wakeup_minutes:
            past_bedtime = current_minutes >= bedtime_minutes or current_minutes < wakeup_minutes
        else:
            past_bedtime = current_minutes >= bedtime_minutes and current_minutes < wakeup_minutes

        # Format bedtime for display
        bedtime_str = f"{bedtime_hour:02d}:{bedtime_minute:02d}"
        time_to_bed = bedtime_minutes - current_minutes
        if time_to_bed < 0:
            time_to_bed += 1440
        hours_left = time_to_bed // 60
        mins_left = time_to_bed % 60

        # Fixed width for content area (inside the box, excluding border chars)
        WIDTH = 34

        def pad_line(content: str) -> str:
            """Pad content to fixed width inside box."""
            padded = content.ljust(WIDTH)
            return f"| {padded} |"

        def divider() -> str:
            """Create a horizontal divider line."""
            return "+" + "-" * (WIDTH + 2) + "+"

        # Build terminal-style output
        lines = []
        lines.append(divider())
        lines.append(pad_line("COACH CLAUDE - TODAY".center(WIDTH)))
        lines.append(divider())

        water_str = f"{stats.total_water} {stats.water_unit}"
        lines.append(pad_line(f"Water:       {water_str}"))
        lines.append(pad_line(f"Workouts:    {stats.workout_count}"))
        lines.append(pad_line(f"  Stretches: {stats.stretch_count}"))
        lines.append(pad_line(f"  Exercises: {stats.exercise_count}"))

        if stats.total_workout_duration > 0:
            mins = stats.total_workout_duration // 60
            secs = stats.total_workout_duration % 60
            duration_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
            lines.append(pad_line(f"Duration:    {duration_str}"))

        lines.append(divider())

        if last_water and stats.last_water_minutes_ago is not None:
            lines.append(pad_line(f"Last water:   {stats.last_water_minutes_ago} min ago"))
        else:
            lines.append(pad_line("Last water:   --"))

        if last_workout and stats.last_workout_minutes_ago is not None:
            lines.append(pad_line(f"Last workout: {stats.last_workout_minutes_ago} min ago"))
        else:
            lines.append(pad_line("Last workout: --"))

        lines.append(divider())

        terminal_output = "\n".join(lines)

        # Build progress bar (20 chars wide)
        bar_width = 20
        filled = int(bar_width * bedtime_percent / 100)
        empty = bar_width - filled
        progress_bar = "█" * filled + "░" * empty
        progress_class = "progress-error" if past_bedtime else "progress-ok"

        if past_bedtime:
            time_label = "PAST BEDTIME"
        else:
            time_label = f"{hours_left}h {mins_left}m to bed"

        # Get today's workouts
        todays_workouts = await db.get_todays_workouts()

        # Build workout list HTML
        if todays_workouts:
            workout_items = []
            for w in todays_workouts:
                duration_str = (
                    f"{w.duration // 60}m {w.duration % 60}s"
                    if w.duration >= 60
                    else f"{w.duration}s"
                )
                time_str = w.datetime.strftime("%I:%M %p")
                icon = "🧘" if w.type == "stretch" else "💪"
                workout_items.append(
                    f'<div class="workout-item">'
                    f'<span class="workout-icon">{icon}</span>'
                    f'<span class="workout-name">{w.name}</span>'
                    f'<span class="workout-duration">{duration_str}</span>'
                    f'<span class="workout-time">{time_str}</span>'
                    f"</div>"
                )
            workout_list_html = "\n".join(workout_items)
        else:
            workout_list_html = '<div class="no-workouts">No workouts yet today</div>'

        db_path = str(get_db_path())
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Coach Claude</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{
            background: #1a1a1a;
            color: #00ff00;
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            gap: 20px;
        }}
        pre {{
            font-size: 14px;
            line-height: 1.0;
            white-space: pre;
            letter-spacing: 0;
        }}
        .btn {{
            position: fixed;
            background: #333;
            color: #00ff00;
            border: 1px solid #00ff00;
            padding: 6px 12px;
            font-family: inherit;
            font-size: 12px;
            cursor: pointer;
            text-decoration: none;
        }}
        .btn:hover {{
            background: #00ff00;
            color: #1a1a1a;
        }}
        .btn-top-left {{ top: 10px; left: 10px; }}
        .btn-top-right {{ top: 10px; right: 10px; }}
        .btn-bottom-left {{ bottom: 15px; left: 15px; }}
        .bedtime-container {{
            text-align: center;
            padding: 15px;
            border: 1px solid #333;
            background: #222;
            min-width: 280px;
        }}
        .bedtime-label {{
            font-size: 12px;
            margin-bottom: 8px;
            opacity: 0.8;
        }}
        .progress-bar {{
            font-size: 16px;
            letter-spacing: 2px;
            margin: 8px 0;
        }}
        .progress-ok {{
            color: #00ff00;
        }}
        .progress-error {{
            color: #ff4444;
        }}
        .time-left {{
            font-size: 14px;
            margin-top: 8px;
        }}
        .bedtime-time {{
            font-size: 11px;
            opacity: 0.6;
            margin-top: 4px;
        }}
        .workout-list {{
            text-align: left;
            padding: 15px;
            border: 1px solid #333;
            background: #222;
            min-width: 280px;
            max-width: 400px;
        }}
        .workout-list-label {{
            font-size: 12px;
            margin-bottom: 10px;
            opacity: 0.8;
            text-align: center;
        }}
        .workout-item {{
            display: flex;
            align-items: center;
            padding: 6px 0;
            border-bottom: 1px solid #333;
            font-size: 13px;
        }}
        .workout-item:last-child {{
            border-bottom: none;
        }}
        .workout-icon {{
            width: 24px;
            text-align: center;
        }}
        .workout-name {{
            flex: 1;
            margin-left: 8px;
        }}
        .workout-duration {{
            color: #888;
            margin-left: 10px;
            font-size: 11px;
        }}
        .workout-time {{
            color: #666;
            margin-left: 10px;
            font-size: 11px;
        }}
        .no-workouts {{
            text-align: center;
            color: #666;
            font-size: 12px;
            padding: 10px;
        }}
        .sessions-indicator {{
            position: fixed;
            bottom: 15px;
            right: 15px;
            background: #222;
            border: 1px solid #333;
            padding: 8px 12px;
            font-size: 12px;
            cursor: default;
        }}
        .sessions-header {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .sessions-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #666;
        }}
        .sessions-dot.active {{
            background: #00ff00;
            box-shadow: 0 0 6px #00ff00;
        }}
        .sessions-count {{
            color: #888;
        }}
        .sessions-count.active {{
            color: #00ff00;
        }}
        .sessions-details {{
            display: none;
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid #333;
            min-width: 150px;
        }}
        .sessions-indicator:hover .sessions-details {{
            display: block;
        }}
        .session-item {{
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            font-size: 11px;
        }}
        .session-id {{
            color: #00ff00;
            font-family: monospace;
        }}
        .session-duration {{
            color: #666;
        }}
        .no-sessions {{
            color: #666;
            font-style: italic;
        }}
    </style>
</head>
<body>
    <a href="/summary" class="btn btn-top-left">30 Day Recap</a>
    <a href="/installation" class="btn btn-top-right">Installation</a>
    <button class="btn btn-bottom-left" onclick="copyDbPath()">Copy DB Path</button>
    <pre>{terminal_output}</pre>
    <div class="bedtime-container">
        <div class="bedtime-label">BEDTIME COUNTDOWN</div>
        <div class="progress-bar {progress_class}">{progress_bar}</div>
        <div class="time-left {progress_class}">{time_label}</div>
        <div class="bedtime-time">Bedtime: {bedtime_str}</div>
    </div>
    <div class="workout-list">
        <div class="workout-list-label">TODAY'S WORKOUTS</div>
        {workout_list_html}
    </div>
    <div class="sessions-indicator">
        <div class="sessions-header">
            <div class="sessions-dot" id="sessions-dot"></div>
            <span class="sessions-count" id="sessions-count">0 sessions</span>
        </div>
        <div class="sessions-details" id="sessions-details">
            <div class="no-sessions">No active sessions</div>
        </div>
    </div>
    <script>
        const dbPath = "{db_path}";
        function copyDbPath() {{
            navigator.clipboard.writeText(dbPath).then(() => {{
                const btn = document.querySelector('.btn-left');
                btn.textContent = 'Copied!';
                setTimeout(() => btn.textContent = 'Copy DB Path', 1500);
            }});
        }}

        // WebSocket for real-time session updates
        function connectWebSocket() {{
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(protocol + '//' + window.location.host + '/ws');

            ws.onmessage = function(event) {{
                const data = JSON.parse(event.data);
                if (data.type === 'sessions') {{
                    const count = data.count;
                    const sessions = data.sessions || [];
                    const dot = document.getElementById('sessions-dot');
                    const countEl = document.getElementById('sessions-count');
                    const detailsEl = document.getElementById('sessions-details');

                    countEl.textContent = count + (count === 1 ? ' session' : ' sessions');

                    if (count > 0) {{
                        dot.classList.add('active');
                        countEl.classList.add('active');
                        detailsEl.innerHTML = sessions.map(s =>
                            `<div class="session-item">
                                <span class="session-id">${{s.id}}</span>
                                <span class="session-duration">${{s.duration}}</span>
                            </div>`
                        ).join('');
                    }} else {{
                        dot.classList.remove('active');
                        countEl.classList.remove('active');
                        detailsEl.innerHTML = '<div class="no-sessions">No active sessions</div>';
                    }}
                }}
            }};

            ws.onclose = function() {{
                // Reconnect after 2 seconds
                setTimeout(connectWebSocket, 2000);
            }};

            ws.onerror = function() {{
                ws.close();
            }};
        }}
        connectWebSocket();
    </script>
</body>
</html>"""
        return html.encode("utf-8")

    async def render_installation_page(port: int) -> bytes:
        """Render the installation guide page."""
        from . import daemon, skill, claude_settings

        # Check current status
        daemon_status = daemon.status()
        skill_installed = skill.is_installed()
        mcp_configured = claude_settings.is_mcp_configured()

        # Generate config JSON
        local_config = claude_settings.get_mcp_config_json(port, for_devcontainer=False)
        devcontainer_config = claude_settings.get_mcp_config_json(port, for_devcontainer=True)

        # Status indicators
        daemon_icon = "✓" if daemon_status["running"] else "✗"
        skill_icon = "✓" if skill_installed else "✗"
        mcp_icon = "✓" if mcp_configured else "✗"

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Coach Claude - Installation</title>
    <style>
        body {{
            background: #1a1a1a;
            color: #00ff00;
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
            padding: 20px;
            max-width: 800px;
            margin: 0 auto;
            line-height: 1.6;
        }}
        h1, h2, h3 {{
            color: #00ff00;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
        }}
        a {{
            color: #00ff00;
        }}
        .status {{
            background: #222;
            padding: 15px;
            border: 1px solid #333;
            margin: 15px 0;
        }}
        .status-item {{
            margin: 5px 0;
        }}
        .ok {{ color: #00ff00; }}
        .warn {{ color: #ffaa00; }}
        pre {{
            background: #111;
            padding: 15px;
            overflow-x: auto;
            border: 1px solid #333;
        }}
        code {{
            background: #222;
            padding: 2px 6px;
        }}
        .copy-btn {{
            background: #333;
            color: #00ff00;
            border: 1px solid #00ff00;
            padding: 4px 8px;
            font-family: inherit;
            font-size: 11px;
            cursor: pointer;
            float: right;
            margin-top: -5px;
        }}
        .copy-btn:hover {{
            background: #00ff00;
            color: #1a1a1a;
        }}
        .section {{
            margin: 30px 0;
        }}
        .back-link {{
            display: inline-block;
            margin-bottom: 20px;
            color: #00ff00;
        }}
    </style>
</head>
<body>
    <a href="/" class="back-link">&larr; Back to Dashboard</a>

    <h1>Coach Claude Installation</h1>

    <div class="status">
        <h3>Current Status</h3>
        <div class="status-item"><span class="{'ok' if daemon_status['running'] else 'warn'}">{daemon_icon}</span> Daemon: {'Running' if daemon_status['running'] else 'Not running'}</div>
        <div class="status-item"><span class="{'ok' if skill_installed else 'warn'}">{skill_icon}</span> Skill: {'Installed' if skill_installed else 'Not installed'}</div>
        <div class="status-item"><span class="{'ok' if mcp_configured else 'warn'}">{mcp_icon}</span> MCP Config: {'Configured' if mcp_configured else 'Not configured'}</div>
        <div class="status-item">Database: <code>{daemon_status['db_path']}</code></div>
        <div class="status-item">Logs: <code>{daemon_status['logs_path']}</code></div>
    </div>

    <div class="section">
        <h2>Quick Setup</h2>
        <p>Run this command to install everything automatically:</p>
        <pre>coach-claude install</pre>
        <p>This will:</p>
        <ul>
            <li>Install the daemon (auto-starts on login)</li>
            <li>Install the Claude skill</li>
            <li>Configure Claude Code's MCP settings</li>
        </ul>
    </div>

    <div class="section">
        <h2>Manual Configuration</h2>

        <h3>For Local Use</h3>
        <p>Add this to <code>~/.claude/settings.json</code>:</p>
        <button class="copy-btn" onclick="copyConfig('local')">Copy</button>
        <pre id="local-config">{local_config}</pre>

        <h3>For Devcontainers</h3>
        <p>Run the server on your host machine, then add this to your devcontainer's <code>~/.claude/settings.json</code>:</p>
        <button class="copy-btn" onclick="copyConfig('devcontainer')">Copy</button>
        <pre id="devcontainer-config">{devcontainer_config}</pre>
    </div>

    <div class="section">
        <h2>Commands</h2>
        <pre>
coach-claude install    # Full setup
coach-claude uninstall  # Remove everything
coach-claude start      # Start daemon
coach-claude stop       # Stop daemon
coach-claude status     # Show status
coach-claude run        # Run server directly
        </pre>
    </div>

    <div class="section">
        <h2>Troubleshooting</h2>
        <p><strong>Server not responding?</strong></p>
        <pre>coach-claude status</pre>

        <p><strong>Check logs:</strong></p>
        <pre>tail -f {daemon_status['logs_path']}/stderr.log</pre>

        <p><strong>Restart the daemon:</strong></p>
        <pre>coach-claude stop && coach-claude start</pre>
    </div>

    <script>
        function copyConfig(type) {{
            const el = document.getElementById(type + '-config');
            navigator.clipboard.writeText(el.textContent).then(() => {{
                const btn = el.previousElementSibling;
                btn.textContent = 'Copied!';
                setTimeout(() => btn.textContent = 'Copy', 1500);
            }});
        }}
    </script>
</body>
</html>"""
        return html.encode("utf-8")

    async def render_summary_page() -> bytes:
        """Render the 30-day summary page with charts."""
        import json
        from datetime import datetime, timedelta

        # Get data
        body_weight_history = await db.get_body_weight_history(30)
        daily_water = await db.get_daily_water_stats(30)
        daily_body_parts = await db.get_daily_body_part_stats(30)
        current_weight = float(await db.get_config_value("body_weight") or 0)

        # Generate last 30 days
        today = datetime.now().date()
        dates = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]

        # Build water data by date
        water_by_date = {w["date"]: w["total"] for w in daily_water}

        # Build body weight data by date
        weight_by_date = {}
        for log in body_weight_history:
            date_str = log.datetime.date().isoformat()
            if date_str not in weight_by_date:
                weight_by_date[date_str] = log.weight

        # Get all unique body parts
        all_body_parts = set()
        for day_stats in daily_body_parts.values():
            all_body_parts.update(day_stats.keys())
        all_body_parts = sorted(all_body_parts)

        # Build chart data
        chart_labels = [d[5:] for d in dates]  # MM-DD format
        weight_data = [weight_by_date.get(d, None) for d in dates]
        water_data = [water_by_date.get(d, 0) for d in dates]

        # Build table rows
        table_rows = []
        for date in dates:
            short_date = date[5:]  # MM-DD format
            water = water_by_date.get(date, 0)
            weight = weight_by_date.get(date, "")
            body_part_data = daily_body_parts.get(date, {})

            row = f"<tr><td>{short_date}</td><td>{water:.0f}</td><td>{weight}</td>"
            for part in all_body_parts:
                val = body_part_data.get(part, 0)
                row += f"<td>{val:.0f}</td>" if val > 0 else "<td>-</td>"
            row += "</tr>"
            table_rows.append(row)

        # Build header
        header = "<tr><th>Date</th><th>Water (oz)</th><th>Weight (lbs)</th>"
        for part in all_body_parts:
            header += f"<th>{part.title()}</th>"
        header += "</tr>"

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Coach Claude - 30 Day Recap</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            background: #1a1a1a;
            color: #00ff00;
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
            padding: 20px;
            margin: 0;
        }}
        h1, h2 {{
            text-align: center;
            margin-bottom: 10px;
        }}
        h2 {{
            font-size: 16px;
            color: #888;
            margin-top: 30px;
        }}
        .current-weight {{
            text-align: center;
            font-size: 18px;
            margin-bottom: 20px;
            color: #888;
        }}
        .current-weight span {{
            color: #00ff00;
            font-size: 24px;
        }}
        .back-link {{
            position: fixed;
            top: 10px;
            left: 10px;
            color: #00ff00;
            text-decoration: none;
            background: #333;
            border: 1px solid #00ff00;
            padding: 6px 12px;
            font-size: 12px;
            z-index: 100;
        }}
        .back-link:hover {{
            background: #00ff00;
            color: #1a1a1a;
        }}
        .charts-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin: 20px 0;
            justify-content: center;
        }}
        .chart-box {{
            background: #222;
            border: 1px solid #333;
            padding: 15px;
            flex: 1;
            min-width: 300px;
            max-width: 600px;
        }}
        .chart-title {{
            text-align: center;
            margin-bottom: 10px;
            font-size: 14px;
        }}
        .table-container {{
            overflow-x: auto;
            margin-top: 20px;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            min-width: 600px;
        }}
        th, td {{
            border: 1px solid #333;
            padding: 8px 12px;
            text-align: right;
        }}
        th {{
            background: #222;
            color: #00ff00;
            position: sticky;
            top: 0;
        }}
        th:first-child, td:first-child {{
            text-align: left;
            position: sticky;
            left: 0;
            background: #1a1a1a;
            z-index: 1;
        }}
        th:first-child {{
            background: #222;
            z-index: 2;
        }}
        tr:hover {{
            background: #252525;
        }}
        .legend {{
            margin-top: 20px;
            padding: 15px;
            background: #222;
            border: 1px solid #333;
        }}
        .legend-title {{
            color: #00ff00;
            margin-bottom: 10px;
        }}
        .legend-item {{
            color: #888;
            font-size: 12px;
            margin: 5px 0;
        }}
    </style>
</head>
<body>
    <a href="/" class="back-link">&larr; Dashboard</a>
    <h1>30 Day Recap</h1>
    <div class="current-weight">Current Weight: <span>{current_weight} lbs</span></div>

    <div class="charts-container">
        <div class="chart-box">
            <div class="chart-title">Body Weight (lbs)</div>
            <canvas id="weightChart"></canvas>
        </div>
        <div class="chart-box">
            <div class="chart-title">Daily Water Intake (oz)</div>
            <canvas id="waterChart"></canvas>
        </div>
    </div>

    <h2>Daily Details</h2>
    <div class="table-container">
        <table>
            <thead>
                {header}
            </thead>
            <tbody>
                {"".join(reversed(table_rows))}
            </tbody>
        </table>
    </div>

    <div class="legend">
        <div class="legend-title">Legend</div>
        <div class="legend-item">Water: Daily water intake in ounces</div>
        <div class="legend-item">Weight: Body weight measurement (lbs)</div>
        <div class="legend-item">Body parts: Total weight moved (weight × reps) in lbs</div>
    </div>

    <script>
        const labels = {json.dumps(chart_labels)};
        const weightData = {json.dumps(weight_data)};
        const waterData = {json.dumps(water_data)};

        const chartDefaults = {{
            responsive: true,
            plugins: {{
                legend: {{ display: false }}
            }},
            scales: {{
                x: {{
                    ticks: {{ color: '#888' }},
                    grid: {{ color: '#333' }}
                }},
                y: {{
                    ticks: {{ color: '#00ff00' }},
                    grid: {{ color: '#333' }}
                }}
            }}
        }};

        // Weight chart
        new Chart(document.getElementById('weightChart'), {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{
                    data: weightData,
                    borderColor: '#00ff00',
                    backgroundColor: 'rgba(0, 255, 0, 0.1)',
                    fill: true,
                    tension: 0.3,
                    spanGaps: true,
                    pointRadius: weightData.map(v => v !== null ? 4 : 0),
                    pointBackgroundColor: '#00ff00'
                }}]
            }},
            options: chartDefaults
        }});

        // Water chart
        new Chart(document.getElementById('waterChart'), {{
            type: 'bar',
            data: {{
                labels: labels,
                datasets: [{{
                    data: waterData,
                    backgroundColor: 'rgba(0, 150, 255, 0.6)',
                    borderColor: '#0096ff',
                    borderWidth: 1
                }}]
            }},
            options: chartDefaults
        }});
    </script>
</body>
</html>"""
        return html.encode("utf-8")

    async def broadcast_sessions():
        """Broadcast session count and details to all connected dashboard WebSockets."""
        import json

        now = int(time.time())
        sessions_list = []
        for sid, info in active_sessions.items():
            duration = now - info["connected_at"]
            mins = duration // 60
            secs = duration % 60
            sessions_list.append(
                {
                    "id": sid,
                    "duration": f"{mins}m {secs}s" if mins > 0 else f"{secs}s",
                }
            )

        message = json.dumps(
            {
                "type": "sessions",
                "count": len(active_sessions),
                "sessions": sessions_list,
            }
        )
        disconnected = set()
        for ws in dashboard_websockets:
            try:
                await ws.send({"type": "websocket.send", "text": message})
            except Exception:
                disconnected.add(ws)
        dashboard_websockets.difference_update(disconnected)

    async def handle_websocket(scope, receive, send):
        """Handle WebSocket connection for real-time dashboard updates."""
        import json

        # Wait for the WebSocket connection request
        message = await receive()
        if message["type"] != "websocket.connect":
            return

        # Create a simple send wrapper
        class WSSender:
            def __init__(self, send_func):
                self._send = send_func

            async def send(self, message):
                await self._send(message)

        ws = WSSender(send)

        # Accept the WebSocket connection
        await send({"type": "websocket.accept"})
        dashboard_websockets.add(ws)

        # Send initial session data with details
        now = int(time.time())
        sessions_list = []
        for sid, info in active_sessions.items():
            duration = now - info["connected_at"]
            mins = duration // 60
            secs = duration % 60
            sessions_list.append(
                {
                    "id": sid,
                    "duration": f"{mins}m {secs}s" if mins > 0 else f"{secs}s",
                }
            )
        initial = json.dumps(
            {
                "type": "sessions",
                "count": len(active_sessions),
                "sessions": sessions_list,
            }
        )
        await send({"type": "websocket.send", "text": initial})

        try:
            while True:
                message = await receive()
                if message["type"] == "websocket.disconnect":
                    break
                # We don't expect any messages from the client, but handle ping/pong if needed
        finally:
            dashboard_websockets.discard(ws)

    async def asgi_app(scope, receive, send):
        """Pure ASGI application for MCP SSE server."""
        if scope["type"] == "websocket":
            path = scope["path"]
            if path == "/ws":
                await handle_websocket(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 4004})
            return

        if scope["type"] == "lifespan":
            # Handle lifespan events
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await db.init_db()
                    print(f"Coach Claude MCP server running on http://{host}:{port}")
                    print(f"SSE endpoint: http://{host}:{port}/sse")
                    print(f"Dashboard: http://{host}:{port}/")
                    print(f"Installation: http://{host}:{port}/installation")
                    print(f"Database: {get_db_path()}")
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "http":
            path = scope["path"]
            method = scope["method"]

            if path == "/" and method == "GET":
                # Stats page
                html = await render_stats_page()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [[b"content-type", b"text/html; charset=utf-8"]],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": html,
                    }
                )
            elif path == "/installation" and method == "GET":
                # Installation page
                html = await render_installation_page(port)
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [[b"content-type", b"text/html; charset=utf-8"]],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": html,
                    }
                )
            elif path == "/summary" and method == "GET":
                # Summary page
                html = await render_summary_page()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [[b"content-type", b"text/html; charset=utf-8"]],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": html,
                    }
                )
            elif path == "/sse" and method == "GET":
                # SSE connection endpoint - track session
                import uuid

                session_id = str(uuid.uuid4())[:8]
                active_sessions[session_id] = {
                    "connected_at": int(time.time()),
                    "last_seen": int(time.time()),
                }
                await broadcast_sessions()
                try:
                    async with sse.connect_sse(scope, receive, send) as streams:
                        await app.run(streams[0], streams[1], app.create_initialization_options())
                finally:
                    active_sessions.pop(session_id, None)
                    await broadcast_sessions()
            elif path.startswith("/messages/") and method == "POST":
                # Message posting endpoint
                await sse.handle_post_message(scope, receive, send)
            else:
                # 404 Not Found
                await send(
                    {
                        "type": "http.response.start",
                        "status": 404,
                        "headers": [[b"content-type", b"text/plain"]],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"Not Found",
                    }
                )

    # Run with uvicorn (short graceful shutdown so Ctrl+C works quickly)
    uvicorn.run(asgi_app, host=host, port=port, log_level="info", timeout_graceful_shutdown=1)


# --- CLI Commands ---


def cmd_install(args):
    """Install daemon, skill, and MCP config."""
    from . import daemon, skill

    print("Installing Coach Claude...\n")

    # Check OS
    system = daemon.get_system()
    if system == "unsupported":
        print("Error: Unsupported operating system. Only macOS and Linux are supported.")
        sys.exit(1)

    # Install daemon
    try:
        daemon.install(args.port)
        print("✓ Created daemon (auto-starts on login)")
    except Exception as e:
        print(f"✗ Failed to install daemon: {e}")
        sys.exit(1)

    # Install skill
    try:
        skill_path = skill.install()
        print(f"✓ Installed skill to {skill_path}")
    except Exception as e:
        print(f"✗ Failed to install skill: {e}")

    # MCP config is per-project in Claude Code
    print("✓ Server ready")

    mcp_cmd = f"claude mcp add coach-claude -t sse http://localhost:{args.port}/sse"
    box_width = len(mcp_cmd) + 4
    print("")
    print("┌" + "─" * box_width + "┐")
    print("│  " + mcp_cmd + "  │")
    print("└" + "─" * box_width + "┘")
    print("")
    print("Run the command above in each project directory to enable Coach Claude.")

    print(
        f"""
Setup complete!

Dashboard: http://localhost:{args.port}/
Setup guide: http://localhost:{args.port}/installation
"""
    )


def cmd_uninstall(args):
    """Uninstall daemon, skill, and MCP config."""
    from . import daemon, skill, claude_settings

    print("Uninstalling Coach Claude...\n")

    # Remove daemon
    try:
        daemon.uninstall()
        print("✓ Removed daemon")
    except Exception as e:
        print(f"✗ Failed to remove daemon: {e}")

    # Remove skill (optional)
    if args.all:
        try:
            skill.uninstall()
            print("✓ Removed skill")
        except Exception as e:
            print(f"✗ Failed to remove skill: {e}")

        # Remove MCP config
        try:
            claude_settings.remove_mcp_config()
            print("✓ Removed MCP config")
        except Exception as e:
            print(f"✗ Failed to remove MCP config: {e}")

    print("\nUninstall complete. Your data remains in ~/.coach-claude/")


def cmd_start(args):
    """Start the daemon."""
    from . import daemon

    if not daemon.is_installed():
        print("Daemon not installed. Running server directly...")
        print("(Install with: coach-claude install)\n")
        run_sse(args.host, args.port)
    else:
        try:
            daemon.start()
            print("✓ Started Coach Claude daemon")
            print(f"  Dashboard: http://localhost:{args.port}/")
        except Exception as e:
            print(f"✗ Failed to start: {e}")
            sys.exit(1)


def cmd_stop(args):
    """Stop the daemon."""
    from . import daemon

    try:
        daemon.stop()
        print("✓ Stopped Coach Claude daemon")
    except Exception as e:
        print(f"✗ Failed to stop: {e}")
        sys.exit(1)


def cmd_restart(args):
    """Restart the daemon."""
    from . import daemon

    try:
        daemon.stop()
        print("✓ Stopped Coach Claude daemon")
    except Exception:
        pass  # May not be running

    try:
        daemon.start()
        print("✓ Started Coach Claude daemon")
        print(f"  Dashboard: http://localhost:{args.port}/")
    except Exception as e:
        print(f"✗ Failed to start: {e}")
        sys.exit(1)


def cmd_status(args):
    """Show daemon status."""
    from . import daemon, skill, claude_settings

    status = daemon.status()
    skill_installed = skill.is_installed()
    mcp_configured = claude_settings.is_mcp_configured()

    print("Coach Claude Status\n")
    print(f"System:      {status['system']}")
    print(f"Daemon:      {'Installed' if status['installed'] else 'Not installed'}")
    print(f"Running:     {'Yes' if status['running'] else 'No'}")
    print(f"Skill:       {'Installed' if skill_installed else 'Not installed'}")
    print(f"MCP Config:  {'Configured' if mcp_configured else 'Not configured'}")
    print(f"Executable:  {status['executable'] or 'Not found'}")
    print(f"Database:    {status['db_path']}")
    print(f"Logs:        {status['logs_path']}")
    print(f"Service:     {status['service_file']}")


def cmd_run(args):
    """Run the server directly."""
    if args.transport == "sse":
        run_sse(args.host, args.port)
    else:
        asyncio.run(main_stdio())


def run():
    """Entry point for the server."""
    parser = argparse.ArgumentParser(
        description="Coach Claude MCP Server - Health and wellness tracking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  install     Install daemon, skill, and configure MCP
  uninstall   Remove daemon (and optionally skill/config)
  start       Start the daemon
  stop        Stop the daemon
  restart     Restart the daemon
  status      Show current status
  run         Run server directly (without daemon)

Examples:
  coach-claude install
  coach-claude status
  coach-claude run --transport sse --port 8787
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # install
    install_parser = subparsers.add_parser("install", help="Install daemon, skill, and MCP config")
    install_parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})"
    )
    install_parser.set_defaults(func=cmd_install)

    # uninstall
    uninstall_parser = subparsers.add_parser("uninstall", help="Remove daemon")
    uninstall_parser.add_argument(
        "--all", action="store_true", help="Also remove skill and MCP config"
    )
    uninstall_parser.set_defaults(func=cmd_uninstall)

    # start
    start_parser = subparsers.add_parser("start", help="Start daemon")
    start_parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    start_parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})"
    )
    start_parser.set_defaults(func=cmd_start)

    # stop
    stop_parser = subparsers.add_parser("stop", help="Stop daemon")
    stop_parser.set_defaults(func=cmd_stop)

    # restart
    restart_parser = subparsers.add_parser("restart", help="Restart daemon")
    restart_parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})"
    )
    restart_parser.set_defaults(func=cmd_restart)

    # status
    status_parser = subparsers.add_parser("status", help="Show status")
    status_parser.set_defaults(func=cmd_status)

    # run
    run_parser = subparsers.add_parser("run", help="Run server directly")
    run_parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio", help="Transport (default: stdio)"
    )
    run_parser.add_argument("--host", default="127.0.0.1", help="Host for SSE (default: 127.0.0.1)")
    run_parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Port for SSE (default: {DEFAULT_PORT})"
    )
    run_parser.set_defaults(func=cmd_run)

    args = parser.parse_args()

    if args.command is None:
        # Default behavior: run with stdio (for backwards compatibility)
        args.transport = "stdio"
        cmd_run(args)
    else:
        args.func(args)


if __name__ == "__main__":
    run()
