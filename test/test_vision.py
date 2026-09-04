import os
import json
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import Optional


# 1. Base Pydantic Schema
class GlassExperiment(BaseModel):
    GS_wt_percent: Optional[str] = None
    exchanging_ion: Optional[str] = None
    exchange_side: Optional[str] = None
    E_field: Optional[str] = None
    reference_DOI: Optional[str] = None
    SiO2: float = 0.0
    P2O5: float = 0.0
    B2O3: float = 0.0
    Al2O3: float = 0.0
    CaO: float = 0.0
    MgO: float = 0.0
    BaO: float = 0.0
    ZnO: float = 0.0
    SnO2: float = 0.0
    PbO: float = 0.0
    ZrO2: float = 0.0
    Li2O: float = 0.0
    Na2O: float = 0.0
    K2O: float = 0.0
    TiO2: float = 0.0
    Tg: Optional[float] = None
    ion_exchange_time_min: Optional[float] = None
    E_field_strength_v_cm: Optional[float] = None
    ion_exchange_temperature_c: Optional[float] = None
    DOL_um: Optional[float] = None
    CS_Mpa: Optional[float] = None
    trace: float = 0.0
    trace_notes: Optional[str] = None
    is_standard_process: bool = True
    reported_unit: Optional[str] = None


class ExtractionResult(BaseModel):
    experiments: list[GlassExperiment]


def test_multimodal_pdf(pdf_filename):
    """Uploads the raw PDF with automatic retries for server overloads."""
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: API Key not found in .env file.")
        return

    pdf_path = os.path.join("../data", "01_raw_papers", pdf_filename)
    if not os.path.exists(pdf_path):
        print(f"Error: Could not find {pdf_path} at {pdf_path}")
        return

    client = genai.Client(api_key=api_key)

    print(f"Step 1: Uploading {pdf_filename} to Gemini File API...")
    try:
        uploaded_pdf = client.files.upload(file=pdf_path)
    except Exception as e:
        print(f"Failed to upload PDF: {e}")
        return

    prompt = """
    You are an expert materials scientist. Extract the glass composition and ion exchange 
    experimental parameters from the provided document.

    CRITICAL VISION INSTRUCTION:
    The Compressive Stress (CS) and Depth of Layer (DOL) values are frequently plotted on graphs, 
    scatter plots, or optical stress profile images in the Results section. You must visually analyze 
    the charts, read the X and Y axes, and extract the CS (in MPa) and DOL (in μm) 
    corresponding to specific exchange times and temperatures.

    EXTRACTION RULES:
    1. MULTIPLE EXPERIMENTS: Create a separate object in `experiments` for each condition tested.
    2. MISSING OXIDES: If an oxide listed in the schema is omitted, set it to 0.0.
    3. UNLISTED / TRACE OXIDES: Sum unexpected oxides into `trace` and record details in `trace_notes`.
    4. PROCESS ANOMALIES: Set `is_standard_process` to false for mixed-alkali baths or contamination.
    5. UNITS: Record whether the composition was originally reported in mol% or wt% in `reported_unit`.
    """

    print("Step 2: Analyzing text, tables, and images simultaneously (with auto-retry)...")

    max_retries = 3
    success = False

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=[prompt, uploaded_pdf],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExtractionResult,
                )
            )
            print("\n--- EXTRACTION SUCCESSFUL ---")
            print(json.dumps(json.loads(response.text), indent=2))
            success = True
            break

        except Exception as e:
            print(f"Attempt {attempt} failed with error: {e}")
            if attempt < max_retries:
                sleep_time = attempt * 5
                print(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                print("\n--- EXTRACTION FAILED AFTER MAXIMUM RETRIES ---")

    # Clean up the file from Google's servers
    try:
        client.files.delete(name=uploaded_pdf.name)
        print("\n(PDF successfully deleted from cloud storage)")
    except Exception:
        pass


if __name__ == "__main__":
    # Ensure this points to the exact filename of your test paper in data/01_raw_papers/
    TARGET_PDF = "test_paper.pdf"
    test_multimodal_pdf(TARGET_PDF)