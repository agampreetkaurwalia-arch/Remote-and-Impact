# Remote Anywhere Radar — source and diagnosis repair (2026-11-03)

## What this addresses

The real second scan reported 28/51 readable sources, 502 jobs, and 0 matching jobs within 24 hours. These figures do not prove that no suitable roles exist across 51 companies.

This patch replaces four generic website configurations with employer-linked ATS connections:

| Company | Previous status | New adapter | Source |
|---|---|---|---|
| Remote | NEEDS_ADAPTER | Greenhouse `remotecom` | https://job-boards.greenhouse.io/remotecom |
| Kinsta | NEEDS_ADAPTER | Lever `kinsta` | https://jobs.lever.co/kinsta |
| Doist | NEEDS_ADAPTER | Workable `doist` | https://apply.workable.com/doist/ |
| Whereby | NEEDS_ADAPTER | Lever `whereby` | https://jobs.lever.co/whereby |

Doist expressly says locations on its Workable listings are for advertising and its remote roles are location-independent. Its config has a narrowly scoped policy exception. Other global employer policies must not override role locations like Remote US/UK/EU/EMEA/APAC/Americas.

The summary now shows where jobs are eliminated: `jobs_fetched`, `matching_role_titles`, `matching_india_global_locations`, `matching_with_usable_publication_time`, `matching_postings_within_24h`, `new_matches`.

## Install

1. Extract the ZIP into the separate `remote-anywhere-radar` repo.
2. Replace only root `companies.json` and `remote_radar.py`.
3. Add `tests/test_diagnostic_repair.py` (keep all existing tests).
4. Commit and push via GitHub Desktop.
5. Manually trigger the existing **Remote Anywhere Radar - morning and evening** Actions workflow.
6. Inspect `output/summary.json` and `output/source_health.csv`. The health CSV has individual source errors and per-company filter counts.

Do not modify `state/`, `output/`, `notify.py`, `.github/workflows/`, or the original international radar.

## QA and limits

**51/51 offline tests passed** (46 existing, 5 additional). Tests use simulated HTTP responses. The local runtime cannot reach employer ATS APIs, so these four adapters are **not yet verified live**.

If all four succeed, readable coverage could rise from 28 to 32 of 51. The 19 other previously unreadable sources remain unresolved. Toggl is currently ERROR despite its public Ashby careers board; the exact HTTP error cannot be diagnosed from `summary.json` and requires `output/source_health.csv`.

Strict 24-hour evidence remains in force. Missing or date-only publication data is never described as verified within 24 hours. A live run can still return zero matches even after all connections work.
