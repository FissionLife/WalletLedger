# Role 4: MCP Server Integration
# Exposes internal Payment API tools to LangGraph so the LLM can trigger actions

def get_balance_tool(customer_id: str):
    """
    MCP Tool: Get wallet balance for a user.
    """
    # TODO: Call existing services.py get_wallet
    pass

def log_expense_tool(customer_id: str, amount: float, category: str):
    """
    MCP Tool: Log a new expense (order/transaction) for a user.
    """
    # TODO: Call existing services.py process_order or create new expense model
    pass
