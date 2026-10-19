"""
NVIDIA NIM (optional, explanation only). Uses NVIDIA's OpenAI-compatible endpoint.
Value: turns the critic's structured checks into a plain-English rationale for the dashboard/report.
It NEVER makes or changes a decision. Returns None when no key is set (UI then shows the rule text).
Get a key at https://build.nvidia.com and set NVIDIA_API_KEY in .env.
"""
from __future__ import annotations

import os

import httpx

NIM_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NIM_MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct")


def explain(decision: str, checks: list[dict]) -> str | None:
    key = os.getenv("NVIDIA_API_KEY")
    if not key:
        return None
    prompt = (
        "Explain in 2 sentences, for a platform engineer, why this Kubernetes resource change was "
        f"'{decision}'. Use only these checks, add no new facts: {checks}"
    )
    try:
        r = httpx.post(
            f"{NIM_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": NIM_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.1, "max_tokens": 150},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None  # explanation is optional; never break the pipeline
