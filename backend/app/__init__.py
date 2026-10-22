"""The FinOps Agent backend package.

Importing the package loads `.env` (see `app.config`), so every entry point - uvicorn, pytest,
a script - sees the same configuration. Nothing else happens here: the app's behaviour lives in
`app.main` and the modules it imports.
"""
from app.config import load_env

load_env()
