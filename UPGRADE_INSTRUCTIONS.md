# Remote Anywhere Radar — ONE consolidated upgrade

This upgrade is ONLY for the separate `remote-anywhere-radar` GitHub repository. **Do not put these files in `my-job-radar`.**

## Install, once

1. Download and unzip `Remote_Anywhere_Radar_V2_CONSOLIDATED.zip`.
2. Open GitHub Desktop, select `remote-anywhere-radar`, then **Repository → Show in Explorer**.
3. Copy the contents of the extracted `upgrade/` folder into the **root** of this repository, merging `.github/` and `tests/` folders. Allow overwrite for the scanner, config, notification script, and workflow.
4. **DO NOT delete, move, overwrite, or reset any existing `state/` or `output/` folders.** The package deliberately contains neither.
5. In GitHub Desktop review the files, **Commit to main → Push origin**.
6. In the **remote-anywhere-radar** repository, open **Actions → Remote Anywhere Radar - morning and evening → Run workflow → main**.
7. Confirm the run shows a `Remote Anywhere Radar — live health report` with **51 configured** sources, per-source failures, actual fetched counts, and alert funnel. GitHub saves `remote-radar-latest-diagnostics` as an artifact with `raw_jobs_audit.csv` so you can confirm the actual URLs and timestamps.

No new API keys or notification settings are required. Issues/Watch email notifications must already be enabled in that repository.

## Expected behavior

- Twice daily: **08:11 and 20:11 IST** (actual execution/notification can be delayed by GitHub).
- Only your **seven role families**, only **Remote India / Global / Worldwide / Anywhere**. No visa sponsorship or salary filtering.
- Email job table stays **four columns**: Company | Role (link to job) | Posted within 24 hours | Work location.
- The **first v2 run** will include any genuinely qualifying last-24h jobs (the old first-run baseline previously discarded these). It will not spam older jobs.
- Existing `state/seen.json` is kept as historical data, but **never used for v2 alert suppression**. New `state/alerts_v2.json` remembers only successfully qualified alert IDs, avoiding the old 'seen too early' bug.
- Duplicate issues are suppressed for the same India-local slot and job set. When a manual scan discovers genuinely new jobs after a zero-job issue, a separate issue is permitted so the alert is not silently lost.
- An unreadable source is reported, **not counted as a confirmed empty source**. Complete outage prevents state advancement and a misleading no-jobs email.

## Diagnostics

The GitHub Actions run summary displays the complete filtering funnel plus broken sources. After the run:

- `output/summary.json` — overall counts, source statuses, anomalies
- `output/source_health.csv` — all 51 company source statuses and filtering counts
- `output/unreadable_sources.csv` — source-specific errors and adapter requirements
- `output/role_audit.csv` — all title-matching roles, raw geography, date, exclusion reason
- `output/raw_jobs_audit.csv` — all fetched actual listing IDs, titles, raw dates, and URLs
- `output/new_jobs.csv` — the **four-column** email job shortlist

Some sources do not expose an original timestamp. These remain visible in diagnostics, but never become `Posted within 24 hours = Yes` without evidence.

## Fail-safe behavior / rollback

Run **only one manual scan** after uploading. If it fails, open the last failed GitHub Action run and use its automatic diagnostic artifact. Revert the single upgrade commit to restore the old version; no migration deletes `seen.json`. **Do not delete `alerts_v2.json` once it exists** because that could re-send recent jobs.

The ZIP's tests use simulated HTTP provider responses. They establish parser and workflow logic, not live access to all 51 employer sites. Sites with unsupported private JavaScript, CAPTCHA, changed ATS identifiers, or date-free feeds may still be incomplete; they are surfaced in health diagnostics and require provider-specific work if the next GitHub run confirms it.
