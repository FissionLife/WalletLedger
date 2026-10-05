# Role 5: Transaction Engine (PDF & Chat Parsing)
# Handles extracting financial data from user inputs


def parse_phonepe_pdf(file_bytes):
    """
    Extracts text from a PhonePe or bank statement PDF.
    Sends the text to the AI Gateway to structure it into transaction records.
    """
    # TODO: Use PyPDF2 or similar to extract text
    # TODO: Call AI Gateway to convert text -> structured JSON
    pass


def parse_chat_expense(text: str):
    """
    Extracts expense details from conversational chat.
    e.g., "I just spent 500 on coffee" -> amount: 500, category: Food
    """
    # TODO: Prompt AI Gateway to extract amount and category
    pass
