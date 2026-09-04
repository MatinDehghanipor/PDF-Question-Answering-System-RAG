import os
from dotenv import load_dotenv
from google import genai


def list_available_models():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("Error: API Key not found in .env file.")
        return

    print("Connecting to Google AI Studio...")
    client = genai.Client(api_key=api_key)

    print("\nAllowed Gemini Models for your API Key:")
    try:
        # Retrieve and print all models your key has permission to use
        for model in client.models.list():
            if "gemini" in model.name:
                print(f"- {model.name}")
    except Exception as e:
        print(f"\nFailed to connect. Error details:\n{e}")


if __name__ == "__main__":
    list_available_models()