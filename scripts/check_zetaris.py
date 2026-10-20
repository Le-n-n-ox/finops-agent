"""Day 1-2 feasibility check. Run: python scripts/check_zetaris.py  (needs ZETARIS_* in .env)"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from dotenv import load_dotenv
import httpx

load_dotenv()
from app.integrations.zetaris_client import ZetarisClient, ZetarisNotConfigured

try:
    tokens = ZetarisClient().login()
    print("Zetaris login OK; token keys:", list(tokens))
except ZetarisNotConfigured as e:
    print("NOT CONFIGURED:", e)
    sys.exit(1)
except httpx.HTTPStatusError as e:
    # Zetaris often includes the validation reason in its response body.
    # Redact credentials in case the server echoes request details.
    detail = e.response.text
    for secret in (os.getenv("ZETARIS_USERNAME", ""), os.getenv("ZETARIS_PASSWORD", "")):
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
    print(f"Zetaris login FAILED: HTTP {e.response.status_code}")
    if detail.strip():
        print("Response:", detail)
    sys.exit(2)
except Exception as e:
    print("Zetaris login FAILED:", e)
    sys.exit(2)
