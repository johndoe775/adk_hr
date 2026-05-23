import os

from google.adk import Agent
from google import genai
from google.genai import types

import yaml
from pathlib import Path
from dotenv import load_dotenv

# =========================================================
# Environment
# =========================================================

load_dotenv()

api_key=os.getenv("GOOGLE_API_KEY") 

# =========================================================
# Paths
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROMPTS_FILE = PROJECT_ROOT / "src" / "prompts.yaml"

RESUME_FILE = (
    PROJECT_ROOT
    / "my_data"
    / "Resume_auto_fill_md_format.txt"
)

# =========================================================
# Load YAML prompts
# =========================================================

with open(PROMPTS_FILE, "r") as f:
    data = yaml.safe_load(f)

# =========================================================
# Load resume
# =========================================================

with open(RESUME_FILE, "r") as f:
    resume = f.read().strip()

# =========================================================
# Gemini Client
# =========================================================

client = genai.Client(api_key=api_key)

# =========================================================
# Create shared context cache
# =========================================================

shared_context = f"""
Candidate Resume Information

{resume}
"""

cache = client.caches.create(
    model="gemini-2.5-flash",
    

    config=types.CreateCachedContentConfig(
        display_name="resume_context_cache",

        contents=[
            shared_context
                ]
            
        ,

        ttl="3600s"  # 1 hour
    )
)

CACHE_NAME = cache.name

print(f"Cache created: {CACHE_NAME}")

# =========================================================
# Agent factory
# =========================================================

def create_agent(
    name: str,
    prompt: str,
    description: str
) -> Agent:

    return Agent(
        name=name,

        model="gemini-2.5-flash",

        instruction=prompt.strip(),

        description=description.strip(),

        generate_content_config={
            "cached_content": CACHE_NAME
        }
    )

# =========================================================
# Build sub-agents
# =========================================================

agents = []

for name, cfg in data.items():

    if name == "root_agent":
        continue

    prompt = cfg.get("prompt", "")
    description = cfg.get("tool_use_case", "")

    if not prompt or not description:
        continue

    agent = create_agent(
        name=name,
        prompt=prompt,
        description=description
    )

    agents.append(agent)

# =========================================================
# Root Orchestrator
# =========================================================

root_agent = Agent(
    name="root_orchestrator",

    model="gemini-2.5-flash",

    instruction=f"""
You are a coordinator agent.

Your responsibility is to route the user's request
to the SINGLE most appropriate sub-agent.

Available sub-agents:

{chr(10).join(
    [f"- {a.name}: {a.description}" for a in agents]
)}

Execution Rules:

1. Carefully understand the user's intent
2. Select ONLY ONE best sub-agent
3. Delegate the task entirely
4. Return the delegated response directly

Constraints:

- Never call multiple agents
- Never partially answer yourself
- Always prefer the most specialized agent
- If no suitable agent exists, respond exactly:
  "No suitable agent found"
""",

    sub_agents=agents
)

# =========================================================
# Export
# =========================================================

