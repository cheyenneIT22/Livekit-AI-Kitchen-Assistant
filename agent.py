import asyncio
import logging
from datetime import datetime, timedelta
from typing import List

from dotenv import load_dotenv

from livekit.agents import (
    JobContext,
    WorkerOptions,
    cli,
    function_tool,
    Agent,
)
from livekit.plugins import openai

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ----------------------
# Kitchen State
# ----------------------

class KitchenState:
    SAFE_TEMP = {
        "fridge": (0, 5),
        "freezer": (-25, -18),
    }

    def __init__(self):
        self.current_temps = {
            "fridge": 7,
            "freezer": -17,
        }
        self.food_inventory = [
            {
                "name": "Milk",
                "expiry": datetime.now() + timedelta(days=1),
                "storage": "fridge",
            },
            {
                "name": "Chicken",
                "expiry": datetime.now() - timedelta(days=1),
                "storage": "fridge",
            },
        ]

    def check_temperature(self) -> List[str]:
        issues = []
        for storage, temp in self.current_temps.items():
            low, high = self.SAFE_TEMP[storage]
            if not (low <= temp <= high):
                issues.append(
                    f"{storage.upper()} temp unsafe: {temp}°C (safe {low}-{high}°C)"
                )
        return issues

    def check_expiry(self) -> List[str]:
        warnings = []
        for item in self.food_inventory:
            days_left = (item["expiry"] - datetime.now()).days
            if days_left < 0:
                warnings.append(f"{item['name']} has EXPIRED")
            elif days_left <= 1:
                warnings.append(f"{item['name']} expires soon")
        return warnings


# ----------------------
# Entry Point
# ----------------------

async def entrypoint(ctx: JobContext):
    logger.info("Starting Kitchen AI Agent...")
    await ctx.connect()
    logger.info("Connected to room")

    state = KitchenState()
    tasks: List[asyncio.Task] = []
    MAX_TIMERS = 10

    # ----------------------
    # Create LLM (NO system_prompt here!)
    # ----------------------

    llm = openai.LLM(
        model="gpt-4o-mini",
    )

    assistant = Agent(
        llm=llm,
        stt=openai.STT(),
        tts=openai.TTS(),
        system_prompt="""
        You are a Kitchen Compliance AI assistant.
        Prioritize food safety.
        Be concise and clear.
        """,
    )

    # ----------------------
    # Tools
    # ----------------------

    @function_tool()
    async def set_timer(context, seconds: int, label: str = "Timer") -> str:
        active = len([t for t in tasks if not t.done()])
        if active >= MAX_TIMERS:
            return f"Too many timers ({active}) active."

        async def timer_task():
            await asyncio.sleep(seconds)
            await assistant.say(f"{label} timer finished!")

        task = asyncio.create_task(timer_task())
        tasks.append(task)
        return f"Timer set for {seconds} seconds: {label}"

    @function_tool()
    async def check_temperature(context) -> str:
        issues = state.check_temperature()
        return "Issues: " + "; ".join(issues) if issues else "All temperatures are safe."

    @function_tool()
    async def check_food_expiry(context) -> str:
        warnings = state.check_expiry()
        return "Warnings: " + "; ".join(warnings) if warnings else "All food items are fresh."

    @function_tool()
    async def add_food_item(context, name: str, days_until_expiry: int, storage: str = "fridge") -> str:
        state.food_inventory.append({
            "name": name,
            "expiry": datetime.now() + timedelta(days=days_until_expiry),
            "storage": storage,
        })
        return f"Added {name} to {storage}, expires in {days_until_expiry} days."

    @function_tool()
    async def get_inventory(context) -> str:
        if not state.food_inventory:
            return "Inventory is empty."

        lines = [
            f"{item['name']} ({item['storage']}, expires {(item['expiry'] - datetime.now()).days} days)"
            for item in state.food_inventory
        ]
        return "Inventory: " + "; ".join(lines)

    # Attach tools (Correct for 1.4.3)
    assistant.tools = [
        set_timer,
        check_temperature,
        check_food_expiry,
        add_food_item,
        get_inventory,
    ]

    # ----------------------
    # Background Alerts
    # ----------------------

    async def auto_expiry_checker():
        while True:
            warnings = state.check_expiry()
            if warnings:
                await assistant.say("Food alert: " + "; ".join(warnings))
            await asyncio.sleep(60)

    async def auto_temp_checker():
        while True:
            issues = state.check_temperature()
            if issues:
                await assistant.say("Temperature alert: " + "; ".join(issues))
            await asyncio.sleep(30)

    asyncio.create_task(auto_expiry_checker())
    asyncio.create_task(auto_temp_checker())

    # ----------------------
    # Run Agent
    # ----------------------

    await assistant.run(ctx)

    logger.info("Kitchen AI Agent is ready!")



if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            worker_type="room",
        )
    )

