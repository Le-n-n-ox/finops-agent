# Sponsor integrations — where each one plugs in

| Technology | Requirement | Where | Status |
|---|---|---|---|
| **Zetaris** | Must be in the architecture | `integrations/zetaris_client.py`, `data_loader.load_inputs_from_zetaris()` — the unified data layer under the Data Collector | Login implemented per docs; query TODO |
| **Meterless** | Must be in the architecture | `integrations/meterless_runner.py` — every agent step runs through `get_runner()`; `AGENT_RUNTIME=meterless` | Adapter seam + local runner; Meterless adapter TODO (Dev 2) |
| **Cursor** | Must be the IDE | `.cursor/rules/finops.mdc`, prompts in `docs/CURSOR.md` | Ready |
| **NVIDIA** | Where it adds value | `integrations/nvidia_nim.py` — NIM LLM turns critic checks into plain-English rationale (optional, never decides) | Implemented, needs `NVIDIA_API_KEY` |

Architecture:
```
Zetaris (or local files) -> Data Collector -> FinOps Optimizer -> Context Critic -> Report
                                   each step executed through Meterless runner (or local)
                          NVIDIA NIM: explanation text only
```
Rule: never claim an integration in the demo/README unless a real call was tested.

**Open question:** the brief says "Cursor (with Space XAI)". I don't know what "Space XAI" refers to — check the hackathon material and add it to `docs/CURSOR.md` once confirmed.
