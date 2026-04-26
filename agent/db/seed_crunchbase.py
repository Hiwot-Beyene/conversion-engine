import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import sys
import json
import re

# Add the project root to sys.path to allow importing from agent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from agent.db.models import Company, Base

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[2]

DATABASE_URL = os.getenv("DATABASE_URL")
# Replace ${DB_PASSWORD} with the actual password if present in the URL
if DATABASE_URL and "${DB_PASSWORD}" in DATABASE_URL:
    DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
    DATABASE_URL = DATABASE_URL.replace("${DB_PASSWORD}", DB_PASSWORD)

CSV_PATH = os.getenv("CRUNCHBASE_CSV_PATH") or str(
    _REPO_ROOT / "data" / "crunchbase-companies-information.csv"
)

def parse_employee_count(val):
    if pd.isnull(val):
        return None
    # Extract first integer from strings like "1-10", "501-1000", etc.
    match = re.search(r'\d+', str(val))
    return int(match.group()) if match else None

def extract_sector(val):
    if pd.isnull(val):
        return None
    try:
        # industries is a JSON string like [{"id":"seo","value":"SEO"}]
        industries = json.loads(val)
        if isinstance(industries, list) and len(industries) > 0:
            return industries[0].get('value')
    except:
        pass
    return None

def seed_crunchbase():
    if not DATABASE_URL:
        print("DATABASE_URL not found in environment.")
        return
    if not CSV_PATH or not os.path.exists(CSV_PATH):
        print(f"CSV file not found at {CSV_PATH}")
        return

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Ensure tables and extension are created
    print("Ensuring database schema and extensions exist...")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
        Base.metadata.create_all(engine)
    except Exception as e:
        print(f"Error initializing database: {e}")
        return

    print(f"Reading CSV from {CSV_PATH}...")
    try:
        # Read with low_memory=False to avoid DtypeWarning
        df = pd.read_csv(CSV_PATH, low_memory=False)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    total_rows = len(df)
    # Validation: name, domain, crunchbase_id must be non-null
    # Mapping CSV columns: 'name', 'id' (mapping to crunchbase_id in model)
    required_cols = ['name', 'id']
    for col in required_cols:
        if col not in df.columns:
            print(f"Error: Required column '{col}' missing from CSV.")
            return

    valid_df = df.dropna(subset=required_cols)
    invalid_count = total_rows - len(valid_df)

    companies_to_insert = []
    for _, row in valid_df.iterrows():
        # Map row to Company model.
        company = Company(
            crunchbase_id=str(row['id']),
            name=str(row['name']),
            domain=str(row.get('website')) if pd.notnull(row.get('website')) else None,
            description=str(row.get('about')) if pd.notnull(row.get('about')) else None,
            employee_count=parse_employee_count(row.get('num_employees')),
            sector=extract_sector(row.get('industries')),
            location=str(row.get('location')) if pd.notnull(row.get('location')) else None,
            country=str(row.get('country_code')) if pd.notnull(row.get('country_code')) else None,
            funding_round=str(row.get('ipo_status')) if pd.notnull(row.get('ipo_status')) else None,
            # funding_amount_usd needs more complex parsing from JSON if available
        )
        companies_to_insert.append(company)

    print(f"Bulk inserting {len(companies_to_insert)} companies...")
    try:
        # Using bulk_save_objects for performance
        session.bulk_save_objects(companies_to_insert)
        session.commit()
        print(f"Imported {len(companies_to_insert)} companies, skipped {invalid_count} invalid rows")
        if invalid_count > 0:
            print(f"Details: {invalid_count} rows skipped due to missing required fields (name, id).")
    except Exception as e:
        session.rollback()
        print(f"Error during bulk insert: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    seed_crunchbase()
