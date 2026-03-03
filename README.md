# Kitchen AI Voice Assistant

An AI-powered real-time kitchen compliance voice assistant built using LiveKit Agents and OpenAI.

This assistant monitors:

Fridge & freezer temperatures

-Food expiry dates

 -Kitchen timers

 -Inventory tracking

It supports voice interaction via LiveKit Playground and can run locally or on a cloud server.

# Features

Real-time voice interaction (STT + TTS)

AI-powered responses via OpenAI

Function calling (tool execution)

Background monitoring alerts

Async Python architecture

Production-ready deployment support

# Tech Stack

Python 3.11

LiveKit Agents (v1.4.3)

OpenAI API

AsyncIO

dotenv
# Environment Variables

Created a .env file in the project root:

OPENAI_API_KEY=your_openai_key
LIVEKIT_URL=wss://your_livekit_url
LIVEKIT_API_KEY=your_livekit_key
LIVEKIT_API_SECRET=your_livekit_secret
# Architecture
User (Voice)
    ↓
LiveKit Playground
    ↓
LiveKit Cloud
    ↓
Kitchen AI Agent (Python Worker)
    ↓
OpenAI API
# Deployment
The agent can be deployed on:
VPS (DigitalOcean, AWS, Hetzner)
Docker container
Cloud VM
Private server
No inbound ports required. The agent connects outbound to LiveKit Cloud.
# Project Status
Active development – built as a LiveKit AI voice assistant demo with production deployment capability.
