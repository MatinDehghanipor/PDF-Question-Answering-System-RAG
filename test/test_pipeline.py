import os
import json
from dotenv import load_dotenv
from google import genai
from src.modules.parser import process_pdf
from src.modules.extractor import extract_data_with_llm


def test_single_pdf(pdf_filename):
    """Runs a single PDF through the parser and LLM extractor."""

    # 1. Define the path to your test PDF
    pdf_path = os.path.join("../data", "01_raw_papers", pdf_filename)

    if not os.path.exists(pdf_path):
        print(f"Error: Could not find {pdf_path}")
        return

    print(f"Step 1: Parsing PDF ({pdf_filename})...")
    context_string = process_pdf(pdf_path)

    if not context_string.strip():
        print("Error: Parser returned empty text. Check the PDF format.")
        return

    print("Step 2: Connecting to Gemini (gemini-3.6-flash)...")
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: API Key not found in .env file.")
        return

    client = genai.Client(api_key=api_key)

    print("Step 3: Extracting structured data...")
    results = extract_data_with_llm(client, context_string)

    if results:
        print("\n--- EXTRACTION SUCCESSFUL ---")
        print(json.dumps(results, indent=2))
    else:
        print("\n--- EXTRACTION FAILED ---")


if __name__ == "__main__":
    # Replace with the exact name of a real PDF in your 01_raw_papers folder
    TARGET_PDF = "test_paper.pdf"

    test_single_pdf(TARGET_PDF)