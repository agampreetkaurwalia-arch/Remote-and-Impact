"""Present source failures and scan-filter diagnostics in GitHub Actions Summary.
No external imports, credentials or test side effects.
"""
from pathlib import Path
import csv
import json
import sys

ROOT=Path(__file__).resolve().parent

def report(root=ROOT):
    s=json.loads((root/'output'/'summary.json').read_text(encoding='utf-8'))
    lines=['## Remote Anywhere Radar — live health report','',
           f"**{s['sources_readable']}/{s['companies_configured']} readable sources; {s['jobs_fetched']} jobs fetched**",'',
           '| Filter stage | Count |','|---|---:|',
           f"| Matching role titles | {s['matching_role_titles']} |",
           f"| Matching India / Global / Anywhere | {s['matching_india_global_locations']} |",
           f"| With usable publication date | {s['matching_with_usable_publication_time']} |",
           f"| Published within 24h | {s['matching_postings_within_24h']} |",
           f"| Newly alertable | {s['new_matches']} |",'']
    anomalies=s.get('scan_anomalies') or []
    if anomalies:
        lines.append('**Scan anomalies:** '+ '; '.join(anomalies)); lines.append('')
    with (root/'output'/'unreadable_sources.csv').open(encoding='utf-8',newline='') as f:
        missing=list(csv.DictReader(f))
    if missing:
        lines.extend(['### Sources requiring repair','', '| Company | Status | Error |','|---|---|---|'])
        for row in missing:
            err=(row.get('Error / limitation') or '')[:140].replace('|','/').replace('\n',' ')
            lines.append('| '+row['Company'].replace('|','/')+' | '+row['Status']+' | '+err+' |')
    else:
        lines.append('All configured sources were readable in this run.')
    lines.extend(['','See tracked `output/raw_jobs_audit.csv` for real job IDs, titles and dates.',''])
    return '\n'.join(lines)

if __name__=='__main__':
    print(report())
