# Remote Anywhere Radar — separate from the international Job Radar

A free, independent GitHub Actions job-monitoring project. **51 companies are configured for checking**. It runs at **8:11 AM and 8:11 PM India time**, and creates a GitHub Issue for **each** scan. If you enable email notifications for issues, you receive the morning and evening digests in your inbox—even when there are zero matches.

**The email has exactly four columns:** Company | Role (click to apply) | Posted within 24 hours | Work location.

## Requirements implemented

- Company roster: the 47 companies from Zapier's work-from-anywhere list, plus Fingerprint, Strike, Brave and Alpaca.
- Title matches **consulting, strategy, founder's associate, chief of staff, program manager, project manager or product manager**. No AI fit scores.
- Vacancy explicitly advertises **Remote Global / Anywhere / Worldwide** or **Remote India**. A general corporate worldwide-work policy does **not** override a vacancy that says US-only or EMEA-only.
- A usable employer publication timestamp within the last 24 hours. No date, date-only value, or stale publication = not emailed.
- No visa/salary/contract checks, as requested. No other columns in the digest.
- Two issues per India-local day, with email delivery through GitHub's existing issue-notification mechanism.
- First scan records a baseline, avoiding a blast of pre-existing vacancies. The next scan emails newly discovered, matching requisitions.

## What is actually connected?

**11 companies have pre-mapped public ATS boards** using Greenhouse (5), Ashby (5), or Lever (1). Their publicly visible career-board URLs were checked on the web; their APIs must still be tested in a real GitHub run.

**40 more companies have their career pages configured**. The scanner automatically discovers linked Greenhouse, Ashby, Lever, and Workable boards or reads public schema.org `JobPosting` markup, including structured job-detail pages linked from the careers page. Some employer sites are JavaScript-only or otherwise block automated reading. These are reported as `NEEDS_ADAPTER` or `ERROR` in `output/source_health.csv`. **Having 51 rows does not mean 51 operational integrations.**

This distinction is intentional: unlike earlier versions, an unreadable career site is never counted as monitored successfully. `output/summary.json` shows the actual live count.

### Employer date evidence

- Greenhouse: `first_published` (requests individual job details when omitted from its list response).
- Ashby: `publishedAt` (the *most recent publication*; can be a repost of an older vacancy).
- Lever: `createdAt` *only if actually available on a public posting*; otherwise its jobs are not labeled as posted within 24h.
- Public career sites: schema.org `JobPosting.datePosted` with a full timezone-aware time, if provided.
- Workable: a usable exact posting timestamp, if its public widget exposes one.

If the employer supplies **only a calendar date**, the radar cannot prove it falls within the previous 24 hours and excludes it from email. Because some providers record last publication rather than original publication, a recently republished job may still appear.

## Outputs

- `output/email.md` — four-column digest sent via GitHub Issues (with zero-result explanation)
- `output/new_jobs.csv` — same four columns, only newly matching jobs
- `output/current_24h.csv` — same four columns, all currently qualifying jobs
- `output/source_health.csv` — separate diagnostics for each of the 51 companies
- `output/summary.json` — per-run totals
- `state/seen.json` — persistent seen requisition IDs

Never delete `state/seen.json` during normal use. A broken state file causes a loud error, not a silent reset. The scanner stages its updated state and only commits it after GitHub successfully creates the notification Issue.

## What this project does **not** do

It does not bypass blocked sites, bypass CAPTCHA, use paid APIs, claim every website is readable, or guarantee that GitHub runs at exactly the scheduled minute. It also cannot guarantee remote eligibility beyond the job's stated location. **The release is offline-tested, not yet live-deployed or receiving email.** Follow `START_HERE.md` once to activate it.
