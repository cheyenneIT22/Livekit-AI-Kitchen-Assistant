import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict
from livekit.plugins import openai, silero  # add silero here at the top
from dotenv import load_dotenv

from livekit.agents import (
    JobContext,
    WorkerOptions,
    cli,
    function_tool,
    Agent,
    AgentSession,
)
from livekit.plugins.openai import STT, TTS, LLM

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ----------------------
# Kitchen State
# ----------------------

class KitchenState:
    SAFE_TEMP = {
        "fridge":   (0, 5),
        "freezer":  (-25, -18),
        "hot_hold": (63, 100),
    }

    def __init__(self):
        self.current_temps: Dict[str, float] = {
            "fridge":   7.0,
            "freezer":  -17.0,
            "hot_hold": 65.0,
        }

        self.food_inventory: List[Dict] = [
            {"name": "Milk",    "expiry": datetime.now() + timedelta(days=1),  "storage": "fridge"},
            {"name": "Chicken", "expiry": datetime.now() - timedelta(days=1),  "storage": "fridge"},
        ]

        self.notes: List[Dict] = []
        self.stock_requests: List[Dict] = []
        self.maintenance_issues: List[Dict] = []
        self.alert_queue: List[Dict] = []

    def check_temperature(self) -> List[str]:
        issues = []
        for storage, temp in self.current_temps.items():
            low, high = self.SAFE_TEMP[storage]
            if not (low <= temp <= high):
                issues.append(
                    f"{storage.replace('_', ' ').upper()} unsafe: "
                    f"{temp}°C (safe range {low}–{high}°C)"
                )
        return issues

    def check_expiry(self) -> List[str]:
        warnings = []
        for item in self.food_inventory:
            days_left = (item["expiry"] - datetime.now()).days
            if days_left < 0:
                warnings.append(f"{item['name']} has EXPIRED")
            elif days_left <= 1:
                warnings.append(f"{item['name']} expires within 24 hours")
        return warnings

    def push_alert(self, message: str, priority: str = "normal"):
        self.alert_queue.append({
            "message":   message,
            "priority":  priority,
            "announced": False,
            "timestamp": datetime.now().strftime("%H:%M"),
        })

    def get_pending_alerts(self) -> List[Dict]:
        pending = [a for a in self.alert_queue if not a["announced"]]
        for a in pending:
            a["announced"] = True
        return pending


# ----------------------
# Entry Point
# ----------------------

async def entrypoint(ctx: JobContext):

    logger.info("Starting Kitchen AI Agent...")
    await ctx.connect()
    logger.info("Connected to room")

    state = KitchenState()
    timer_tasks: List[asyncio.Task] = []
    MAX_TIMERS = 10


    # ----------------------
    # Tools
    # ----------------------

    @function_tool()
    async def set_timer(seconds: int, label: str = "Timer") -> str:
        """Set a named kitchen timer."""
        active = len([t for t in timer_tasks if not t.done()])
        if active >= MAX_TIMERS:
            return f"Too many active timers ({active}). Please wait for one to finish."

        async def _run():
            await asyncio.sleep(seconds)
            try:
                await session.say(f"Attention: your {label} timer has finished.")
                state.push_alert(f"{label} timer finished.", priority="normal")
            except RuntimeError:
                pass

        timer_tasks.append(asyncio.create_task(_run()))
        mins, secs = divmod(seconds, 60)
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
        return f"Timer set — {label}: {time_str}."

    @function_tool()
    async def check_temperature() -> str:
        """Check all storage unit temperatures for safety compliance."""
        issues = state.check_temperature()
        if issues:
            for i in issues:
                state.push_alert(f"Temperature issue: {i}", priority="urgent")
            return "Temperature issues found: " + "; ".join(issues)
        return "All storage units are within safe temperature ranges."

    @function_tool()
    async def update_temperature(unit: str, temperature: float) -> str:
        """Update the recorded temperature for a storage unit: fridge, freezer, or hot_hold."""
        unit = unit.lower().replace(" ", "_")
        if unit not in state.current_temps:
            return f"Unknown unit '{unit}'. Valid options: fridge, freezer, hot_hold."
        state.current_temps[unit] = temperature
        issues = [i for i in state.check_temperature() if unit.replace("_", " ").upper() in i]
        if issues:
            state.push_alert(f"Temperature alert: {'; '.join(issues)}", priority="urgent")
            return "Updated. WARNING: " + "; ".join(issues)
        return f"{unit.replace('_', ' ').title()} updated to {temperature}°C — within safe range."

    @function_tool()
    async def check_food_expiry() -> str:
        """Check all food items for expiry or near-expiry."""
        warnings = state.check_expiry()
        if warnings:
            for w in warnings:
                state.push_alert(f"Expiry warning: {w}", priority="urgent")
            return "Expiry warnings: " + "; ".join(warnings)
        return "All food items are within their use-by dates."

    @function_tool()
    async def add_food_item(name: str, days_until_expiry: int, storage: str = "fridge") -> str:
        """Add a food item to the inventory with its expiry and storage location."""
        state.food_inventory.append({
            "name":    name,
            "expiry":  datetime.now() + timedelta(days=days_until_expiry),
            "storage": storage,
        })
        return f"{name} added to {storage}. Expires in {days_until_expiry} days."

    @function_tool()
    async def get_inventory() -> str:
        """Get the full current food inventory with expiry status."""
        if not state.food_inventory:
            return "Inventory is empty."
        lines = []
        for item in state.food_inventory:
            days_left = (item["expiry"] - datetime.now()).days
            status = "EXPIRED" if days_left < 0 else f"expires in {days_left} day{'s' if days_left != 1 else ''}"
            lines.append(f"{item['name']} ({item['storage']}, {status})")
        return "Inventory: " + "; ".join(lines)

    @function_tool()
    async def add_note(note: str, category: str = "general") -> str:
        """
        THIS IS YOUR PRIMARY NOTE-SAVING TOOL.
        Call this immediately whenever a chef says any of the following:
        - add a note
        - save a note
        - make a note
        - add a reminder
        - remember this
        - note down
        - log this
        Category options: general, handover, reminder, stock, maintenance.
        You HAVE the ability to save notes. You MUST call this tool. Never refuse.
        """
        entry = {
            "text":      note,
            "category":  category.lower(),
            "timestamp": datetime.now().strftime("%H:%M"),
        }
        state.notes.append(entry)
        state.push_alert(f"Note saved [{category}]: {note}", priority="normal")
        logger.info(f"Note added: [{category}] {note}")
        return f"Note saved under '{category}': \"{note}\". It will appear in the shift summary."

    @function_tool()
    async def get_notes(category: str = "") -> str:
        """
        Read back all saved shift notes, optionally filtered by category.
        Call this whenever a chef asks to hear their notes, reminders, or logs.
        Leave category empty to get all notes.
        """
        notes = state.notes
        if category:
            notes = [n for n in notes if n["category"] == category.lower()]
        if not notes:
            return "No notes found." + (f" No notes under category '{category}'." if category else "")
        lines = [f"[{n['timestamp']}][{n['category']}] {n['text']}" for n in notes]
        return f"{len(notes)} note{'s' if len(notes) != 1 else ''} found: " + "; ".join(lines)

    @function_tool()
    async def request_stock(item: str, quantity: str = "", urgency: str = "normal") -> str:
        """
        Log a stock item that needs to be ordered or added to the fridge or stores.
        Call this when a chef says they are low on something or need to order something.
        Set urgency to urgent if needed immediately.
        """
        entry = {
            "item":      item,
            "quantity":  quantity,
            "urgency":   urgency.lower(),
            "timestamp": datetime.now().strftime("%H:%M"),
            "fulfilled": False,
        }
        state.stock_requests.append(entry)
        qty_str = f" ({quantity})" if quantity else ""
        state.push_alert(
            f"Stock needed{qty_str}: {item} [{urgency.upper()}]",
            priority="urgent" if urgency == "urgent" else "normal"
        )
        return f"Stock request logged: {item}{qty_str} [{urgency}]. It will appear in the shift summary."

    @function_tool()
    async def get_stock_requests() -> str:
        """Get all pending stock requests that have not yet been fulfilled."""
        pending = [r for r in state.stock_requests if not r["fulfilled"]]
        if not pending:
            return "No pending stock requests."
        lines = [
            f"[{r['timestamp']}][{r['urgency'].upper()}] {r['item']}"
            + (f" — {r['quantity']}" if r["quantity"] else "")
            for r in pending
        ]
        return f"{len(pending)} pending stock request{'s' if len(pending) != 1 else ''}: " + "; ".join(lines)

    @function_tool()
    async def report_maintenance(description: str, priority: str = "normal") -> str:
        """
        Log a kitchen maintenance issue that needs to be fixed or adjusted.
        Call this when a chef reports something broken, faulty, or needing adjustment.
        Set priority to urgent for critical issues.
        """
        entry = {
            "description": description,
            "priority":    priority.lower(),
            "timestamp":   datetime.now().strftime("%H:%M"),
            "resolved":    False,
        }
        state.maintenance_issues.append(entry)
        state.push_alert(
            f"Maintenance [{priority.upper()}]: {description}",
            priority="urgent" if priority == "urgent" else "normal"
        )
        return f"Maintenance issue logged [{priority}]: \"{description}\". It will appear in the shift summary."

    @function_tool()
    async def get_maintenance_issues() -> str:
        """Get all open unresolved maintenance issues."""
        open_issues = [i for i in state.maintenance_issues if not i["resolved"]]
        if not open_issues:
            return "No open maintenance issues."
        lines = [
            f"[{i['timestamp']}][{i['priority'].upper()}] {i['description']}"
            for i in open_issues
        ]
        return f"{len(open_issues)} open issue{'s' if len(open_issues) != 1 else ''}: " + "; ".join(lines)

    @function_tool()
    async def resolve_maintenance(keyword: str) -> str:
        """Mark a maintenance issue as resolved by matching a keyword from its description."""
        for issue in state.maintenance_issues:
            if keyword.lower() in issue["description"].lower() and not issue["resolved"]:
                issue["resolved"] = True
                return f"Maintenance issue resolved: \"{issue['description']}\""
        return f"No open maintenance issue found matching '{keyword}'."

    @function_tool()
    async def get_shift_summary() -> str:
        """
        Read the full end-of-shift summary.
        Call this whenever a chef asks for the summary, report, or shift overview.
        Covers all notes, stock requests, maintenance issues, expiry and temperature issues.
        """
        sections = []

        if state.notes:
            lines = [f"[{n['timestamp']}][{n['category']}] {n['text']}" for n in state.notes]
            sections.append(f"NOTES ({len(state.notes)}): " + "; ".join(lines))
        else:
            sections.append("NOTES: None recorded this shift.")

        pending_stock = [r for r in state.stock_requests if not r["fulfilled"]]
        if pending_stock:
            lines = [
                f"{r['item']}" + (f" ({r['quantity']})" if r["quantity"] else "") +
                f" [{r['urgency'].upper()}]"
                for r in pending_stock
            ]
            sections.append(f"STOCK NEEDED ({len(pending_stock)}): " + "; ".join(lines))
        else:
            sections.append("STOCK NEEDED: None.")

        open_maint = [i for i in state.maintenance_issues if not i["resolved"]]
        if open_maint:
            lines = [f"{i['description']} [{i['priority'].upper()}]" for i in open_maint]
            sections.append(f"MAINTENANCE TO FIX ({len(open_maint)}): " + "; ".join(lines))
        else:
            sections.append("MAINTENANCE TO FIX: None.")

        expiry = state.check_expiry()
        sections.append("EXPIRY ISSUES: " + ("; ".join(expiry) if expiry else "None."))

        temps = state.check_temperature()
        sections.append("TEMPERATURE ISSUES: " + ("; ".join(temps) if temps else "None."))

        return "End of shift summary — " + " | ".join(sections)

    @function_tool()
    async def get_pending_alerts() -> str:
        """Read out all alerts that have not yet been announced."""
        pending = state.get_pending_alerts()
        if not pending:
            return "No new alerts at this time."
        lines = [f"[{a['timestamp']}][{a['priority'].upper()}] {a['message']}" for a in pending]
        return f"{len(pending)} pending alert{'s' if len(pending) != 1 else ''}: " + "; ".join(lines)


    # ----------------------
    # Create Agent
    # ----------------------

    assistant_agent = Agent(
        instructions="""
        You are Chef Compliance, a kitchen AI assistant built into a restaurant
        kitchen management system. You have a full set of tools available to you.

        YOUR TOOLS ARE REAL AND FULLY FUNCTIONAL. You are NOT a general assistant.
        You are a specialised kitchen system. You CAN and MUST save notes, reminders,
        stock requests and maintenance issues using your tools.

        ABSOLUTE RULES — never break these:

        1. NOTE / REMINDER REQUESTS:
           Any time a chef says "add a note", "save a note", "add a reminder",
           "remember this", "make a note", "note down", or "log this" —
           you MUST call add_note() immediately with the content they gave you.
           NEVER say you cannot save notes. NEVER suggest an external app.
           You have the add_note tool. Use it every single time without exception.

        2. READING NOTES / SUMMARY:
           Any time a chef asks "what are my notes", "read the notes",
           "give me the summary", "shift report", "what was logged today" —
           you MUST call get_notes() or get_shift_summary() immediately.
           NEVER summarise from memory. Always call the tool.

        3. STOCK REQUESTS:
           Any time a chef says they are low on something or need to order something —
           call request_stock() immediately.

        4. MAINTENANCE:
           Any time a chef reports something broken or needing fixing —
           call report_maintenance() immediately.

        5. After every tool call that saves data, confirm to the chef:
           tell them exactly what was saved and that it will appear in the shift summary.

        On startup:
        - Greet the chef as Chef Compliance
        - Call check_temperature and check_food_expiry immediately
        - Report any issues found
        - Tell the chef you can save notes, reminders, stock requests,
          and maintenance issues for their shift

        Tone: professional, formal, concise.
        """,
        tools=[
            set_timer,
            check_temperature,
            update_temperature,
            check_food_expiry,
            add_food_item,
            get_inventory,
            add_note,
            get_notes,
            request_stock,
            get_stock_requests,
            report_maintenance,
            get_maintenance_issues,
            resolve_maintenance,
            get_shift_summary,
            get_pending_alerts,
        ],
    )


    # ----------------------
    # Create Session
    # No external VAD plugin needed — the STT stream handles
    # turn detection automatically via OpenAI's Whisper endpoint.
    # ----------------------

   # then change the session to:
    session = AgentSession(
    stt=STT(language="en"),
    llm=LLM(model="gpt-4o"),
    tts=TTS(),
    vad=silero.VAD.load(),
    )

    await session.start(room=ctx.room, agent=assistant_agent)

    logger.info("Kitchen AI Agent is ready!")


    # ----------------------
    # Greeting
    # ----------------------

    await session.generate_reply(
        instructions="""
        Greet the chef as Chef Compliance.
        Call check_temperature and check_food_expiry immediately.
        Report any issues found clearly.
        Tell the chef you can save notes, reminders, stock requests
        and maintenance issues for their shift summary.
        """
    )


    # ----------------------
    # Background tasks
    # ----------------------

    async def alert_announcer():
        while True:
            await asyncio.sleep(15)
            pending = [
                a for a in state.alert_queue
                if not a["announced"] and a["priority"] == "urgent"
            ]
            for alert in pending:
                alert["announced"] = True
                try:
                    await session.say(f"Urgent alert: {alert['message']}")
                except RuntimeError:
                    return

    async def auto_expiry_checker():
        while True:
            await asyncio.sleep(300)
            warnings = state.check_expiry()
            if warnings:
                for w in warnings:
                    state.push_alert(f"Expiry: {w}", priority="urgent")
                try:
                    await session.say(
                        "Expiry alert: " + "; ".join(warnings) +
                        ". Please review these items immediately."
                    )
                except RuntimeError:
                    return

    async def auto_temp_checker():
        while True:
            await asyncio.sleep(60)
            issues = state.check_temperature()
            if issues:
                for issue in issues:
                    state.push_alert(f"Temperature: {issue}", priority="urgent")
                try:
                    await session.say(
                        "Temperature alert: " + "; ".join(issues) +
                        ". Immediate corrective action required."
                    )
                except RuntimeError:
                    return

    asyncio.create_task(alert_announcer())
    asyncio.create_task(auto_expiry_checker())
    asyncio.create_task(auto_temp_checker())


# ----------------------
# Worker
# ----------------------

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            worker_type="room",
        )
    )
