# Quality assurance — Remote Anywhere Radar

Checked locally with Python standard library and synthetic employer responses.

Automated suite covers: 51-company roster and names; all seven title families; rejection of US/Europe/EMEA-only remote positions and unsafe "Anywhere in the US" wording; India and Global eligibility; exactly 24-hour publication boundary; timezone requirements; Greenhouse/Ashby/Lever/Workable payloads; Greenhouse detail-based `first_published` enrichment; HTML/JSON-LD job discovery; ordinary web pages reporting `NEEDS_ADAPTER` instead of pretending zero jobs; duplicate ID behavior; preserving saved state across outages; corrupted-state refusal; no first-run alert flood; scan 1 → scan 2 new job → scan 3 no duplicate; twice-daily India-local issue titles; issue idempotency; and GitHub permissions failure.

**Validation limitation:** This runner cannot access live career-site APIs (network DNS unavailable), and cannot send a GitHub Issue from a user's private account without GitHub authorization. Passing offline tests does not establish 51 live connections or email delivery. The first GitHub run is the real integration test. The health report is the source of truth for live coverage.

No scraping of inaccessible sites, CAPTCHA circumvention, paid services, or invented jobs.
