# Zetaris — where to start

Goal for Day 1–2: prove you can reach Zetaris and (ideally) expose the three data sources through it. If not, the app keeps using local files (`DATA_SOURCE=local`) and the README says so honestly.

## Steps
1. **Find your connection details** in your Zetaris account/installation: the base URL (SaaS API or server IP), your Org ID, username/password, and API key.
2. **Copy `.env.example` → `.env`** and fill the `ZETARIS_*` values. `.env` is git-ignored — never commit it.
3. **Test login**: `python scripts/check_zetaris.py`. This calls the documented `GET /api/v1.0/auth/login` (Basic auth + `X-Org-ID` + `X-Request-ID`). Success prints the token keys.
4. **Load the data into Zetaris.** Using the Zetaris UI, register the sample data (`data/usage_history.csv`, `deployments.yaml`/`business_events.json` converted to CSV or tables) as data sources so one SQL layer can query them. *Zetaris's UI/connector steps are in its user guides (https://www.zetaris.com/userguides) — follow those; I did not guess them.*
5. **Run a query** from the Zetaris SQL console first (e.g. `SELECT service, cpu_millicores FROM usage_history LIMIT 5`) so you know the table names.
6. **Implement `ZetarisClient.query()`** from the Redoc SQL Query endpoints (start → page → close): https://api.saas.enterprise.zetaris.com/redoc/index.html
7. **Implement `load_inputs_from_zetaris()`** returning the same `InputBundle` as `load_inputs()`. Switch with `DATA_SOURCE=zetaris`.

## Other access paths (from the Zetaris KB)
- JDBC (Enterprise): `jdbc:zetaris:lightning@<host>:10000`, driver jar from the KB. ODBC is also available. Python has no documented native client, so REST is the practical route.

## If it doesn't work by Day 2
Stay on local files, record what blocked you (no access / no connector / auth), and move on. The adapter boundary means nothing else changes.
