"""Day 1-2 feasibility check. Run: python scripts/check_zetaris.py  (needs ZETARIS_* in .env)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from dotenv import load_dotenv

load_dotenv()
from app.integrations.zetaris_client import ZetarisClient, ZetarisNotConfigured

try:
    tokens = ZetarisClient().login()
    print("Zetaris login OK; token keys:", list(tokens))
except ZetarisNotConfigured as e:
    print("NOT CONFIGURED:", e)
    sys.exit(1)
except Exception as e:
    print("Zetaris login FAILED:", e)
    sys.exit(2)
