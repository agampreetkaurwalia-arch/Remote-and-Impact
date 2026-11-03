# Operations and troubleshooting

This is an independently scheduled project. Do not copy it into `my-job-radar`, whose code and state remain unchanged.

## First live scan

Run GitHub **Actions → Remote Anywhere Radar - morning and evening → Run workflow**. The first run only establishes saved history. `output/current_24h.csv` can still contain currently matching vacancies; the email's **new** column is empty until a subsequent scan sees a newly added matching job ID.

Read `output/source_health.csv` after the first scan:

- `OK`: API or structured careers page was readable and provided at least one record
- `EMPTY`: readable source explicitly returned no postings
- `NEEDS_ADAPTER`: careers page was reachable but did **not** expose a supported public feed, JobPosting markup, or parseable job-detail pages; not a functioning integration
- `DEGRADED`: partial data; some individual job details could not be read
- `ERROR`: source failure; other company sources still process normally

There is no claim that all 51 source URLs work from GitHub. The live report provides the counts.

## Email issues

The workflow creates a new GitHub Issue per India-local morning or evening slot. Under the **new repository**, enable **Watch → Custom → Issues**, and set email delivery in GitHub notifications. A zero-result email is intentional. If no email arrives, first inspect the latest **Actions** run and then **Issues**; if the Issue exists, check notification settings or spam. If the Issue does not exist, expand the `Email morning/evening digest` Actions step. Private repos must allow Issues, and Actions must have write permissions.

## Source errors

Do not keep adding unverified ATS slugs or broad aggregators. If a source is `NEEDS_ADAPTER`, use its current public careers URL to identify its actual job-system provider. When an employer adds a Greenhouse/Lever/Ashby board, set the company's `type` and `slug` in `companies.json`; preserve the company name. The scanner does not bypass CAPTCHAs, sign-in requirements, or access restrictions.

## Email timing and duplicates

GitHub schedules target 08:11 and 20:11 **Asia/Kolkata**. GitHub can delay them. A repeated manual scan within the same local time slot does not create a duplicate Issue. The `state/seen.json` file remembers previously observed job IDs; do not delete it. If a new job appears after a manually created digest in the same time slot, the next scheduled digest may be needed to report it; the current simple slot deduplication prevents repeated status emails.

## Evidence limitations

A date missing from a public feed is not a verified 24h posting; such a listing is excluded from the four-column digest. Ashby reports last publication and can republish existing jobs; the system cannot distinguish all reposts. Some job sites provide only JavaScript-rendered vacancies; they remain uncovered until an official public feed or supported adapter exists. The system uses job-level locations, not a company's generic remote policy.
