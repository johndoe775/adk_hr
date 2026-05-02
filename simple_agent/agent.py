from google.adk import Agent
import yaml
from pathlib import Path
from dotenv import load_dotenv
from collections import deque

load_dotenv()

# ---------------------------
# Paths
# ---------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_FILE = PROJECT_ROOT / "src" / "prompts.yaml"
RESUME_FILE = PROJECT_ROOT / "src" / "Resume_auto_fill_md_format.txt"

# ---------------------------
# Load YAML
# ---------------------------
with open(PROMPTS_FILE, "r") as f:
    data = yaml.safe_load(f)

# ---------------------------
# Load resume (optional context)
# ---------------------------
with open(RESUME_FILE, "r") as f:
    resume = f.read()

# ---------------------------
# Formatter (cleaned)
# ---------------------------
def formatter(text: str) -> str:
    """
    Keeps at most 2 levels of curly braces content.
    Prevents malformed prompt templates from breaking.
    """
    c=1
    s=""
    for i in text:
        if i!="{" and i!="}":
            s+=i
    
        elif  (i=="{" or i=="}"):
            c+=1
            if c<=3:
                s+=i
    return s

# ---------------------------
# Agent factory
# ---------------------------
def create_agent(name: str, prompt: str, description: str) -> Agent:
    safe_prompt = formatter(prompt).replace("{resume}", resume)

    return Agent(
        name=name,
        model="gemini-2.5-flash",
        instruction=safe_prompt,
        description=description.strip()
    )
# ---------------------------
# Build sub-agents
# ---------------------------
agents = []

for name, cfg in data.items():
    if name == "root_agent":
        continue  # skip root definition if present in YAML

    prompt = cfg.get("prompt", "").strip()
    description = cfg.get("tool_use_case", "").strip()

    if not prompt or not description:
        continue  # skip invalid entries

    agents.append(create_agent(name, prompt, description))

# ---------------------------
# Root agent
root_agent = Agent(
    name="root_orchestrator",
    model="gemini-2.5-flash",
    instruction=f"""
You are a coordinator agent responsible for delegating tasks to sub-agents.

Available sub-agents:
{chr(10).join([f"- {a.name}: {a.description}" for a in agents])}

Execution protocol:
1. Carefully read and fully understand the user's query
2. Identify the single most appropriate sub-agent
3. Delegate the task to ONLY that sub-agent
4. Return the sub-agent's response as the final answer

Rules:
- You MUST understand the user's intent clearly before selecting an agent
- You MUST select exactly ONE sub-agent
- Do NOT call multiple agents
- Do NOT partially answer the query yourself
- Prefer the most specific and relevant agent
- If no suitable agent exists, respond exactly:
  "No suitable agent found"
""",
    sub_agents=agents
)