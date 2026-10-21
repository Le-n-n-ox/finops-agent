# Uploading the FinOps dataset to Zetaris

## Prepare the files

From the repository root, run:

```powershell
python scripts/export_zetaris_data.py
```

This writes import-ready CSVs to `data/zetaris_upload/`:

| Upload file | Zetaris table | Expected rows |
| --- | --- | ---: |
| `deployments.csv` | `deployments` | 10 |
| `usage_history.csv` | `usage_history` | 7,200 |
| `business_events.csv` | `business_events` | 5 |
| `incident_history.csv` | `incident_history` | 7 |

The upload version maps the enhanced source columns to the column names expected by the app's Zetaris reader. Mock CPU values derived from the supplied utilization percentages retain the `imputed_mock_cpu` data-quality flag. Event `services` are pipe-separated so Zetaris' CSV file source keeps them in one column; the app converts that value back into a list.

The `finops_policy.json` and `test_scenarios.json` files are copied for reference. The current app connector reads policy and cost settings from local `data/policy.yaml` and `data/cost_model.json`; it does not query the two reference JSON files.

## Upload and register in Zetaris

1. Open **NDP File System**, enter `file-store`, create a folder such as `finops-agent`, and upload the four CSV files. Zetaris documents this flow for CSV/JSON files in its [local file connection guide](https://kbase.zetaris.com/knowledge/how-to-ccnnect-to-json-from-local-machine).
2. In **SQL Workspace**, create or use the `finops_data` virtual file source and register each uploaded CSV with the exact table names in the mapping above. Zetaris requires stored files to be registered as file-source tables before they can be queried ([data connection overview](https://kbase.zetaris.com/knowledge/connect)).
3. Verify the registered tables with:

```sql
SELECT COUNT(*) FROM finops_data.deployments;
SELECT COUNT(*) FROM finops_data.usage_history;
SELECT COUNT(*) FROM finops_data.business_events;
SELECT COUNT(*) FROM finops_data.incident_history;
```

## Point the app at Zetaris

Keep the Zetaris URL, organization ID, and API key in the ignored root `.env` file. Set:

```dotenv
DATA_SOURCE=zetaris
```

Restart the backend (or recreate the Compose services) and check the configured tables with:

```powershell
python scripts/check_zetaris_query.py
```

The connector queries the four `finops_data` tables above. It does not upload files itself; file upload and registration are Zetaris UI steps.
