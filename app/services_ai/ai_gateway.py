# Role 3: AI Gateway (Provider Agnostic)
# Handles LLM routing, API keys, and round-robin logic


class AIGateway:
    def __init__(self):
        self.default_model = "gemini-flash"

    def generate_response(self, user_id: str, prompt: str):
        """
        1. Fetch user's Gemini/OpenAI API key from DB
        2. Route request using LiteLLM to support multiple providers
        3. Handle fallback and rate limits
        """
        # TODO: Fetch user's API key from DB
        # TODO: Route to LiteLLM
        pass
