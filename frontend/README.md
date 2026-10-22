# Frontend

React + TypeScript + Vite dashboard for the FinOps agent. It reads the FastAPI backend under
`/api` and falls back to bundled mock fixtures when the backend is unreachable, so the UI is
usable before the API is running.

## Commands

```bash
npm install
npm run dev       # Vite dev server on :5173, proxies /api to the backend
npm run build     # type-check (tsc -b) then bundle
npm run lint      # oxlint
npm run mock      # regenerate public/mock/*.json from ../data/sample_analysis_response.json
```

The dev server proxies `/api` to `http://127.0.0.1:8000` (see `vite.config.ts`). Set
`VITE_API_PROXY` to point somewhere else — Docker Compose sets it to the `finops_agent` service.
Start the backend first with `uvicorn app.main:app --reload --port 8000 --app-dir backend` from the
repository root.

## Layout

```text
src/
├─ api.ts                  Every backend call. Read helpers return Fetched<T>, so a failed call
│                          is distinguishable from "there was nothing to show".
├─ types.ts                TypeScript mirror of backend/app/models/schemas.py. Do not diverge.
├─ lib/report.ts           Client-side Markdown report builder (the offline export path).
├─ components/
│  ├─ App.tsx              Page shell: section nav, filters, export, mobile sheet.
│  ├─ DetailPanel.tsx      The per-workload panel: Evidence / Cycle / What-if / Critic / Patch.
│  ├─ DetailSheet.tsx      The same panel as a mobile bottom sheet (focus trap and scroll lock).
│  ├─ ReviewCyclePanel.tsx Proposer → Critic → Judge phases, with the tools each one called.
│  ├─ Simulator.tsx        What-if: re-ask the critic about hypothetical request values.
│  ├─ ReviewState.tsx      What a human already decided about this workload.
│  ├─ ReviewForm.tsx       Record a human action, with the outcome field.
│  ├─ DecisionHistory.tsx  Every decision across reports, searchable, with a validity column.
│  ├─ PolicyPanel.tsx      The editable safety policy; saving appends a new version.
│  ├─ ProvenanceStrip.tsx  Policy version, rule version, input fingerprint, and the LLM disclosure.
│  ├─ SavingsPotential.tsx What the optimizer found vs what the safety rules let through.
│  ├─ InputStatus.tsx      The data sources behind the analysis, from the validation report.
│  ├─ ResultsTable.tsx     The sortable, searchable workload table.
│  ├─ TrendChart.tsx       Savings and decision mix across analyses.
│  ├─ EventTimeline.tsx    Business events, split into live / upcoming / past.
│  └─ Workflow.tsx         The pipeline strip. Mode-aware: it shows the stages that ran.
```

## Conventions

- **The contract is the backend.** `src/types.ts` mirrors `backend/app/models/schemas.py`. Fields
  added there need a matching type here; fields added here need a matching field there.
- **The deterministic critic owns every decision.** The UI explains decisions; it never makes one.
  The simulator re-asks the critic, it does not substitute for it.
- **Nothing is applied.** "Accept" records a human decision in the audit log. It does not deploy
  anything, and the frontend says so wherever that could be misread.
- **Every panel degrades.** A failed history, policy or events call returns `Fetched<T>` with
  `failed: true` and the panel shows an empty state — and drops the previous value, because a
  stale number that looks current is worse than no number. The analysis itself is the only thing
  that can fail the page.
- **Show the money that was not counted.** When the critic refuses a reduction the optimizer found,
  the saving moves to `proposal.suppressed_saving_usd`. Any total that means "what the optimizer
  found" adds it; any total that means "what was approved" does not.
