# Cursor prompts for Developer 1

Open the repo folder in Cursor. Project rules in `.cursor/rules/finops.mdc` load automatically. One module per prompt; always ask for tests.

**#1 loader**
> Implement `load_inputs` and `validate_inputs` in `backend/app/services/data_loader.py` for the files in `data/`, returning the `InputBundle` from `app/models/schemas.py`. Use yaml.safe_load, pandas, json. Raise clear ValueError for missing/malformed files; flag unknown services, negative usage, bad timestamps and duplicates as `ValidationIssue`s. Do not change schemas.py. Make the xfail tests in `backend/tests/test_data_loader.py` pass (remove the marker) and add edge cases. Run `pytest -q`.

**#2 optimizer**
> Implement `build_proposals` in `backend/app/services/optimizer_service.py` following the docstring and the thresholds in `bundle.policy.optimizer`. Pure deterministic Python; accept an explicit `now`. Requests only; round up; one proposal per service. Make `backend/tests/test_optimizer.py` pass and add tests for peak-near-request and no_change. Run `pytest -q`.

**#3 Zetaris** — see `docs/ZETARIS_SETUP.md`; ask Cursor to implement `ZetarisClient.query()` *from the Redoc spec you paste in*, not from memory.
