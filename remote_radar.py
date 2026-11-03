#!/usr/bin/env python3
"""Remote Anywhere Job Radar. Python standard library only.

The sole email shortlist is role + remote Global/Anywhere/India + a timestamp
of publication within 24 hours. A missing timestamp NEVER becomes a match.
Every roster member is checked; unreadable career pages are reported rather
than silently counted as successfully monitored.
"""
import csv
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urljoin
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo('Asia/Kolkata')
MAX_BYTES = 5_000_000
ROLE_RX = re.compile(
    r"\b(?:consultant|consulting|strateg(?:y|ic|ist)(?:\s+(?:operations|initiatives|programs))?|"
    r"founder['’]?s?\s+associate|chief\s+of\s+staff|"
    r"(?:technical\s+)?program(?:me)?\s+manager|"
    r"(?:technical\s+)?project\s+manager|"
    r"(?:technical\s+)?product\s+manager|"
    r"strategy\s*(?:&|and|/)\s*operations|bizops)\b", re.I)
GLOBAL_RX = re.compile(r"\b(?:global(?:ly)?|world\s*-?\s*wide|anywhere|work\s+from\s+anywhere|any\s+location)\b", re.I)
INDIA_RX = re.compile(r"\bindia\b", re.I)
REMOTE_RX = re.compile(r"\b(remote|work\s+from\s+(?:home|anywhere)|distributed|telecommut(?:e|ing))\b", re.I)
RESTRICTED_RX = re.compile(
    r"\b(?:united\s+states(?:\s+only)?|u\.?s\.?a?\.?\s+only|"
    r"(?:US|UK|EU|EMEA|LATAM|APAC|Europe|Americas|Canada|Australia|North\s+America)\s*[-–]?\s*only|"
    r"only\s+(?:in|within|from)\s+(?:the\s+)?(?:US|UK|EU|EMEA|Europe|Americas|Canada|Australia|North\s+America)|"
    r"(?:US|UK|EU|Europe|Americas|Canada|Australia|North\s+America)[- ]based|"
    r"must\s+(?:live|reside|be\s+based)\s+in\s+(?:the\s+)?(?:US|USA|UK|EU|Europe|Canada|Australia))\b", re.I)
ATS_RX = [
    ('ashby', re.compile(r'https?://jobs\.ashbyhq\.com/([a-zA-Z0-9._-]+)', re.I)),
    ('lever', re.compile(r'https?://jobs\.lever\.co/([a-zA-Z0-9._-]+)', re.I)),
    ('greenhouse', re.compile(r'https?://(?:job-boards|boards)\.greenhouse\.io/([a-zA-Z0-9._-]+)', re.I)),
    ('workable', re.compile(r'https?://apply\.workable\.com/([a-zA-Z0-9._-]+)', re.I)),
]

@dataclass(frozen=True)
class Job:
    company: str
    ident: str
    title: str
    location: str
    workplace: str
    timestamp: str
    date_basis: str
    url: str


def get_text(url, *, fetch=None):
    if fetch is not None:
        value = fetch(url)
        return value.decode('utf-8') if isinstance(value, bytes) else value
    if not url.startswith('https://'):
        raise ValueError('Only HTTPS data endpoints allowed')
    req = Request(url, headers={
        'User-Agent': 'RemoteAnywhereRadar/1.0 (personal job alert monitoring)',
        'Accept': 'application/json,text/html,application/ld+json;q=0.9,*/*;q=0.2',
    })
    for retry in range(2):
        try:
            with urlopen(req, timeout=12) as resp:
                data = resp.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError('Response exceeded size limit')
                return data.decode('utf-8', 'replace')
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or retry == 1:
                raise
            delay = exc.headers.get('Retry-After', '1')
            try:
                delay = min(3, max(0, int(delay)))
            except ValueError:
                delay = 1
            time.sleep(delay)
        except (TimeoutError, URLError):
            if retry == 1:
                raise
            time.sleep(0.5)
    raise RuntimeError('Unexpected HTTP retry state')


def parse_timestamp(value):
    """A calendar day without time is not sufficient for a strict 24h test."""
    if isinstance(value, (float, int)):
        seconds = float(value)
        if seconds > 1e12:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if re.fullmatch(r'\d{10,13}', value):
        return parse_timestamp(int(value))
    if not re.search(r'T\d\d:\d\d|\s\d\d:\d\d', value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def remote_region(job):
    """Returns only the three scopes requested; avoids company-policy inference."""
    loc = ' '.join(str(job.location).split())
    scope = GLOBAL_RX.search(loc)
    india = INDIA_RX.search(loc)
    workplace = str(job.workplace).strip().lower().replace('-', '')
    if workplace in ('hybrid', 'onsite', 'on site'):
        return ''
    remote = (REMOTE_RX.search(loc) or workplace in ('remote', 'telecommute')
              or re.search(r'\b(?:anywhere|world\s*-?\s*wide)\b', loc, re.I))
    if not remote:
        return ''
    # If India is explicitly allowed, other named locations don't disqualify it.
    if india:
        return 'India'
    if RESTRICTED_RX.search(loc) or re.search(
        r'\banywhere\s+(?:in|within|across)\s+(?:the\s+)?(?:US|USA|United States|UK|EU|Europe|Canada|Australia|Americas|EMEA)\b',
        loc, re.I):
        return ''
    if scope:
        return 'Global / Anywhere'
    return ''


def role_matches(title):
    return bool(ROLE_RX.search(title or ''))


def recent(dt, now, hours=24):
    return dt is not None and now - timedelta(hours=hours) <= dt <= now + timedelta(minutes=5)


def parse_greenhouse(company, payload):
    jobs = payload.get('jobs')
    if not isinstance(jobs, list):
        raise ValueError('Greenhouse payload lacks jobs list')
    for item in jobs:
        if not isinstance(item, dict):
            continue
        loc_obj = item.get('location') or {}
        loc = loc_obj.get('name') if isinstance(loc_obj, dict) else str(loc_obj)
        yield Job(company, str(item.get('id', '')), str(item.get('title') or ''),
                  str(loc or ''), '',
                  str(item.get('first_published') or ''), 'first_published',
                  str(item.get('absolute_url') or ''))


def parse_ashby(company, payload):
    jobs = payload.get('jobs')
    if not isinstance(jobs, list):
        raise ValueError('Ashby payload lacks jobs list')
    for item in jobs:
        if not isinstance(item, dict) or item.get('isListed') is False:
            continue
        yield Job(company, str(item.get('id', '')), str(item.get('title') or ''),
                  str(item.get('location') or ''), str(item.get('workplaceType') or ''),
                  str(item.get('publishedAt') or ''), 'last_published',
                  str(item.get('jobUrl') or item.get('applyUrl') or ''))


def parse_lever(company, payload):
    if not isinstance(payload, list):
        raise ValueError('Lever payload not a list')
    for item in payload:
        if not isinstance(item, dict):
            continue
        cat = item.get('categories') or {}
        loc = cat.get('location') or ''
        if not loc and isinstance(cat.get('allLocations'), list):
            loc = ', '.join(str(i) for i in cat['allLocations'])
        yield Job(company, str(item.get('id', '')), str(item.get('text') or ''),
                  str(loc), str(item.get('workplaceType') or ''),
                  str(item.get('createdAt') or ''), 'created_at_if_available',
                  str(item.get('hostedUrl') or item.get('applyUrl') or ''))


def parse_workable(company, payload):
    jobs = payload.get('jobs')
    if not isinstance(jobs, list):
        raise ValueError('Workable widget payload lacks jobs')
    for item in jobs:
        if not isinstance(item, dict):
            continue
        loc = item.get('location') or {}
        if isinstance(loc, dict):
            loc = loc.get('location_str') or loc.get('city') or ''
        yield Job(company, str(item.get('shortcode') or item.get('id') or ''),
                  str(item.get('title') or ''), str(loc),
                  'Remote' if item.get('telecommuting') is True else '',
                  str(item.get('published_on') or item.get('published_at') or item.get('created_at') or ''),
                  'workable_published_if_available',
                  str(item.get('url') or item.get('application_url') or ''))


class StructuredPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.recording = False
        self.current = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'script':
            a = dict(attrs)
            self.recording = a.get('type', '').lower() == 'application/ld+json'
            if self.recording:
                self.current = []
    def handle_data(self, data):
        if self.recording:
            self.current.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self.recording:
            self.scripts.append(''.join(self.current))
            self.recording = False


class CareerLinkParser(HTMLParser):
    """Read static HTML job links. Do not infer dates from anchor order or text."""
    def __init__(self):
        super().__init__()
        self.links = []
        self.active = None
        self.words = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a' and self.active is None:
            self.active = dict(attrs).get('href', '')
            self.words = []
    def handle_data(self, data):
        if self.active is not None:
            self.words.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == 'a' and self.active is not None:
            self.links.append((self.active, ' '.join(''.join(self.words).split())))
            self.active = None
            self.words = []


def candidate_detail_links(page, base_url, max_links=16):
    parser = CareerLinkParser()
    parser.feed(page)
    host = urlparse(base_url).hostname or ''
    found = []
    for href, label in parser.links:
        if not (role_matches(label) and href):
            continue
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != host:
            continue
        if url not in found:
            found.append(url)
        if len(found) >= max_links:
            break
    return found


def jobposting_nodes(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from jobposting_nodes(x)
    if isinstance(obj, dict):
        types = obj.get('@type', [])
        if isinstance(types, str):
            types = [types]
        if 'JobPosting' in types:
            yield obj
        for field in ('@graph', 'mainEntity', 'itemListElement'):
            if field in obj:
                yield from jobposting_nodes(obj[field])


def parse_jsonld_jobs(company, page, base_url):
    parser = StructuredPage()
    parser.feed(page)
    for script in parser.scripts:
        try:
            payload = json.loads(html.unescape(script))
        except (ValueError, TypeError):
            continue
        for p in jobposting_nodes(payload):
            locreq = p.get('applicantLocationRequirements') or []
            if isinstance(locreq, dict):
                locreq = [locreq]
            allowed = []
            for req in locreq:
                if isinstance(req, dict):
                    allowed.append(str(req.get('name') or req.get('addressCountry') or ''))
                elif isinstance(req, str):
                    allowed.append(req)
            jl = p.get('jobLocation') or []
            if isinstance(jl, dict):
                jl = [jl]
            loc = ' / '.join(a for a in allowed if a)
            if not loc:
                parts = []
                for x in jl:
                    a = x.get('address') if isinstance(x, dict) else None
                    if isinstance(a, dict):
                        parts.append(str(a.get('addressCountry') or a.get('addressLocality') or ''))
                loc = ', '.join(p for p in parts if p)
            workplace = 'Remote' if str(p.get('jobLocationType') or '').upper() == 'TELECOMMUTE' else ''
            if workplace and not loc and p.get('jobLocationType'):
                loc = 'Remote'  # never assume global
            url = p.get('url') or base_url
            if not isinstance(url, str):
                url = base_url
            url = urljoin(base_url, url)
            title = str(p.get('title') or '')
            ident = hashlib.sha256((url + title).encode()).hexdigest()[:22]
            yield Job(company, ident, title, loc, workplace,
                      str(p.get('datePosted') or ''), 'jsonld_datePosted', url)


def discover_ats(page):
    matches = []
    page = html.unescape(page).replace('\\/', '/')
    for source_type, rx in ATS_RX:
        for m in rx.finditer(page):
            slug = m.group(1).lower().strip('.')
            if slug not in ('jobs', 'apply', 'career', 'careers') and (source_type, slug) not in matches:
                matches.append((source_type, slug))
    return matches[:3]


def endpoint(kind, slug):
    s = quote(slug, safe='.-_')
    if kind == 'greenhouse':
        return f'https://boards-api.greenhouse.io/v1/boards/{s}/jobs'
    if kind == 'ashby':
        return f'https://api.ashbyhq.com/posting-api/job-board/{s}'
    if kind == 'lever':
        return f'https://api.lever.co/v0/postings/{s}?mode=json'
    if kind == 'workable':
        return f'https://apply.workable.com/api/v1/widget/accounts/{s}?details=true'
    raise ValueError(f'Unknown ATS: {kind}')

PARSERS = {'greenhouse': parse_greenhouse, 'ashby': parse_ashby,
           'lever': parse_lever, 'workable': parse_workable}


def enrich_greenhouse(company, slug, jobs, fetch=None):
    """Greenhouse listing may omit first_published. Read the job detail only
    for target-role remote vacancies; never mistake updated_at for publish date.
    """
    missing = [j for j in jobs if role_matches(j.title) and remote_region(j)
               and not j.timestamp and j.ident]
    selected = missing[:40]
    replacements = {}
    failed = 0
    for j in selected:
        try:
            detail = json.loads(get_text(
                f'https://boards-api.greenhouse.io/v1/boards/{quote(slug, safe=".-_")}/jobs/{quote(j.ident, safe="")}',
                fetch=fetch))
            replacements[j.ident] = Job(j.company, j.ident, j.title, j.location,
                                       j.workplace, str(detail.get('first_published') or ''),
                                       'first_published', j.url)
        except (ValueError, TypeError, KeyError, HTTPError, URLError, TimeoutError):
            failed += 1
    updated = [replacements.get(j.ident, j) for j in jobs]
    warning = ''
    if len(missing) > len(selected):
        warning = f'{len(missing) - len(selected)} matching job details not fetched (40 per-board cap)'
    if failed:
        warning = (warning + '; ' if warning else '') + f'{failed} detail requests failed'
    return updated, warning


def fetch_company(source, *, fetch=None):
    name, kind = source['name'], source['type']
    try:
        if kind in PARSERS:
            raw = get_text(endpoint(kind, source['slug']), fetch=fetch)
            jobs = list(PARSERS[kind](name, json.loads(raw)))
            warning = ''
            if kind == 'greenhouse':
                jobs, warning = enrich_greenhouse(name, source['slug'], jobs, fetch=fetch)
            return jobs, 'DEGRADED' if warning else ('OK' if jobs else 'EMPTY'), warning, kind
        if kind != 'website':
            raise ValueError('Unrecognized company source type')
        page = get_text(source['careers'], fetch=fetch)
        # Only use a publicly linked ATS board, not guessed identifiers.
        errors = []
        for provider, slug in discover_ats(page):
            try:
                raw = get_text(endpoint(provider, slug), fetch=fetch)
                jobs = list(PARSERS[provider](name, json.loads(raw)))
                warning = ''
                if provider == 'greenhouse':
                    jobs, warning = enrich_greenhouse(name, slug, jobs, fetch=fetch)
                return jobs, 'DEGRADED' if warning else ('OK' if jobs else 'EMPTY'), warning, f'discovered {provider}:{slug}'
            except (ValueError, KeyError, TypeError, HTTPError, URLError, TimeoutError) as exc:
                errors.append(f'{provider}:{slug} {type(exc).__name__}')
        jobs = list(parse_jsonld_jobs(name, page, source['careers']))
        if jobs:
            return jobs, 'OK', '', 'public JSON-LD'
        # Some sites put JobPosting JSON-LD on the individual job page,
        # not the careers index. Read up to 16 same-host title-matching links.
        details = candidate_detail_links(page, source['careers'])
        job_items = []
        broken = 0
        for job_url in details:
            try:
                job_items.extend(parse_jsonld_jobs(name, get_text(job_url, fetch=fetch), job_url))
            except (ValueError, TypeError, HTTPError, URLError, TimeoutError):
                broken += 1
        if job_items:
            distinct = {job_key(job): job for job in job_items}
            warning = f'{broken} job detail pages could not be read' if broken else ''
            if len(details) == 16:
                warning += ('; ' if warning else '') + 'website detail-link cap reached (16)'
            return list(distinct.values()), 'DEGRADED' if warning else 'OK', warning, 'job-page JSON-LD'
        if re.search(r'no (?:current |open )?(?:job |position |role )?(?:openings|positions|vacancies)|no jobs available', page, re.I):
            return [], 'EMPTY', '', 'company website'
        return [], 'NEEDS_ADAPTER', ('No readable structured listings or ATS board. ' + ' '.join(errors)).strip(), 'website'
    except (ValueError, KeyError, TypeError, HTTPError, URLError, TimeoutError, OSError) as exc:
        return [], 'ERROR', f'{type(exc).__name__}: {str(exc)[:180]}', kind


def job_key(job):
    # Never collapse distinct requisitions simply because title+location are equal.
    return f'{job.company.lower()}::{job.ident}'


def markdown_escape(s):
    return str(s).replace('|', '\\|').replace('[', '\\[').replace(']', '\\]').replace('\n', ' ').strip()


def safe_url(url):
    return url if isinstance(url, str) and url.startswith(('https://', 'http://')) else ''


def make_email(jobs, now, total, readable, first_run):
    local = now.astimezone(TZ)
    rows = [f'# Remote Anywhere Radar — {local:%d %b %Y, %I:%M %p} IST', '',
            '| Company | Role | Posted within 24 hours | Work location |',
            '|---|---|---|---|']
    for job, region, published in jobs:
        hours = (now - published).total_seconds() / 3600
        title = markdown_escape(job.title)
        href = safe_url(job.url)
        role = f'[{title}]({href})' if href else title
        rows.append(f'| {markdown_escape(job.company)} | {role} | Yes — {max(0, hours):.1f}h ago | Remote — {region} |')
    if not jobs:
        rows.append('| — | No new matching jobs | — | — |')
    rows.extend(['', f'{len(jobs)} new matches • {readable} of {total} company sources returned readable postings or a confirmed empty board.'])
    if first_run:
        rows.append('First scan: baseline created; previously listed jobs are not emailed as new.')
    rows.append('The scan checks employer publication timestamps; a provider may sometimes republish an older job.')
    return '\n'.join(rows) + '\n'


def write_csv(path, header, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def atomic_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def load_state(path):
    if not path.exists():
        return {'version': 1, 'seen': {}}, True
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('seen'), dict):
        raise ValueError('Existing state is invalid. Refusing to erase job history.')
    return data, False


def run(root=ROOT, *, fetch=None, now=None, workers=6):
    now = now or datetime.now(timezone.utc)
    config = json.loads((root / 'companies.json').read_text(encoding='utf-8'))
    sources = config.get('companies')
    if not isinstance(sources, list) or len(sources) != 51:
        raise ValueError('Expected exactly 51 company entries; refusing an incomplete roster')
    if len({x['name'].lower() for x in sources}) != 51:
        raise ValueError('Duplicate companies in roster')
    out = root / 'output'
    out.mkdir(parents=True, exist_ok=True)
    state, first_run = load_state(root / 'state' / 'seen.json')
    prev_seen = state['seen']
    results = [None] * len(sources)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch_company, src, fetch=fetch): i for i, src in enumerate(sources)}
        for fut in as_completed(futs):
            idx = futs[fut]
            try:
                results[idx] = fut.result()
            except Exception as exc:
                results[idx] = ([], 'ERROR',
                                f'Unexpected source error {type(exc).__name__}: {str(exc)[:180]}',
                                sources[idx]['type'])
    fetched, recent_matches, undated = 0, [], 0
    healthy = 0
    seen_next = dict(prev_seen)
    health_rows = []
    for src, result in zip(sources, results):
        jobs, status, error, adapter = result
        fetched += len(jobs)
        if status in ('OK', 'EMPTY'):
            healthy += 1
        qualifying = 0
        for job in jobs:
            if not job.ident or not job.title or not safe_url(job.url):
                continue
            key = job_key(job)
            seen_next[key] = now.isoformat()
            if not role_matches(job.title):
                continue
            region = remote_region(job)
            if not region:
                continue
            pub = parse_timestamp(job.timestamp)
            if pub is None:
                undated += 1
                continue
            if not recent(pub, now, config.get('window_hours', 24)):
                continue
            qualifying += 1
            recent_matches.append((job, region, pub, key))
        health_rows.append([src['name'], status, adapter, len(jobs), qualifying, error, src['careers']])
    # Prior seen IDs are never accidentally lost during a site outage.
    new = [(job, region, pub) for job, region, pub, key in recent_matches if not first_run and key not in prev_seen]
    new.sort(key=lambda x: x[2], reverse=True)
    recent_matches.sort(key=lambda x: x[2], reverse=True)
    write_csv(out / 'source_health.csv', ['Company', 'Status', 'Adapter', 'Jobs found', '24h matching jobs', 'Error / limitation', 'Careers'], health_rows)
    # Four columns in every job report. Application URL is included inside Role.
    def job_row(j, region, pub):
        hrs = max(0, (now - pub).total_seconds() / 3600)
        return [j.company, f'{j.title} — {j.url}', f'Yes — {hrs:.1f}h ago', f'Remote — {region}']
    write_csv(out / 'current_24h.csv', ['Company', 'Role', 'Posted within 24 hours', 'Work location'],
              [job_row(j, region, pub) for j, region, pub, _ in recent_matches])
    write_csv(out / 'new_jobs.csv', ['Company', 'Role', 'Posted within 24 hours', 'Work location'],
              [job_row(j, region, pub) for j, region, pub in new])
    summary = {'companies_configured': len(sources), 'sources_readable': healthy,
               'sources_needing_adapter_or_failed': len(sources) - healthy,
               'jobs_fetched': fetched, 'date_unverified_role_location_matches': undated,
               'matching_postings_within_24h': len(recent_matches), 'new_matches': len(new),
               'first_run_baseline': first_run, 'scanned_utc': now.isoformat(),
               'statuses': {r[0]: r[1] for r in health_rows}}
    atomic_json(out / 'summary.json', summary)
    (out / 'email.md').write_text(make_email(new, now, len(sources), healthy, first_run), encoding='utf-8')
    atomic_json(out / 'next_state.json', {'version': 1, 'seen': seen_next})
    # Tests call this function without GITHUB_STEP_SUMMARY; no fixture writes to live summary.
    return summary


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
