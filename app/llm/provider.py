import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def get_llm():
    """
    Create the configured chat model.
    """

    api_key = os.getenv("API_KEY")

    if not api_key:
        raise ValueError(
            "API_KEY environment variable is required."
        )

    model = "openai/gpt-oss-120b"
    base_url = "https://api.groq.com/openai/v1"

    return ChatOpenAI(
        model=model,
        temperature=0,
        api_key=api_key,
        base_url=base_url,
    )