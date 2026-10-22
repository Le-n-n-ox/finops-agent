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

## Pages

The dashboard is split into five routed pages, so a reviewer opens the section they need instead of
scrolling past everything else. The routes are real URLs — the browser back button works, and a
link to a page (or a specific workload) can be pasted to someone else.

| Route        | Page      | What it is for                                                                |
| ------------ | --------- | ----------------------------------------------------------------------------- |
| `/`          | Overview  | The money: what is on the table, how much is approved, and whether it is moving. |
| `/workloads` | Workloads | The findings and the evidence behind each one.                                 |
| `/evidence`  | Evidence  | What the run was built from: stages, input health, and the business events.    |
| `/policy`    | Policy    | The safety rules the critic enforces, editable.                                |
| `/history`   | History   | Every decision the critic has made, across reports.                            |

The selected workload lives in the query string (`/workloads?workload=<id>`), so "look at this
one" is a link, not a transient state. Opening a workload *pushes* a history entry, so the back
button returns to the list rather than leaving the page — and the selection and the URL are kept
in step by one effect, so they can never disagree about which workload is on screen.

Routing is a hand-rolled `history.pushState` wrapper (`src/state/`) rather than a routing library:
the app is a handful of top-level sections with no nested layouts, so a library would be more
machinery than the job needs. The back button is the reason to route at all — without it, a
reviewer who opens a workload and goes back loses their place entirely.

The analysis itself is loaded **once**, in `src/state/AnalysisProvider.tsx`, and shared by every
page. Otherwise each page would re-run the analysis on navigation.

The run is **streamed**. A full analysis is a multi-turn conversation with the model server for
every workload, so it takes minutes rather than seconds — and the page shows each workload as it
is reviewed, with a progress bar, a count of how many are done, and a running elapsed time. A
slow run has to be distinguishable from a stuck one, and the elapsed time is what tells them
apart. `POST /api/analyze/stream` sends the results as they are finished;
`POST /api/analyze` still returns the whole response in one piece.

## The agent cycle and the model disclosure

There is one reasoning path. The backend always runs the **agent cycle** (Proposer → Critic →
Judge), the request body carries no `mode`, and the workflow strip always shows the agent-cycle
stages. `runAnalysis` does not send a mode field.

The response carries three fields that say what actually ran:

| Field | Type | Meaning |
|---|---|---|
| `llm_backend` | `string` (optional) | `"openai-compatible"` when a live model server answered, `"simulated"` when the deterministic stand-in ran. |
| `llm_model` | `string \| null` (optional) | The model id that ran, e.g. `"local-runtime/gpt-oss-20b"`. `null` when no model ran. |
| `llm_base_url` | `string \| null` (optional) | The model server's base URL. `null` when no model ran. |

All three are optional, because a payload with no `llm_backend` at all is a third case and not
the same as `"simulated"`: it means the payload does not record which reasoner answered. The
bundled mock fixtures are exactly that — they are not a stand-in run, and the UI must not claim
one was.

The header badge names the model that ran — `Live API · agent cycle · local-runtime/gpt-oss-20b`.
When `llm_backend === "simulated"` the badge says plainly that the deterministic stand-in was used
instead, and `ProvenanceStrip` shows its amber warning. The UI must never imply a model ran when it
did not — and never claim a stand-in ran when the payload does not say one did.

`GET /api/llm/status` returns the same information as a plain JSON object, so the model can be
shown before any analysis has run. The app reads it when it opens, not after the first analysis:
by the time an analysis resolves, the badge has already taken the response's word for it.

## Layout

```text
src/
├─ api.ts                  Every backend call. Read helpers return Fetched<T>, so a failed call
│                          is distinguishable from "there was nothing to show".
├─ types.ts                TypeScript mirror of backend/app/models/schemas.py. Do not diverge.
├─ lib/report.ts           Client-side Markdown report builder (the offline export path).
├─ App.tsx                 The shell: header, section nav, provenance strip, route switch.
├─ state/
│  ├─ router-context.ts    The router contract: path, search, navigate.
│  ├─ RouterProvider.tsx   pushState / replaceState / popstate.
│  ├─ analysis-context.ts  The shared analysis contract.
│  └─ AnalysisProvider.tsx Loads the analysis once; every page reads from it.
├─ pages/
│  ├─ Overview.tsx         Summary cards, savings potential, top opportunities, trend.
│  ├─ Workloads.tsx        Decision mix, savings chart, results table, detail panel/sheet.
│  ├─ Evidence.tsx         Workflow strip, input health, event timeline.
│  ├─ PolicyPage.tsx       The editable safety policy.
│  └─ HistoryPage.tsx      Every decision across reports.
├─ components/
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
│  └─ Workflow.tsx         The workflow strip. Always the agent-cycle stages.
```

## Conventions

- **One job per page.** If a section is asked to answer a second question, it belongs on its own
  page. The nav is the outline of what the reviewer is trying to find out.

- **The contract is the backend.** `src/types.ts` mirrors `backend/app/models/schemas.py`. Fields
  added there need a matching type here; fields added here need a matching field there.
- **The deterministic critic owns every decision.** The UI explains decisions; it never makes one.
  The simulator re-asks the critic, it does not substitute for it.
- **The agent cycle is the only reasoning path.** There is no Pipeline / Agent cycle toggle and no
  `mode` in the analysis request. The backend always runs the agent cycle, and the workflow strip
  always shows its stages.
- **Disclose the model.** The header badge and the provenance strip name the model that actually
  ran (`llm_model`), and say plainly that the deterministic stand-in was used when
  `llm_backend === "simulated"`. The UI must never imply a model ran when it did not — and a
  payload with no `llm_backend` means "not recorded", not "the stand-in ran".
- **Nothing is applied.** "Accept" records a human decision in the audit log. It does not deploy
  anything, and the frontend says so wherever that could be misread.
- **Every panel degrades.** A failed history, policy or events call returns `Fetched<T>` with
  `failed: true` and the panel shows an empty state — and drops the previous value, because a
  stale number that looks current is worse than no number. A failed *analysis* shows the error
  and leaves the section navigation in place: Policy and History fetch their own data, so a
  failed analysis must not take them out of reach.
- **Show the money that was not counted.** When the critic refuses a reduction the optimizer found,
  the saving moves to `proposal.suppressed_saving_usd`. Any total that means "what the optimizer
  found" adds it; any total that means "what was approved" does not.
