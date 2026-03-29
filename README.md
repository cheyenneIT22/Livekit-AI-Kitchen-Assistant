# Chef Compliance — Kitchen AI Voice Assistant

An AI-powered real-time kitchen compliance voice assistant built using LiveKit Agents and OpenAI. Designed for restaurant kitchens, it monitors food safety, tracks inventory, manages timers, and logs shift notes — all via voice.

---

## Features

### Voice & AI
- Real-time voice interaction (Speech-to-Text + Text-to-Speech via OpenAI)
- AI-powered responses via GPT-4o with function/tool calling
- Voice activity detection via Silero VAD
- Interruptible, natural conversation flow
- Multi-user support — multiple chefs can connect simultaneously from any browser

### Food Safety & Compliance
- Live temperature monitoring — fridge, freezer, hot hold
- Safe temperature range enforcement with automatic alerts
- Food expiry tracking with near-expiry and expired warnings
- HACCP cooking compliance checks (chicken, beef, pork, fish, eggs, vegetables)
- Background monitoring — temperature checked every 60s, expiry every 5 minutes
- Urgent alerts announced automatically by voice

### Inventory Management
- Add food items with expiry dates and storage location
- View full inventory with expiry status
- Safe delete with voice confirmation — won't delete without chef saying YES
- Auto-remove all expired items with a single voice command

### Shift Notes & Logging
- Save shift notes by voice — general, handover, reminder categories
- Read back notes at any time
- Delete individual notes with confirmation
- Clear all notes with confirmation
- Full compliance log of all actions

### Stock & Maintenance
- Log stock requests by voice with urgency levels (normal / urgent)
- Report maintenance issues (broken equipment, adjustments needed)
- Resolve maintenance issues by voice
- All items appear in end-of-shift summary

### End-of-Shift Summary
- Full shift report covering notes, stock needed, maintenance issues, expiry warnings, and temperature issues
- Available on demand by voice at any time

### Browser Client (index.html)
- Works in Chrome, Firefox, Safari, Edge — any modern browser
- No installation needed for chefs — just open the page
- Live voice visualiser showing when agent is speaking
- Real-time alerts panel
- Conversation transcript
- Microphone mute/unmute button
- Debug log for troubleshooting

---

## Voice Commands (Examples)

| Action | Say |
|--------|-----|
| Add a note | *"Add a note: we are low on olive oil, category reminder"* |
| Read notes | *"What are my notes?"* or *"Read the shift notes"* |
| Delete a note | *"Delete the note about olive oil"* → confirm YES |
| Shift summary | *"Give me the end of shift summary"* |
| Check temperatures | *"Check temperatures"* |
| Update temperature | *"Update fridge temperature to 4 degrees"* |
| Add inventory | *"Add chicken breast, expires in 3 days, fridge"* |
| Delete inventory | *"Remove chicken from inventory"* → confirm YES |
| Clear expired | *"Clear all expired items"* |
| Request stock | *"Request stock: cream, 2 litres, urgent"* |
| Log maintenance | *"Report maintenance: oven thermostat is off, urgent"* |
| Set timer | *"Set a 15 minute timer for the lamb"* |
| HACCP check | *"HACCP check: chicken, 78 degrees, 150 seconds"* |

---

## Tech Stack

- Python 3.11
- LiveKit Agents v1.4+
- OpenAI API (GPT-4o, Whisper STT, TTS)
- Silero VAD (voice activity detection)
- Flask + flask-cors (token server)
- AsyncIO
- python-dotenv

---

## Project Files

| File | Purpose |
|------|---------|
| `agent.py` | Main AI agent — all tools, state, background monitoring |
| `worker.py` | LiveKit worker entry point |
| `token_server.py` | Flask server that issues browser tokens |
| `index.html` | Browser client — open in any browser |
| `.env` | Credentials (not committed to git) |

---

## Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_key
LIVEKIT_URL=wss://your_livekit_url
LIVEKIT_API_KEY=your_livekit_key
LIVEKIT_API_SECRET=your_livekit_secret
```

---

## Installation

```bash
pip install livekit-agents livekit-plugins-openai livekit-plugins-silero \
            python-dotenv flask flask-cors livekit-api
```

---

## Running Locally

```bash
# Terminal 1 — AI agent
python worker.py dev

# Terminal 2 — token server for browser clients
python token_server.py

# Then open index.html in any browser
```

---

## Running on a Server

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install livekit-agents livekit-plugins-openai livekit-plugins-silero \
            python-dotenv flask flask-cors livekit-api

# Run agent
python3 worker.py dev
```

No inbound ports required. The agent connects outbound to LiveKit Cloud.

For production, run the agent as a background service using `systemd` or `screen`:

```bash
# Using screen
screen -S chef-compliance
python3 worker.py start
# Ctrl+A then D to detach
```

---

## Architecture

```
Chef (Voice via Browser)
        ↓
   index.html (any browser)
        ↓
  token_server.py (Flask)
        ↓
   LiveKit Cloud
        ↓
  agent.py (Python Worker)
        ↓
   OpenAI API (GPT-4o)

 ## Project Status

Active development — production-ready restaurant kitchen AI voice assistant with multi-user browser support, full compliance tooling, and server deployment capability.
