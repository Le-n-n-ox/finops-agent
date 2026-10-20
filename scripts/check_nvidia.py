"""Run: python scripts/check_nvidia.py   (needs NVIDIA_API_KEY in .env)"""
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
key = os.getenv("NVIDIA_API_KEY")
if not key:
    sys.exit("NVIDIA_API_KEY is empty. Put it in .env (no quotes, no spaces).")
base = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
model = os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")

r = httpx.post(
    f"{base}/chat/completions",
    headers={"Authorization": f"Bearer {key}"},
    json={"model": model, "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
          "max_tokens": 50, "temperature": 0},
    timeout=30,
)
print("HTTP", r.status_code)
if r.status_code == 200:
    msg = r.json()["choices"][0]["message"]
    text = msg.get("content") or msg.get("reasoning_content")
    print("model:", model)
    print("NVIDIA OK ->", text if text else f"(empty text; raw message: {msg})")
else:
    print(r.text[:400])
    if r.status_code in (401, 403):
        print("Key rejected: regenerate it at build.nvidia.com")
    if r.status_code == 404:
        print(f"Model '{model}' not found: pick another from build.nvidia.com/models and set NVIDIA_MODEL")
    sys.exit(1)