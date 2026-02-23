import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from dotenv import load_dotenv

from livekit.agents import JobContext, WorkerOptions, cli, Agent
from livekit.plugins import openai

load_dotenv()

# -----------------------------------
# Logging
# -----------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# -----------------------------------
# Kitchen State
# -----------------------------------

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

        self.last_alert_time: Dict[str, float] = {}

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

    def should_alert(self, key: str, cooldown: int = 300) -> bool:
        import time
        now = time.time()
        if key not in self.last_alert_time or now - self.last_alert_time[key] > cooldown:
            self.last_alert_time[key] = now
            return True
        return False

    def check_temperature(self) -> List[str]:
        issues = []
        for storage, temp in self.current_temps.items():
            low, high = self.SAFE_TEMP[storage]
            if not (low <= temp <= high):
                issues.append(
                    f"{storage.upper()} temperature unsafe: {temp}°C (safe range: {low}-{high}°C)"
                )
        return issues

    def check_expiry(self) -> List[str]:
        warnings = []
        for item in self.food_inventory:
            days_left = (item["expiry"] - datetime.now()).days

            if days_left < 0:
                warnings.append(
                    f"{item['name']} has EXPIRED (expired {abs(days_left)} days ago)"
                )
            elif days_left <= 1:
                warnings.append(
                    f"{item['name']} expires in {days_left} day(s)"
                )
        return warnings


# -----------------------------------
# Timer
# -----------------------------------

async def kitchen_timer(seconds: int, label: str, agent):
    logger.info(f"Timer started: {label} for {seconds} seconds")
    await asyncio.sleep(seconds)

    try:
        await agent.say(
            f"Your {label} timer is finished!",
            allow_interruptions=False,
        )
    except Exception as e:
        logger.error(f"Failed to announce timer completion: {e}")

    logger.info(f"Timer completed: {label}")


# -----------------------------------
# Background Monitor
# -----------------------------------

async def compliance_monitor(state: KitchenState, agent):
    logger.info("Compliance monitor started")

    try:
        while True:
            temp_issues = state.check_temperature()
            for issue in temp_issues:
                if state.should_alert(issue):
                    logger.warning(issue)
                    await agent.say(f"Alert: {issue}", allow_interruptions=True)

            expiry_warnings = state.check_expiry()
            for warning in expiry_warnings:
                if "EXPIRED" in warning and state.should_alert(warning):
                    logger.warning(warning)
                    await agent.say(warning, allow_interruptions=True)

            await asyncio.sleep(60)

    except asyncio.CancelledError:
        logger.info("Compliance monitor stopped")
        raise


# -----------------------------------
# Entry Point
# -----------------------------------

async def entrypoint(ctx: JobContext):
    logger.info("Kitchen AI assistant starting...")
    await ctx.connect()
    logger.info("Connected to room")

    state = KitchenState()
    tasks = []
    MAX_TIMERS = 10

    # ✅ FIXED: LLM without instructions
    llm = openai.LLM(
        model="gpt-4o-mini"
    )

    # ✅ FIXED: Instructions passed to Agent instead
    agent = Agent(
        llm=llm,
        instructions="""
        You are a Kitchen Compliance AI assistant.

        You can:
        - set_timer
        - check_temperature
        - check_food_expiry
        - add_food_item
        - get_inventory

        Be helpful, concise, and safety-focused.
        Always prioritize food safety and compliance.
        """
    )

    # ----------------------
    # Register Functions
    # ----------------------

    @agent.function()
    async def set_timer(seconds: int, label: str = "Timer") -> str:
        active_timers = len([t for t in tasks if not t.done()])
        if active_timers >= MAX_TIMERS:
            return f"Too many active timers ({active_timers}). Please wait."

        task = asyncio.create_task(
            kitchen_timer(seconds, label, agent)
        )
        tasks.append(task)
        return f"Timer set for {seconds} seconds: {label}"

    @agent.function()
    async def check_temperature() -> str:
        issues = state.check_temperature()
        if issues:
            return "Temperature issues detected: " + "; ".join(issues)
        return "All temperatures are within safe ranges."

    @agent.function()
    async def check_food_expiry() -> str:
        warnings = state.check_expiry()
        if warnings:
            return "Food warnings: " + "; ".join(warnings)
        return "All food items are fresh."

    @agent.function()
    async def add_food_item(
        name: str,
        days_until_expiry: int,
        storage: str = "fridge",
    ) -> str:
        item = {
            "name": name,
            "expiry": datetime.now() + timedelta(days=days_until_expiry),
            "storage": storage,
        }
        state.food_inventory.append(item)
        return f"Added {name} to {storage}, expires in {days_until_expiry} days."

    @agent.function()
    async def get_inventory() -> str:
        if not state.food_inventory:
            return "Your inventory is empty."

        items = []
        for item in state.food_inventory:
            days_left = (item["expiry"] - datetime.now()).days
            items.append(
                f"{item['name']} in {item['storage']} (expires in {days_left} days)"
            )

        return "Current inventory: " + "; ".join(items)

    # ----------------------

    try:
        monitor_task = asyncio.create_task(
            compliance_monitor(state, agent)
        )
        tasks.append(monitor_task)

        logger.info("Starting agent...")
        await agent.start(ctx.room)

    finally:
        logger.info("Cleaning up tasks...")
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Shutdown complete")


# -----------------------------------
# Run App
# -----------------------------------

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(entrypoint_fnc=entrypoint)
    )
