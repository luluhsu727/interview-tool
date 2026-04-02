import streamlit as st
from google.cloud import bigquery
from google.api_core import exceptions
import pandas as pd
from datetime import datetime
import os
import json

# --- 1. SMART AUTHENTICATION (Laptop vs. Cloud) ---
PROJECT_ID = "shopify-1-april"
# This looks for the file on your local machine
LOCAL_KEY = os.path.join(os.getcwd(), "shopify-1-april-5b8762694787.json")

if os.path.exists(LOCAL_KEY):
    # LOCAL MODE: Use your physical JSON file
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = LOCAL_KEY
    client = bigquery.Client(project=PROJECT_ID)
elif "GCP_SERVICE_ACCOUNT" in st.secrets:
    # CLOUD MODE: Use "Secrets" from the Streamlit Dashboard (Safe for GitHub)
    service_account_info = json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
    client = bigquery.Client.from_service_account_info(service_account_info)
else:
    st.error("❌ Credentials not found! Add your JSON key locally or set Streamlit Secrets.")
    st.stop()

# --- 2. DASHBOARD UI SETUP ---
st.set_page_config(page_title="Shopify Global Tax", page_icon="💰")
st.title("Shopify Global Tax Filing Dashboard")
st.markdown("---")

# --- 3. STAGE 1: REVIEW DISCREPANCIES (Audit Trail) ---
st.header("1. Review Discrepancies")
st.info("Pulling from `final_tax_audit_trail` (Enriched by Gemini AI)")

audit_query = f"SELECT * FROM `{PROJECT_ID}.shopify_tax_exercise.final_tax_audit_trail` WHERE requires_review = True"
try:
    audit_df = client.query(audit_query).to_dataframe()

    if audit_df.empty:
        st.success("✅ All clear! No variances found in the current audit trail.")
    else:
        st.warning(f"⚠️ Found {len(audit_df)} items requiring manual approval:")
        st.dataframe(audit_df)
except Exception as e:
    st.error(f"Error loading audit trail: {e}")

st.markdown("---")

# --- 4. STAGE 2: OFFICIAL FILING (Summary Data) ---
st.header("2. Official Filing")
country_to_file = st.selectbox("Select Country to File", ["IE", "GB", "FR"])

if st.button(f"🚀 Submit {country_to_file} VAT Return"):
    with st.spinner(f'Fetching official totals for {country_to_file}...'):
        
        # Pulling the AGGREGATED totals created by your first script
        summary_query = f"""
            SELECT * FROM `{PROJECT_ID}.shopify_tax_exercise.final_vat_return_summary` 
            WHERE supplier_country = '{country_to_file}'
        """
        summary_df = client.query(summary_query).to_dataframe()

    if summary_df.empty:
        st.error(f"❌ No summary data found for {country_to_file}. Please run the 'VAT Brain' script first.")
    else:
        # Extract totals for the confirmation message
        net_sales = summary_df['net_sales'].iloc[0]
        vat_due = summary_df['output_vat'].iloc[0]
        
        st.write(f"**Drafting Return for {country_to_file}:**")
        st.code(f"Net Sales: {net_sales} | VAT Due: {vat_due}")

        # Simulate Government Handshake
        with st.spinner('Transmitting to Government Gateway...'):
            fake_receipt = f"RECPT-{datetime.now().strftime('%Y%m%d')}-001"
            
            # Save the Receipt back to BigQuery
            receipt_sql = f"""
                INSERT INTO `{PROJECT_ID}.shopify_tax_exercise.filing_receipts` 
                (invoice_id, country, receipt_id, filed_at, status)
                VALUES ('BULK_UPLOAD', '{country_to_file}', '{fake_receipt}', CURRENT_TIMESTAMP(), 'FILED')
            """
            client.query(receipt_sql)
            
            st.success(f"Filing Successful! Government Receipt: **{fake_receipt}**")
            st.balloons()

st.markdown("---")

# --- 5. STAGE 3: PROOF OF FILING (Receipts) ---
st.header("3. Proof of Filing (History)")
try:
    receipts_df = client.query(f"SELECT * FROM `{PROJECT_ID}.shopify_tax_exercise.filing_receipts` ORDER BY filed_at DESC").to_dataframe()
    if not receipts_df.empty:
        st.table(receipts_df)
    else:
        st.write("No filing history found yet.")
except Exception as e:
    st.error(f"Error loading receipts: {e}")