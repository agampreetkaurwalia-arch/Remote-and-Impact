# Start here — one-time GitHub setup (new, separate repo)

**Do not put these files in your existing `my-job-radar` repo.** This is a separate remote-only radar.

1. Download the `Remote_Anywhere_Radar_51_Companies.zip` archive and select **Extract All**.
2. In GitHub, create a **new private repository** called `remote-anywhere-radar` at https://github.com/new. Enable **Issues** under the repository Settings if they are off.
3. In GitHub Desktop, **File → Clone repository**, select the new repository, then **Repository → Show in Explorer**.
4. Copy **the contents** of the extracted `Remote_Anywhere_Radar` folder into the cloned repository root. Make sure `.github/workflows/remote-anywhere-radar.yml`, `remote_radar.py`, `notify.py`, `companies.json`, and `tests/` exist in the correct locations. Do not upload the ZIP as one file.
5. In GitHub Desktop choose **Commit to main → Push origin**.
6. Open the new repository: **Settings → Actions → General → Workflow permissions → Read and write permissions** and save. The workflow also declares `contents: write` and `issues: write`.
7. Go to the repository main page, choose **Watch → Custom → Issues**, and select email delivery at https://github.com/settings/notifications. This is the same notification mechanism that worked for your existing radar, but **watching the old repository does not automatically watch this new one**.
8. Open **Actions → Remote Anywhere Radar - morning and evening → Run workflow**, select `main`, and run it once. The first run creates a baseline, and sends the first status email if notifications are enabled.
9. Check `output/summary.json` and `output/source_health.csv`. Company career sites marked `NEEDS_ADAPTER` are *not yet genuinely monitored*; `OK` or `EMPTY` are readable sources. Never interpret 51 configured as 51 healthy.

## Regular delivery

**8:11 AM and 8:11 PM India time daily.** The workflow uses GitHub's timezone-aware schedule in `Asia/Kolkata`. GitHub can delay scheduled runs; these are targets, not exact delivery guarantees. Each successful run creates a new GitHub Issue in the new repo and GitHub emails you about it if your email notification settings permit.

Emails contain just the four requested columns. A zero-results digest is still sent. Individual roles are clickable links to the posting.

## When something doesn't work

- **No workflow in Actions:** check `.github/workflows/remote-anywhere-radar.yml` is committed on `main` in the *new* repo.
- **Workflow permissions denied:** check Settings → Actions → General → Workflow permissions; ensure Issues is enabled.
- **First email has zero new jobs:** expected baseline behavior; look in `current_24h.csv` for already posted matching positions.
- **Many companies show `NEEDS_ADAPTER`:** their careers pages are not machine-readable; this isn't proof they have zero vacancies. Do not expect alerts from those employers until their adapters are built or an official ATS feed is found.
- **Broken job history:** do not delete the state file. Restore it from Git history instead.
- **Read job report:** open `output/current_24h.csv` or `new_jobs.csv` in GitHub; emails are generated from `output/email.md`.

No paid API keys, Gmail app passwords, Python installation on your computer, or changes to the old radar are needed.
