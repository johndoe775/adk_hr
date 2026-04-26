from google.adk import Agent
import yaml
from pathlib import Path
import os
#from google.adk.models.lite_llm import LiteLlm
from dotenv import load_dotenv
load_dotenv()

#groq = os.getenv("groq")
# Paths
PROJECT_ROOT = Path(__file__).parent.parent
PROMPTS_FILE = PROJECT_ROOT / "src" / "prompts.yaml"
RESUME_FILE = PROJECT_ROOT / "src" / "Resume_auto_fill_md_format.txt"


# Load YAML
with open(PROMPTS_FILE, "r") as f:
    data = yaml.safe_load(f)


# Build tool descriptions string (LLM-friendly)
tool_descriptions = "\n".join([
    f"- {k}: {v.get('tool_use_case','')}"
    for k, v in data.items() if k != "root_agent"
])


# Load resume
with open(RESUME_FILE, "r") as f:
    resume = f.read()


# Create sub-agents
agents = {}

for key, config in data.items():
    if key == "root_agent":
        continue

    agents[key] = Agent(
        name=key,
        model="gemini-2.5-pro",
        description=config.get("tool_use_case", ""),
        instruction=config.get("prompt", "")
    )


# Root agent
root_agent = Agent(
    name="root_agent",
    model="gemini-2.5-pro",
    description="Routes user queries to the correct sub-agent.",
    instruction=f"""
You are a routing agent.

Your job:
1. Understand the user query
2. Select the most relevant sub-agent
3. Delegate the task

Available sub-agents:
{tool_descriptions}

User resume:
{resume}

Rules:
- Match query intent to tool_use_case
- Choose ONLY one best agent
- Do NOT answer yourself
- Always delegate to a sub-agent

Output:
Return ONLY the final response from the selected sub-agent.
""",
    sub_agents=list(agents.values())
)