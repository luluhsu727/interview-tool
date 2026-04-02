import pandas as pd
import numpy as np
import pandas_gbq
from google.cloud import bigquery
import vertexai
from vertexai.generative_models import GenerativeModel
from zeep import Client # For VIES VAT Verification
import os

# 1. CONFIGURATION
PROJECT_ID = "shopify-1-april"
LOCATION = "us-central1" # Or your specific region
vertexai.init(project=PROJECT_ID, location=LOCATION)
gemini_model = GenerativeModel("gemini-1.5-flash")

# EU VAT Verification API (Official VIES)
vies_client = Client(wsdl='https://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl')

# Box Mapping for official Filing (The "Receipt" stage)
BOX_MAP = {
    "GB": {"net_sales": "Box 6", "output_vat": "Box 1", "input_vat_reclaimed": "Box 4"},
    "IE": {"net_sales": "T1", "output_vat": "T2", "input_vat_reclaimed": "T4"}
}

# 2. THE "WORKERS" (External Handshakes)
def call_gemini_classifier(memo):
    """Uses AI to determine if a line item is a SERVICE or PRODUCT."""
    try:
        prompt = f"Classify this Shopify invoice memo as 'SERVICE' or 'PRODUCT'. Respond with only one word: {memo}"
        response = gemini_model.generate_content(prompt)
        return response.text.strip().upper()
    except Exception as e:
        print(f"Gemini Error: {e}")
        return "UNKNOWN"

def verify_vat_id(vat_id, country_code):
    """Hits the official EU VIES API to check if a VAT ID is real."""
    if not vat_id or vat_id == 'INVALID': return False
    try:
        # Clean the ID (remove country prefix if present)
        clean_id = str(vat_id).upper().replace(country_code.upper(), "").strip()
        result = vies_client.service.checkVat(countryCode=country_code, vatNumber=clean_id)
        return result['valid']
    except Exception:
        return False

# 3. THE ENGINE
class ShopifyGlobalTaxEngine:
    def __init__(self, project_id):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)

    def fetch_upstream_data(self):
        query = f"SELECT * FROM `{self.project_id}.shopify_tax_exercise.raw_netsuite_data`"
        return pandas_gbq.read_gbq(query, project_id=self.project_id)

    def process_compliance(self, df):
        print("🤖 Running AI Classification & VAT Verification...")
        
        # AI Logic
        df["line_type"] = df["memo"].apply(call_gemini_classifier)
        
        # Real-time API Verification
        df["cust_vat_valid"] = df.apply(lambda r: verify_vat_id(r["customer_vat_id"], r["customer_country"]) 
                                       if r["transaction_type"] == "sale" else True, axis=1)
        
        # Complex Tax Logic
        # 0% Tax only if: Sale + Cross-Border + Valid VAT + Service
        df["expected_tax"] = np.where(
            (df["transaction_type"] == "sale") & 
            (df["supplier_country"] != df["customer_country"]) & 
            (df["cust_vat_valid"] == True) & 
            (df["line_type"] == "SERVICE"), 
            0, 
            df["amount_net"] * (df["tax_rate"] / 100)
        )
        
        df["variance"] = (df["tax_amount"] - df["expected_tax"]).round(2)
        df["requires_review"] = df["variance"].abs() > 0.50
        return df

    def export_to_bigquery(self, processed_df):
        print("📤 Exporting Final Audit Trail and Return Summary...")
        
        # 1. Create Summary for the Filing Dashboard
        summary = processed_df[processed_df["requires_review"] == False].groupby("supplier_country").agg(
            net_sales=("amount_net", "sum"),
            output_vat=("tax_amount", "sum")
        ).reset_index()

        # 2. Upload to BigQuery
        processed_df.to_gbq(
            f"{self.project_id}.shopify_tax_exercise.final_tax_audit_trail",
            project_id=self.project_id, if_exists='replace'
        )
        summary.to_gbq(
            f"{self.project_id}.shopify_tax_exercise.final_vat_return_summary",
            project_id=self.project_id, if_exists='replace'
        )

if __name__ == "__main__":
    engine = ShopifyGlobalTaxEngine(PROJECT_ID)
    raw_data = engine.fetch_upstream_data()
    enriched_data = engine.process_compliance(raw_data)
    engine.export_to_bigquery(enriched_data)
    print("✅ Pipeline Complete. Check BigQuery for 'final_tax_audit_trail'.")