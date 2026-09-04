import os
import shutil
import base64
import time
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai
from src.modules.extractor import extract_pdf_multimodal

# --- Configuration ---
st.set_page_config(page_title="Glass Data Extractor", layout="wide", initial_sidebar_state="expanded")
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

# Directory Setup
PAPERS_DIR = r"data\01_raw_papers"
PROCESSED_DIR = r"data\03_processed_docs"
STAGING_CSV = r"data\04_output_staging\staging_dataset.csv"

# Ensure directories exist
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(os.path.dirname(STAGING_CSV), exist_ok=True)

# --- Initialization ---
if "client" not in st.session_state:
    st.session_state.client = genai.Client(api_key=API_KEY) if API_KEY else None

if "extracted_df" not in st.session_state:
    st.session_state.extracted_df = pd.DataFrame()


def display_pdf(file_path):
    """Embeds the PDF in the Streamlit app."""
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}#toolbar=0&navpanes=0" width="100%" height="750" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)


# --- Column Categorization ---
COMP_COLS = ["SiO2", "Al2O3", "Na2O", "K2O", "MgO", "CaO", "B2O3", "P2O5", "BaO", "ZnO", "SnO2", "PbO", "ZrO2", "Li2O",
             "TiO2", "trace", "trace_notes", "GS_wt_percent", "reported_unit"]
PROC_COLS = ["exchanging_ion", "exchange_side", "E_field", "Tg", "ion_exchange_time_min", "ion_exchange_temperature_c",
             "E_field_strength_v_cm", "is_standard_process", "reference_DOI"]
RES_COLS = ["concentration_profile", "DOL_um", "CS_Mpa"]

# --- UI Layout ---
st.title("🔬 Glass Science Data Extraction Pipeline")

if not st.session_state.client:
    st.error("API Key missing. Please check your .env file.")
    st.stop()

# Sidebar: File Selection (Only shows unprocessed files)
available_pdfs = [f for f in os.listdir(PAPERS_DIR) if f.lower().endswith('.pdf')]

if not available_pdfs:
    st.sidebar.success("🎉 All caught up! No new papers in the raw folder.")
else:
    selected_pdf = st.sidebar.selectbox("Select PDF to Process:", available_pdfs)
    pdf_path = os.path.join(PAPERS_DIR, selected_pdf)

    # --- Action: Extract Data ---
    if st.sidebar.button("1. Extract Data from PDF", type="primary", use_container_width=True):
        st.session_state.extracted_df = pd.DataFrame()  # Clear previous

        with st.spinner(f"Analyzing {selected_pdf} (Text + Vision)..."):
            data, error = extract_pdf_multimodal(st.session_state.client, pdf_path)

            if error:
                st.error(error)
            elif not data:
                st.warning("No experimental data found in this document.")
            else:
                df = pd.DataFrame(data)
                # Ensure all columns exist even if LLM missed some
                for col in COMP_COLS + PROC_COLS + RES_COLS:
                    if col not in df.columns:
                        df[col] = None

                st.session_state.extracted_df = df
                st.toast("Extraction Complete!", icon="✅")

# --- Main Workspace: Split Screen ---
if not st.session_state.extracted_df.empty:
    st.markdown("---")
    col1, col2 = st.columns([1, 1.2], gap="large")

    with col1:
        st.subheader("📄 Ground Truth Document")
        display_pdf(pdf_path)

    with col2:
        st.subheader("⚙️ Verify and Edit Data")

        # Categorized tabs
        tab1, tab2, tab3 = st.tabs(["🧪 Composition", "🌡️ Process Params", "📊 Results (Penetration / DOL / CS)"])

        with tab1:
            st.caption("Verify Oxide mass/mole fractions and trace elements.")
            edited_comp = st.data_editor(st.session_state.extracted_df[COMP_COLS], num_rows="dynamic",
                                         use_container_width=True, key="comp")

        with tab2:
            st.caption("Verify temperatures, times, and boundary conditions.")
            edited_proc = st.data_editor(st.session_state.extracted_df[PROC_COLS], num_rows="dynamic",
                                         use_container_width=True, key="proc")

        with tab3:
            st.caption("Cross-reference C(x,t) profile arrays, DOL, and CS with paper figures.")
            edited_res = st.data_editor(st.session_state.extracted_df[RES_COLS], num_rows="dynamic",
                                        use_container_width=True, key="res")

        st.markdown("---")

        # --- Action: Save & Archive ---
        if st.button("2. Approve Data & Archive PDF", type="primary", use_container_width=True):
            # Recombine the edited tabs
            final_df = pd.concat([edited_comp, edited_proc, edited_res], axis=1)
            final_df.insert(0, "Source_File", selected_pdf)

            # Update Dataset Logic
            if os.path.exists(STAGING_CSV):
                master_df = pd.read_csv(STAGING_CSV)

                # Check if the PDF has been processed before and remove its old rows
                if "Source_File" in master_df.columns:
                    master_df = master_df[master_df["Source_File"] != selected_pdf]

                updated_master = pd.concat([master_df, final_df], ignore_index=True)
            else:
                updated_master = final_df

            updated_master.to_csv(STAGING_CSV, index=False)

            # Safely archive PDF
            processed_path = os.path.join(PROCESSED_DIR, selected_pdf)

            try:
                shutil.copy2(pdf_path, processed_path)
                st.session_state.extracted_df = pd.DataFrame()
                os.remove(pdf_path)
                st.success(
                    f"✅ Saved {len(final_df)} rows for {selected_pdf} (overwriting previous entries if any) and archived document!")
            except PermissionError:
                st.session_state.extracted_df = pd.DataFrame()
                st.warning(f"✅ Data saved and PDF copied to processed folder.")

            time.sleep(1.5)
            st.rerun()