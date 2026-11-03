# Remote Anywhere Job Radar — v2 consolidated

A private, free, GitHub Actions-based monitor for the 51 companies selected by the user. It checks postings every morning and evening at 08:11 and 20:11 IST. Each email contains exactly four job columns:

| Company | Role | Posted within 24 hours | Work location |
|---|---|---|---|

A job is included only when its title matches the seven selected role families, the advertised remote geography includes India or Global/Anywhere, and a defensible publication timestamp falls within the previous 24 hours. Visa checks and salary filters are not part of this radar. The Role column contains the job's application link.

Read `UPGRADE_INSTRUCTIONS.md` first, then `AUDIT_REPORT.md` for root causes and limitations. This version introduces `state/alerts_v2.json` and keeps legacy `state/seen.json` intact.

The main program is `remote_radar.py`, with `notify.py` for GitHub Issues email, `health_summary.py` for Actions diagnostics, and `companies.json` for the employer roster. Run local regression tests with `python -m unittest discover -s tests -v`.
