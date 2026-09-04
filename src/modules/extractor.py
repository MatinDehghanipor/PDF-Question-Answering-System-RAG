import os
import json
import time
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import Optional


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
    concentration_profile: Optional[str] = None
    DOL_um: Optional[float] = None
    CS_Mpa: Optional[float] = None
    trace: float = 0.0
    trace_notes: Optional[str] = None
    is_standard_process: bool = True
    reported_unit: Optional[str] = None


class ExtractionResult(BaseModel):
    experiments: list[GlassExperiment]


def extract_pdf_multimodal(client, pdf_path):
    """Uploads a PDF, analyzes it using vision, and handles retries."""
    try:
        uploaded_pdf = client.files.upload(file=pdf_path)
    except Exception as e:
        return None, f"Upload failed: {e}"

    prompt = """
    You are an expert materials scientist. Extract the glass composition and ion exchange 
    experimental parameters from the provided document.

    CRITICAL VISION INSTRUCTIONS:
    Analyze graphs, scatter plots, EDS/EPMA line scan profiles, and stress profile images to extract:
    1. CONCENTRATION PROFILE C(x,t): If an EDS/EPMA concentration profile graph is present, visually estimate 5 to 10 discrete data points along the curve. Format strictly as a string of (Depth in μm, Concentration) tuples. Example: "[(0, 15.2), (10, 12.1), (25, 8.4), (50, 2.1)]".
    2. Depth of Layer / Optical Depth of Layer (DOL, in μm).
    3. Surface Compressive Stress (CS, in MPa).

    RULES:
    1. MULTIPLE EXPERIMENTS: Create a separate object for each condition tested.
    2. MISSING OXIDES: Set to 0.0 (Do NOT use null).
    3. TRACE: Sum unexpected oxides into `trace` and specify in `trace_notes`.
    4. ANOMALIES: Set `is_standard_process` to false for mixed baths or external field anomalies.
    5. UNREPORTED: Set missing physical parameters (concentration_profile, CS, DOL, Tg) to null if absent.
    6. EXCHANGE SIDE: For float glass, specify "Tin side" or "Air side" if explicitly stated. If the glass is not produced via the float process (meaning both sides are effectively air), or if it is completely unspecified, default to "Air side".
    """

    max_retries = 3
    extracted_data = []
    error_msg = None

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model='gemini-3-flash-preview',
                contents=[prompt, uploaded_pdf],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExtractionResult,
                )
            )
            result_dict = json.loads(response.text)
            extracted_data = result_dict.get("experiments", [])
            break
        except Exception as e:
            if attempt < max_retries:
                time.sleep(attempt * 4)
            else:
                error_msg = f"Extraction failed after max retries: {e}"

    try:
        client.files.delete(name=uploaded_pdf.name)
    except Exception:
        pass

    return extracted_data, error_msg