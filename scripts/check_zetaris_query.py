"""Run: python scripts/check_zetaris_query.py
Needs ZETARIS_BASE_URL, ZETARIS_ORG_ID and ZETARIS_API_KEY in .env.
Prints row counts and the real shape of one record per table so we can map them to the schemas."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
# `host.docker.internal` is provided by Docker Desktop inside containers. When
# this helper is run directly from Windows, use the host-published service port
# via localhost instead.
base_url = os.getenv("ZETARIS_BASE_URL", "").rstrip("/")
if os.name == "nt" and base_url:
    parts = urlsplit(base_url)
    if parts.hostname == "host.docker.internal":
        netloc = "localhost"
        if parts.port:
            netloc += f":{parts.port}"
        os.environ["ZETARIS_BASE_URL"] = urlunsplit(
            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
        )
        print(f"Using localhost for this Windows host check (port {parts.port or 'default'}).")

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
