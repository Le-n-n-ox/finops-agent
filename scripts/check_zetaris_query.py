"""Run: python scripts/check_zetaris_query.py
Needs ZETARIS_BASE_URL, ZETARIS_ORG_ID and ZETARIS_API_KEY in .env.
Prints row counts and the real shape of one record per table so we can map them to the schemas."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
from app.integrations.zetaris_client import TABLES, ZetarisClient, ZetarisNotConfigured

try:
    client = ZetarisClient()
    for t in TABLES:
        rows = client.query(f"SELECT * FROM finops_data.{t}")
        print(f"\n== {t}: {len(rows)} rows")
        if rows:
            print("type of a record:", type(rows[0]).__name__)
            print("first record:", json.dumps(rows[0], default=str)[:400])
except ZetarisNotConfigured as e:
    sys.exit(f"NOT CONFIGURED: {e}")
except Exception as e:
    sys.exit(f"FAILED: {type(e).__name__}: {e}")