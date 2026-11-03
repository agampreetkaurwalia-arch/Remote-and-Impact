#!/usr/bin/env python3
"""Exactly one GitHub Issue per India-local morning/evening slot.
The user's existing GitHub email notifications deliver these Issues as email.
No issue is created by unit tests; the workflow calls this only after live scan.
"""
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent


def issue_title(scanned_utc):
    local = datetime.fromisoformat(scanned_utc.replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Kolkata'))
    slot = 'morning' if local.hour < 14 else 'evening'
    return f'Remote Anywhere Radar | {local:%Y-%m-%d} | {slot}'


def notify(root=ROOT, *, env=None, invoke=None):
    env = dict(os.environ if env is None else env)
    if not env.get('GH_TOKEN') or not env.get('GITHUB_REPOSITORY'):
        raise RuntimeError('GitHub Issue notifications require GH_TOKEN and GITHUB_REPOSITORY')
    live = invoke is None
    invoke = invoke or subprocess.run
    summary = json.loads((root / 'output' / 'summary.json').read_text(encoding='utf-8'))
    title = issue_title(summary['scanned_utc'])
    repo = env['GITHUB_REPOSITORY']
    args = ['gh', 'issue', 'list', '--repo', repo, '--state', 'all', '--limit', '100', '--json', 'title']
    listing = invoke(args, capture_output=True, text=True, env=env, check=True)
    issues = json.loads(listing.stdout)
    if any(x.get('title') == title for x in issues):
        if live:
            print('Already notified for this India-time slot; no duplicate Issue.')
        return 'already_sent'
    body = root / 'output' / 'email.md'
    invoke(['gh', 'issue', 'create', '--repo', repo, '--title', title,
            '--body-file', str(body)], capture_output=True, text=True, env=env, check=True)
    if live:
        print(f'Created email-notification Issue: {title}')
    return 'sent'


if __name__ == '__main__':
    notify()
