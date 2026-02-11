from dotenv import load_dotenv
load_dotenv()

from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins.openai import OpenAILLM, OpenAISTTS, OpenAISTT


KITCHEN_PROMPT = """
You are a friendly kitchen voice assistant.

You help with:
- Cooking times
- Simple recipes
- Food safety
- Substitutions
- Measurements

Keep answers short, clear, and practical.
Speak like a calm, helpful kitchen assistant.
"""


async def entrypoint(ctx: JobContext):
    agent = VoicePipelineAgent(
        stt=OpenAISTT(),
        llm=OpenAILLM(
            model="gpt-4o-mini",
            system_prompt=KITCHEN_PROMPT,
        ),
        tts=OpenAISTTS(voice="alloy"),
    )

    await agent.start(ctx.room)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )
