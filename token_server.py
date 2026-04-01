"""
Token Server — Chef Compliance
================================
Gives browser clients a LiveKit access token so they can connect
directly without needing Python installed.

Install:
    pip install flask flask-cors livekit-api

Run:
    python token_server.py

Then open index.html in any browser.
"""

import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from livekit.api import AccessToken, VideoGrants

load_dotenv()

app = Flask(__name__)
CORS(app)

LIVEKIT_URL        = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")


@app.route("/token")
def get_token():
    username = request.args.get("username", "chef").strip().lower()
    if not username:
        return jsonify({"error": "username required"}), 400

    # Each user gets their own room: kitchen-{username}
    room_name = f"kitchen-{username}"

    if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        return jsonify({"error": "LiveKit credentials missing from .env"}), 500

    token = (
        AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(username)
        .with_name(username.title())
        .with_grants(VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )

    return jsonify({
        "token":       token,
        "room":        room_name,
        "livekit_url": LIVEKIT_URL,
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "livekit_url": LIVEKIT_URL})


if __name__ == "__main__":
    print("\n" + "="*45)
    print("  Chef Compliance — Token Server")
    print("="*45)
    print(f"  LiveKit : {LIVEKIT_URL}")
    print(f"  Running : http://localhost:5000")
    print("="*45 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
