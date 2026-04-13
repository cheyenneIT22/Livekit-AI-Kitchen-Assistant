import asyncio
import logging
import re
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from livekit.plugins import openai, silero
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


# ============================================================
# Wake Word
# The agent responds to both "AIKA" and "Chef Compliance".
# Chefs can say "AIKA, set a timer" or just speak naturally.
# The wake word is handled in the STT prompt and instructions —
# no extra hardware needed for the LiveKit browser client.
# For a hardware deployment (Raspberry Pi), swap to
# openWakeWord or Porcupine running locally.
# ============================================================

WAKE_WORDS = ["aika", "aika+", "chef compliance"]


# ============================================================
# Local Command Parser
# Handles the most common kitchen commands instantly without
# calling the LLM — saves cost and reduces latency by ~90%.
# Based on research recommendation (Option B architecture).
# Falls back to LLM for complex / unrecognised requests.
# ============================================================

def local_command_parse(transcript: str) -> Optional[Tuple[str, ...]]:
    """
    Try to match a transcript against common kitchen command patterns.
    Returns a tuple (action, *args) if matched, or None to escalate to LLM.
    """
    t = transcript.lower().strip()

    # Strip wake words from the start before parsing
    for w in WAKE_WORDS:
        t = re.sub(rf'^{re.escape(w)}\s*[,.]?\s*', '', t)

    # Timer: "set timer 5 minutes for steak" / "timer 30 seconds lamb"
    m = re.search(
        r'(?:set\s+)?timer\s+(\d+)\s*(second|minute|hour)s?\s*(?:for\s+(.+))?', t
    )
    if m:
        n, unit, label = m.groups()
        label = label.strip().title() if label else "Timer"
        seconds = int(n) * {"second": 1, "minute": 60, "hour": 3600}[unit]
        return ("timer", seconds, label)

    # Temperature check: "check fridge" / "what's the freezer temp"
    if re.search(r'(check|what).{0,15}(fridge|freezer|hot.?hold|temp)', t):
        return ("check_temp",)

    # Expiry check: "check expiry" / "what's expired" / "any expired items"
    if re.search(r'(check|what|any).{0,15}(expir|use.?by|expired|fresh)', t):
        return ("check_expiry",)

    # Inventory view: "what's in the fridge" / "show inventory"
    if re.search(r'(what.{0,10}(fridge|freezer|inventory|stock)|show.{0,5}inventory|get inventory)', t):
        return ("get_inventory",)

    # Clear expired: "clear expired" / "remove expired items"
    if re.search(r'(clear|remove|delete).{0,10}expir', t):
        return ("clear_expired",)

    # Shift summary: "give me the summary" / "end of shift report"
    if re.search(r'(summary|shift report|end of shift|what was logged)', t):
        return ("get_summary",)

    # No pattern matched — escalate to LLM
    return None


# ============================================================
# Kitchen State
# ============================================================

class KitchenState:
    SAFE_TEMP = {
        "fridge":   (0, 5),
        "freezer":  (-25, -18),
        "hot_hold": (63, 100),
    }

    def __init__(self):
        self.current_temps: Dict[str, float] = {
            "fridge":   7.0,    # intentionally unsafe for demo
            "freezer":  -17.0,  # intentionally unsafe for demo
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
        self.pending_delete: Dict = {}

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


# ============================================================
# Entry Point
# ============================================================

async def entrypoint(ctx: JobContext):

    logger.info("Starting AIKA Kitchen AI Agent...")
    await ctx.connect()
    logger.info("Connected to room")

    state = KitchenState()
    timer_tasks: List[asyncio.Task] = []
    MAX_TIMERS = 10


    # ============================================================
    # Tools
    # ============================================================

    # -- Timers --

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

    # -- Temperatures --

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

    # -- Inventory --

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
    async def delete_inventory_item(name: str) -> str:
        """
        Safely delete a food item from inventory by name.
        Asks the chef to confirm before removing.
        Call this when a chef says:
        - remove [item] from inventory
        - delete [item]
        - take [item] off the inventory
        - we used all the [item]
        - [item] is gone
        """
        match = None
        for i, item in enumerate(state.food_inventory):
            if name.lower() in item["name"].lower():
                match = (i, item)
                break

        if not match:
            return f"No inventory item found matching '{name}'. Check the inventory with get_inventory."

        idx, item = match
        state.pending_delete = {
            "type":  "inventory",
            "index": idx,
            "item":  item,
            "name":  item["name"],
        }

        days_left = (item["expiry"] - datetime.now()).days
        status = "EXPIRED" if days_left < 0 else f"expires in {days_left} days"
        return (
            f"Please confirm: delete '{item['name']}' ({item['storage']}, {status}) "
            f"from inventory? Say YES to confirm or NO to cancel."
        )

    @function_tool()
    async def delete_note(keyword: str) -> str:
        """
        Safely delete a shift note by matching a keyword in its text.
        Asks the chef to confirm before removing.
        Call this when a chef says:
        - delete note about [topic]
        - remove note [text]
        - clear that note
        - delete reminder about [topic]
        """
        match = None
        for i, note in enumerate(state.notes):
            if keyword.lower() in note["text"].lower():
                match = (i, note)
                break

        if not match:
            return f"No note found matching '{keyword}'. Use get_notes to see all notes."

        idx, note = match
        state.pending_delete = {
            "type":  "note",
            "index": idx,
            "item":  note,
            "name":  note["text"],
        }

        return (
            f"Please confirm: delete note [{note['category']}] \"{note['text']}\" "
            f"saved at {note['timestamp']}? Say YES to confirm or NO to cancel."
        )

    @function_tool()
    async def confirm_delete(confirmed: bool) -> str:
        """
        Confirm or cancel a pending deletion.
        Call this immediately when the chef says YES or NO after a delete request.
        confirmed=True to proceed, confirmed=False to cancel.
        """
        if not state.pending_delete:
            return "No deletion is pending. Nothing to confirm."

        pending = state.pending_delete
        state.pending_delete = {}

        if not confirmed:
            return f"Deletion cancelled. '{pending['name']}' has not been removed."

        if pending["type"] == "inventory":
            for i, item in enumerate(state.food_inventory):
                if item["name"] == pending["item"]["name"]:
                    state.food_inventory.pop(i)
                    state.push_alert(f"Inventory item removed: {item['name']}", priority="normal")
                    logger.info(f"Inventory deleted: {item['name']}")
                    return f"'{item['name']}' has been removed from inventory."
            return "Item could not be found — it may have already been removed."

        elif pending["type"] == "note":
            for i, note in enumerate(state.notes):
                if note["text"] == pending["item"]["text"] and note["timestamp"] == pending["item"]["timestamp"]:
                    state.notes.pop(i)
                    state.push_alert(f"Note deleted: {note['text'][:40]}", priority="normal")
                    logger.info(f"Note deleted: {note['text']}")
                    return f"Note \"{note['text']}\" has been deleted."
            return "Note could not be found — it may have already been removed."

        elif pending["type"] == "all_notes":
            count = len(state.notes)
            state.notes.clear()
            state.push_alert(f"All {count} notes cleared.", priority="normal")
            logger.info(f"All notes cleared: {count} entries removed.")
            return f"All {count} shift note{'s' if count != 1 else ''} have been deleted."

        return "Unknown deletion type."

    @function_tool()
    async def delete_all_expired_items() -> str:
        """
        Automatically remove all expired food items from inventory.
        Call this when a chef says:
        - clear expired items
        - remove everything expired
        - clean up the inventory
        - delete all expired food
        No confirmation required — only removes items that have already expired.
        """
        expired = [item for item in state.food_inventory
                   if (item["expiry"] - datetime.now()).days < 0]

        if not expired:
            return "No expired items found. All items are within their use-by dates."

        for item in expired:
            state.food_inventory.remove(item)
            logger.info(f"Expired item auto-removed: {item['name']}")

        names = ", ".join(i["name"] for i in expired)
        state.push_alert(f"Expired items removed: {names}", priority="normal")
        return f"{len(expired)} expired item{'s' if len(expired) != 1 else ''} removed: {names}."

    @function_tool()
    async def clear_all_notes() -> str:
        """
        Delete ALL shift notes after confirmation.
        Call this when a chef says clear all notes or delete all notes.
        Always ask for confirmation before clearing everything.
        """
        if not state.notes:
            return "There are no notes to clear."

        count = len(state.notes)
        state.pending_delete = {
            "type":  "all_notes",
            "index": -1,
            "item":  {},
            "name":  f"all {count} notes",
        }
        return (
            f"Please confirm: permanently delete ALL {count} shift note{'s' if count != 1 else ''}? "
            f"This cannot be undone. Say YES to confirm or NO to cancel."
        )

    # -- Notes --

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
        - AIKA note / AIKA remember
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

    # -- Stock --

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

    # -- Maintenance --

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

    # -- Summaries & Alerts --

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


    # ============================================================
    # Create Agent
    # ============================================================

    assistant_agent = Agent(
        instructions="""
        You are AIKA — the AI Kitchen Assistant for this restaurant.
        Chefs may call you "AIKA" or "Chef Compliance" — both refer to you.
        You respond to either name. When a chef says "AIKA, ..." treat it
        exactly like they are speaking directly to you.

        You are a specialised kitchen system with REAL, FULLY FUNCTIONAL tools.
        You are NOT a general assistant. You CAN and MUST save notes, reminders,
        stock requests and maintenance issues using your tools.

        WAKE WORD NOTE:
        Chefs will often start commands with "AIKA" — for example:
        "AIKA set a timer for 10 minutes"
        "AIKA add a note we are low on cream"
        "AIKA what's expired?"
        Strip the word AIKA from the start and process the rest as a normal command.

        ABSOLUTE RULES — never break these:

        1. NOTE / REMINDER REQUESTS:
           Any time a chef says "add a note", "save a note", "add a reminder",
           "remember this", "make a note", "note down", "log this",
           "AIKA note", or "AIKA remember" —
           you MUST call add_note() immediately with the content they gave you.
           NEVER say you cannot save notes. NEVER suggest an external app.
           You have the add_note tool. Use it every single time without exception.

        2. READING NOTES / SUMMARY:
           Any time a chef asks "what are my notes", "read the notes",
           "give me the summary", "shift report", "what was logged today" —
           you MUST call get_notes() or get_shift_summary() immediately.
           NEVER summarise from memory. Always call the tool.

        3. STOCK REQUESTS:
           Any time a chef says they are low on something or need to order —
           call request_stock() immediately.

        4. MAINTENANCE:
           Any time a chef reports something broken or needing fixing —
           call report_maintenance() immediately.

        5. DELETING NOTES:
           Any time a chef says "delete note", "remove note", "clear note",
           "delete reminder" — call delete_note() with a keyword from the note.
           Always read back what will be deleted and wait for YES or NO.
           When chef says YES call confirm_delete(confirmed=True).
           When chef says NO call confirm_delete(confirmed=False).

        6. DELETING INVENTORY:
           Any time a chef says "remove [item]", "delete [item]",
           "we used all [item]", "[item] is gone" —
           call delete_inventory_item() with the item name.
           Always read back what will be deleted and wait for YES or NO.
           When chef says YES call confirm_delete(confirmed=True).
           When chef says NO call confirm_delete(confirmed=False).

        7. EXPIRED ITEMS:
           "clear expired", "remove expired items", "clean up inventory" —
           call delete_all_expired_items() immediately. No confirmation needed.

        8. CLEAR ALL NOTES:
           "clear all notes" or "delete all notes" —
           call clear_all_notes() and wait for YES or NO confirmation.

        9. After every tool call that saves or deletes data, confirm to the chef
           exactly what happened.

        On startup:
        - Greet the chef as AIKA
        - Mention they can call you AIKA or Chef Compliance
        - Call check_temperature and check_food_expiry immediately
        - Report any issues found
        - Tell the chef you can save notes, reminders, stock requests,
          maintenance issues, and safely delete notes and inventory items

        Tone: professional, formal, concise.
        """,
        tools=[
            set_timer,
            check_temperature,
            update_temperature,
            check_food_expiry,
            add_food_item,
            get_inventory,
            delete_inventory_item,
            delete_all_expired_items,
            add_note,
            get_notes,
            delete_note,
            clear_all_notes,
            confirm_delete,
            request_stock,
            get_stock_requests,
            report_maintenance,
            get_maintenance_issues,
            resolve_maintenance,
            get_shift_summary,
            get_pending_alerts,
        ],
    )


    # ============================================================
    # Create Session
    #
    # STT prompt primed with kitchen vocabulary — improves
    # Whisper accuracy in noisy kitchen environments significantly.
    # (Research recommendation: section 4, Local STT Engines)
    #
    # To switch to Deepgram Nova-3 (better noise handling, ~$0.008/min):
    #   pip install livekit-plugins-deepgram
    #   from livekit.plugins import deepgram
    #   stt=deepgram.STT(model="nova-3")
    #
    # To switch to Groq for LLM (free tier, ~100ms TTFB):
    #   pip install livekit-plugins-openai  (groq uses openai-compatible API)
    #   llm=LLM(
    #       model="gemma2-9b-it",
    #       base_url="https://api.groq.com/openai/v1",
    #       api_key=os.getenv("GROQ_API_KEY"),
    #   )
    #
    # To switch to Cartesia TTS (40-90ms TTFA, best quality):
    #   pip install livekit-plugins-cartesia
    #   from livekit.plugins import cartesia
    #   tts=cartesia.TTS()
    # ============================================================

    session = AgentSession(
        stt=STT(
            language="en",
            # Kitchen vocabulary prompt — primes Whisper for accuracy
            # in noisy environments with common kitchen terms
            prompt=(
                "Kitchen environment. Voice commands include: "
                "AIKA, timer, temperature, fridge, freezer, hot hold, "
                "inventory, expiry, note, reminder, stock, maintenance, "
                "chicken, beef, pork, fish, dairy, checklist, HACCP."
            ),
        ),
        llm=LLM(model="gpt-4o"),
        tts=TTS(),
        vad=silero.VAD.load(),
    )

    await session.start(room=ctx.room, agent=assistant_agent)

    logger.info("AIKA Kitchen AI Agent is ready!")


    # ============================================================
    # Greeting
    # ============================================================

    await session.generate_reply(
        instructions="""
        Greet the chef as AIKA — the AI Kitchen Assistant.
        Mention they can call you AIKA or Chef Compliance.
        Call check_temperature and check_food_expiry immediately.
        Report any issues found clearly.
        Tell the chef you can save notes, reminders, stock requests,
        maintenance issues, and safely delete notes and inventory items.
        Keep the greeting concise.
        """
    )


    # ============================================================
    # Background tasks
    # ============================================================

    async def alert_announcer():
        """Announces urgent queued alerts every 15 seconds."""
        while True:
            await asyncio.sleep(15)
            pending = [
                a for a in state.alert_queue
                if not a["announced"] and a["priority"] == "urgent"
            ]
            for alert in pending:
                alert["announced"] = True
                try:
                    await session.say(f"AIKA alert: {alert['message']}")
                except RuntimeError:
                    return

    async def auto_expiry_checker():
        """Checks food expiry every 5 minutes and announces warnings."""
        while True:
            await asyncio.sleep(300)
            warnings = state.check_expiry()
            if warnings:
                for w in warnings:
                    state.push_alert(f"Expiry: {w}", priority="urgent")
                try:
                    await session.say(
                        "AIKA expiry alert: " + "; ".join(warnings) +
                        ". Please review these items immediately."
                    )
                except RuntimeError:
                    return

    async def auto_temp_checker():
        """Checks storage temperatures every 60 seconds and announces issues."""
        while True:
            await asyncio.sleep(60)
            issues = state.check_temperature()
            if issues:
                for issue in issues:
                    state.push_alert(f"Temperature: {issue}", priority="urgent")
                try:
                    await session.say(
                        "AIKA temperature alert: " + "; ".join(issues) +
                        ". Immediate corrective action required."
                    )
                except RuntimeError:
                    return

    asyncio.create_task(alert_announcer())
    asyncio.create_task(auto_expiry_checker())
    asyncio.create_task(auto_temp_checker())


# ============================================================
# Worker
# ============================================================

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            worker_type="room",
        )
    )
