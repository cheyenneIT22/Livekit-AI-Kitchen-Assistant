# AIKA — AI Kitchen Assistant

A real-time voice AI assistant for restaurant kitchens, built with LiveKit Agents and OpenAI. Chefs interact entirely by voice to manage food safety, inventory, timers, notes, and shift logs.

---

## Prerequisites

Before you start you will need accounts and API keys from:

- **OpenAI** — [platform.openai.com](https://platform.openai.com) (paid credits required)
- **LiveKit Cloud** — [livekit.io](https://livekit.io) (free tier available)
  - After signing up, create a project and copy your `URL`, `API Key`, and `API Secret` from the dashboard

---

## Files

| File | Purpose |
|------|---------|
| `agent.py` | The AI agent — all voice tools and kitchen logic |
| `worker.py` | Connects the agent to LiveKit Cloud |
| `token_server.py` | Small web server that lets browsers connect |
| `index.html` | Browser interface — open in Chrome, Firefox, etc. |

---

## Step 1 — Clone the repo

```bash
git clone https://github.com/your-username/your-repo-name.git
cd your-repo-name
```

---

## Step 2 — Create a virtual environment (recommended)

```bash
# Mac / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

---

## Step 3 — Install dependencies

```bash
pip install livekit-agents livekit-plugins-openai livekit-plugins-silero \
            python-dotenv flask flask-cors livekit-api
```

---

## Step 4 — Create your .env file

Create a file called `.env` in the project root folder (same folder as `agent.py`) and add your credentials:

```
OPENAI_API_KEY=your_openai_api_key
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
```

> **Where to find these:**
> - `OPENAI_API_KEY` → [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
> - `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` → LiveKit Cloud dashboard → Settings → API Keys

---

## Step 5 — Run the agent

You need **two terminals** open at the same time.

**Terminal 1 — Start the AI agent:**
```bash
python worker.py dev
```

You should see:
```
INFO: starting worker
INFO: registered worker
```

**Terminal 2 — Start the token server (required for browser access):**
```bash
python token_server.py
```

You should see:
```
Chef Compliance — Token Server
Running : http://localhost:5000
```

---

## Step 6 — Open the browser interface

Open `index.html` directly in your browser (double-click the file), or serve it locally:

```bash
python -m http.server 8080
# then open http://localhost:8080/index.html
```

1. Click **Enter Kitchen** on the overlay
2. Enter your name and click **Join Kitchen**
3. Allow microphone access when the browser asks
4. AIKA will greet you and begin monitoring

---

## Testing on multiple browsers at the same time

To test with Chrome and Firefox simultaneously:
- Open `index.html` in Chrome → enter name `Marco`, room `kitchen` → Connect
- Open `index.html` in Firefox → enter name `Anna`, room `kitchen` → Connect

Both connect to the same agent. Each chef can speak to AIKA independently.

---

## Example voice commands

| Say | What happens |
|-----|-------------|
| *"AIKA, set a timer 10 minutes for the lamb"* | Starts a named timer |
| *"AIKA, check temperatures"* | Reports all storage temps |
| *"AIKA, add a note we are low on cream, category reminder"* | Saves a shift note |
| *"AIKA, give me the shift summary"* | Reads full end-of-shift report |
| *"AIKA, request stock: chicken breast, 5 kilos, urgent"* | Logs a stock request |
| *"AIKA, report maintenance: oven thermostat is off, urgent"* | Logs a maintenance issue |
| *"AIKA, remove chicken from inventory"* | Asks for confirmation then deletes |
| *"AIKA, clear all expired items"* | Auto-removes expired inventory |

---

## Deploying on a server (VPS)

```bash
# SSH into your server, then:

# Install Python if needed
sudo apt update && sudo apt install python3 python3-pip python3-venv -y

# Clone the repo
git clone https://github.com/your-username/your-repo-name.git
cd your-repo-name

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install livekit-agents livekit-plugins-openai livekit-plugins-silero \
            python-dotenv flask flask-cors livekit-api

# Create your .env file
nano .env
# Paste your credentials, then Ctrl+X → Y → Enter to save

# Run the agent in the background using screen
screen -S aika-agent
python3 worker.py start
# Press Ctrl+A then D to detach (agent keeps running)

# Run the token server in a second screen
screen -S aika-tokens
python3 token_server.py
# Press Ctrl+A then D to detach
```

> **Note:** No inbound ports are required. The agent connects outbound to LiveKit Cloud. The token server runs on port 5000 — if you want browsers outside your local network to connect, open port 5000 in your server's firewall.

To reconnect to a running screen session:
```bash
screen -r aika-agent
screen -r aika-tokens

## Troubleshooting

**`ModuleNotFoundError: No module named 'livekit'`**
→ Run the pip install command again inside your virtual environment.

**`ImportError: cannot import name 'silero'`**
→ Run `pip install livekit-plugins-silero`

**Agent starts but can't hear me**
→ Check your browser allowed microphone access. Click the 🔒 lock icon in the address bar and set Microphone to Allow, then refresh.

**OpenAI 429 error (quota exceeded)**
→ Add credits to your OpenAI account at [platform.openai.com/billing](https://platform.openai.com/billing)

**Agent is running the old version after updating code**
→ Press Ctrl+C to stop the worker, then restart with `python worker.py dev`. Disconnect and reconnect in the browser to start a fresh session.
