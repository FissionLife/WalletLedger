# Role 2: LangGraph Agent Workflow
# Assigned to: Gopal
from typing import Any


async def process_user_interaction(
    chat_id: str, text: str, attachments: list[Any] | None = None
) -> str:
    """
    Contract 1: Processes incoming user messages through LangGraph StateGraph.

    Steps for Gopal (Role 2):
    1. Intent classification (expense log, balance query, report, API key setup).
    2. Invoke Meet's MCP tools (Role 4) when data changes or queries are required.
    3. Invoke Komal's AI Gateway (Role 3) for reasoning and natural language synthesis.
    4. Return final formatted Markdown response for Telegram.
    """
    clean_text = text.strip() if text else ""
    return (
        f'🤖 [LangGraph Mock Agent] Received message: "{clean_text}"\n'
        f"Gopal (Role 2) will implement the full StateGraph workflow here!"
    )


# Backward compatibility
def process_message(chat_id: str, text: str) -> str:
    return f"Echo: {text}"
