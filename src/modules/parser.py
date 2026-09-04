import fitz  # PyMuPDF
import pdfplumber
import re
import os


def extract_text_with_pymupdf(pdf_path):
    """Extracts raw text and attempts to isolate the experimental methodology."""
    try:
        doc = fitz.open(pdf_path)
        full_text = ""
        for page in doc:
            full_text += page.get_text()

        # Regex to capture everything between standard Experimental and Results headers
        match = re.search(
            r'(?i)(experimental procedure|materials and methods|experimental section|experimental)(.*?)(results and discussion|conclusions|results)',
            full_text,
            re.DOTALL
        )

        if match:
            return match.group(2).strip()

        # Fallback: If specific headers aren't found, return the full text
        return full_text

    except Exception as e:
        print(f"Error reading text from {os.path.basename(pdf_path)}: {e}")
        return ""


def extract_tables_with_pdfplumber(pdf_path):
    """Extracts tables and formats them as pipe-separated strings for the LLM."""
    table_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        # Replace null cells with empty strings and join with a pipe
                        cleaned_row = [str(cell).replace('\n', ' ').strip() if cell is not None else "" for cell in row]
                        # Only append rows that actually contain data
                        if any(cleaned_row):
                            table_text += " | ".join(cleaned_row) + "\n"
                    table_text += "-" * 50 + "\n"  # Add a separator between different tables
        return table_text

    except Exception as e:
        print(f"Error reading tables from {os.path.basename(pdf_path)}: {e}")
        return ""


def process_pdf(pdf_path):
    """Orchestrates the extraction of a single PDF."""
    print(f"Extracting context from: {os.path.basename(pdf_path)}...")

    text_content = extract_text_with_pymupdf(pdf_path)
    table_content = extract_tables_with_pdfplumber(pdf_path)

    # Combine into a structured format for Gemini
    combined_context = f"--- EXTRACTED TEXT ---\n{text_content}\n\n--- EXTRACTED TABLES ---\n{table_content}"
    return combined_context


# Brief test block to verify it works locally
if __name__ == "__main__":
    # Point this to a real PDF you place in the raw_papers folder to test
    test_pdf_path = r"D:\Glass_Data_Extraction\data\01_raw_papers\test_paper.pdf"

    if os.path.exists(test_pdf_path):
        result = process_pdf(test_pdf_path)
        print("\nExtraction Successful. Preview of extracted data:\n")
        print(result[:1000])  # Print just the first 1000 characters to verify
    else:
        print(f"To test, please place a PDF at: {test_pdf_path}")