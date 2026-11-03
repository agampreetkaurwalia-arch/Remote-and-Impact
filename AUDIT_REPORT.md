# Consolidated audit — Remote Anywhere Radar (3 November 2026)

## Actual input evidence

Three GitHub runs were supplied by the user:

| Run | Configured | Readable | Jobs fetched | Title matches | India/Anywhere matches | With parseable publish time | Under 24h |
|---|---:|---:|---:|---:|---:|---:|---:|
| Initial | 51 | 19 | 458 | Not reported | Not reported | Not reported | 0 |
| Source repair | 51 | 28 | 502 | Not reported | Not reported | Not reported | 0 |
| Latest diagnostic | 51 | 32 | 504 | 72 | 6 | 6 | 0 |

**The last zero was not automatically a bug:** the six jobs passing geography and role filters were timestamped outside the observed 24h period. However, no full conclusions can be made while 19 sources are unreadable, and the original summary did not show which jobs were excluded.

## Confirmed structural problems in the prior code

1. **Missing coverage:** 19 of 51 were broken or unsupported. An array of company names was mistaken for live monitored coverage. Corrective action: direct ATS where supported; comprehensive per-source error diagnostics.
2. **Incorrect source type:** employer websites for Pinpoint (SafetyWing, YNAB) were treated as generic HTML. Pinpoint documents a public `postings.json` job feed; this release uses it.
3. **Unmatched actual source:** Fingerprint has a publicly identified Greenhouse board but was configured as an unsupported website. Release sets board slug `fingerprint` (still requires a live scan to verify its API response).
4. **Location field loss:** Lever's `allLocations` was ignored whenever `location` was present; Ashby's `secondaryLocations` was ignored. This could hide India-eligible jobs. Both are retained now.
5. **Over-strict location parsing:** remote India stated in a title did not count when the ATS location field said simply `India`. This is fixed. Explicit US/Europe country restrictions still win.
6. **No use of job descriptions:** job summaries labelled only `Remote` could omit explicit 'work from anywhere' text in the full ATS posting. Greenhouse job details and descriptions from the other feeds can now supply explicit worldwide/India language.
7. **Alert history poisoned before qualification:** the old scanner marked **all fetched job IDs** as seen before testing role, geography, publication timestamp, or 24h freshness. A job that later acquired correct metadata could be permanently suppressed. V2 state records only alertable IDs.
8. **First-run baseline suppressed useful recent jobs:** previously every first run forced zero new alerts. Now provably recent postings can be emailed on the first v2 scan.
9. **False empty-source risks:** vague 'no jobs' text anywhere in a webpage could mark a live company as EMPTY even if the phrase was in a hidden template. A website empty result now requires an explicit no-positions heading; API empty results remain distinct from failures.
10. **No real-job evidence:** earlier diagnostics presented only aggregate counts. New `raw_jobs_audit.csv` captures actual listing titles, IDs, dates, ATS adapter, and links. Per-role rejection audit remains separate from the four-column email.
11. **Outage and stale-output problems:** all-site failure could misleadingly produce zero jobs and overwrite history; old committed summary could show up after a failed run. V2 fails closed on total outage and removes stale run markers first.
12. **Duplicate / missed email scenario:** an empty morning issue already created could suppress later genuinely new jobs found during a manual rescan in that same slot. V2 fingerprints the job set to allow new-content alerts, while preventing duplicate retries.
13. **Pagination:** SmartRecruiters board query previously fetched only the first 100 records and could miss later pages. V2 fetches pages with a 500 cap; truncation needs source monitoring.
14. **Provider anomalies:** malformed job items are no longer accepted as successfully fetched listings when all records lack IDs, titles, or application URLs.
15. **Reliability monitoring:** each run compares against its prior scan for source-health / volume collapse and surfaces errors in the Actions summary; diagnostics are also uploaded as a run artifact.

## Source evidence / checks

- GitHub live run summaries above: provided by the user.
- Greenhouse Job Board API documentation: https://docs.greenhouse.io/job-board
- Ashby Job Postings API: https://developers.ashbyhq.com/docs/public-job-posting-api
- Pinpoint JSON Postings API: https://developers.pinpointhq.com/docs/jobs-json-endpoint
- Pinpoint job feed overview: https://developers.pinpointhq.com/docs/job-feeds-overview
- SafetyWing official careers page currently displays job openings: https://safetywing.pinpointhq.com/en
- Remote's official Greenhouse careers page showed **no current openings** on the checked page, even when an older search result showed many: https://job-boards.greenhouse.io/remotecom/
- Fingerprint official hiring page: https://fingerprint.com/careers/jobs/

## Still not proven

This environment cannot authenticate to or run code against the private GitHub repository; its Python runtime cannot reliably reach all 51 live career APIs. Therefore:
- **No claim** that all 51 sites are now successfully monitored.
- No claim that the 19 historical failures are all cured. The next GitHub run will give the actual outcome and exact remaining errors.
- Pinpoint's public `postings.json` doesn't document a publication timestamp. It can make a source readable without making any of its jobs strictly 24h alertable. Detailed role pages are checked for JobPosting date markup where available.
- Company-specific JavaScript and bot/access restrictions may remain unsupported. Exact reliable 24h publication evidence may not be exposed by some employers. A strict filter must leave these jobs out rather than invent a timestamp.
- The scheduler is GitHub's; it may run late. Actual Issues email depends on GitHub notification settings and delivery.

This is a consolidated repair of all demonstrated architectural defects, not a promise that providers won't change their job systems later.
