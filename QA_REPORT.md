# QA — Remote Anywhere Radar v2 consolidated

- Source: the latest user-run scanner and company configuration, including all prior source fixes and role-audit additions.
- Unit/integration suite: 77 offline tests, using isolated temporary directories and mocked HTTP provider responses.
- Test categories: 51-company roster integrity, Greenhouse/Ashby/Lever/Workable/SmartRecruiters/Pinpoint parsing; location and title restrictions; first-publication vs last-publication; 24-hour time boundaries; website JSON-LD; HTML false-empty detection; pagination; malformed boards; total outage; legacy state untouched; v2 alert state; first-run legitimate alerts; no duplicated scans; Issues email idempotence; four-column report; public URL selection; health report.
- No live ATS HTTP verification for all 51 companies was possible in this execution environment.
- The first GitHub live run, which can access the company endpoints, is the required integration test. Its per-source health table and a diagnostics artifact are uploaded automatically.

- GitHub workflow YAML was parsed successfully; its local-time schedule is 08:11/20:11 Asia/Kolkata, and all outputs are isolated from the older international radar.
