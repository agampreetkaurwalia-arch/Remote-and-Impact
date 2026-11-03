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
    r"(?:technical\s+)?product(?:\s+(?:growth|strategy|operations))?\s+manager|"
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
    ('lever', re.compile(r'https?://jobs(?:\.eu)?\.lever\.co/([a-zA-Z0-9._-]+)', re.I)),
    ('greenhouse', re.compile(r'https?://(?:job-boards|boards)\.greenhouse\.io/([a-zA-Z0-9._-]+)', re.I)),
    ('workable', re.compile(r'https?://apply\.workable\.com/([a-zA-Z0-9._-]+)', re.I)),
    ('smartrecruiters', re.compile(r'https?://careers\.smartrecruiters\.com/([a-zA-Z0-9._-]+)', re.I)),
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
    description: str = ""


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


# A title's explicit region can override a job board's generic "Remote" label.
# For example "Project Manager - US" must not become worldwide through a
# company's generally global remote policy.
TITLE_REGION_RESTRICTED = re.compile(
    r'(?:^|\s|[—–,(])(?:[-—–]\s*)?(?:US|USA|UK|EU|EMEA|Americas|LATAM|'
    r'North America|Europe|Canada|Australia)(?:\s+only)?\s*(?:$|[),—–])', re.I)


def remote_region(job, *, assumed_global=False, locations_are_advertising_only=False):
    """Return India/Global only on job evidence or explicitly audited company policy.

    assumed_global is an opt-in per company, never a general rule for all
    remote-first employers. Explicit role restrictions always take precedence.
    """
    loc = ' '.join(str(job.location).split())
    title = ' '.join(str(job.title).split())
    scope = GLOBAL_RX.search(loc)
    india = INDIA_RX.search(loc) or re.search(r'(?:[-–—,(]\s*)India\s*(?:$|[),–—])', title, re.I)
    workplace = str(job.workplace).strip().lower().replace('-', '')
    if workplace in ('hybrid', 'onsite', 'on site'):
        return ''
    remote = (REMOTE_RX.search(loc) or workplace in ('remote', 'telecommute')
              or REMOTE_RX.search(title)
              or re.search(r'\b(?:anywhere|world\s*-?\s*wide)\b', loc, re.I))
    if not remote:
        return ''
    if TITLE_REGION_RESTRICTED.search(title) or re.search(
        r'\b(?:remote|work from anywhere)\s+(?:in|within|across)\s+(?:the\s+)?(?:US|USA|United States|UK|EU|Europe|EMEA|Canada|Australia|Americas)\b',
        title, re.I):
        return ''
    if re.search(r'\b(?:US|USA|United States|UK|United Kingdom|Canada|EU|Europe|EMEA|Australia|Americas)\s+only\b|\bonly\s+(?:in|within|from)\s+(?:the\s+)?(?:US|USA|United States|UK|United Kingdom|Canada|EU|Europe|EMEA|Australia|Americas)\b', loc, re.I):
        return ''
    if locations_are_advertising_only:
        # This is a company-specific documented exception. Explicit role
        # restrictions in the TITLE still win (checked above).
        return 'Global / Anywhere'
    if india:
        return 'India'
    if RESTRICTED_RX.search(loc) or re.search(
        r'\banywhere\s+(?:in|within|across)\s+(?:the\s+)?(?:US|USA|United States|UK|EU|Europe|Canada|Australia|Americas|EMEA)\b',
        loc, re.I):
        return ''
    # A company's broad global policy does not override an advertised
    # role location such as 'Remote EMEA' or 'Remote - United States'.
    # India is handled above and always remains explicitly eligible.
    if re.search(
        r'\b(?:US|USA|United States|UK|United Kingdom|EU|EMEA|LATAM|APAC|'
        r'Europe|Americas|North America|Canada|Australia|Germany|France|'
        r'Spain|Portugal|Poland|Netherlands|Singapore|Japan)\b', loc, re.I
    ):
        return ''
    if scope or assumed_global:
        return 'Global / Anywhere'
    # Employer job descriptions occasionally clarify the geography while the
    # ATS summary has only 'Remote'. Only explicit worldwide/India language
    # counts; general company marketing blurbs are not sufficient.
    desc = html.unescape(str(job.description or ''))
    if re.search(r'\b(?:this role|this position|we hire|applicants|candidates)\b.{0,90}\bIndia\b', desc, re.I):
        if not re.search(r'\b(?:except|excluding|not available in|cannot hire in)\s+India\b', desc, re.I):
            return 'India'
    if re.search(r'\b(?:work from anywhere(?: in the world)?|open to candidates worldwide|\n\s*location\s*:\s*(?:global|worldwide|anywhere)|anywhere in the world)\b', desc, re.I):
        if not re.search(r'\b(?:must (?:be|live|reside) (?:based )?in|only candidates (?:in|from)|open (?:only|exclusively) to)\s+(?:the\s+)?(?:United States|US|UK|Canada|Europe|EU|EMEA|Americas|Australia)\b', desc, re.I):
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
        places = [str(item.get('location') or '')]
        for other in item.get('secondaryLocations') or []:
            if isinstance(other, dict):
                places.append(str(other.get('location') or other.get('name') or ''))
            elif isinstance(other, str):
                places.append(other)
        loc = '; '.join(dict.fromkeys(x.strip() for x in places if x.strip()))
        if item.get('isRemote') and not item.get('workplaceType'):
            workplace = 'Remote'
        else:
            workplace = str(item.get('workplaceType') or '')
        yield Job(company, str(item.get('id') or ''), str(item.get('title') or ''),
                  loc, workplace, str(item.get('publishedAt') or ''), 'last_published',
                  str(item.get('jobUrl') or item.get('applyUrl') or ''),
                  clean_description(item.get('descriptionPlain') or ''))

def parse_lever(company, payload):
    if not isinstance(payload, list):
        raise ValueError('Lever payload not a list')
    for item in payload:
        if not isinstance(item, dict):
            continue
        cat = item.get('categories') or {}
        if not isinstance(cat, dict):
            cat = {}
        places = [str(cat.get('location') or '')]
        places.extend(str(x) for x in (cat.get('allLocations') or []) if x)
        loc = '; '.join(dict.fromkeys(x.strip() for x in places if x.strip()))
        yield Job(company, str(item.get('id') or ''), str(item.get('text') or ''),
                  loc, str(item.get('workplaceType') or ''),
                  str(item.get('createdAt') or ''), 'created_at',
                  str(item.get('hostedUrl') or item.get('applyUrl') or ''),
                  clean_description(item.get('descriptionPlain') or ''))

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


def parse_pinpoint(company, payload):
    """Pinpoint's public postings.json has job data but generally no publish
    timestamp. Do not substitute deadline or date of fetching for publication.
    """
    jobs = payload.get('data')
    if not isinstance(jobs, list):
        raise ValueError('Pinpoint postings.json has no data list')
    for item in jobs:
        if not isinstance(item, dict):
            continue
        loc = item.get('location') or {}
        if isinstance(loc, dict):
            loc = loc.get('name') or ''
        workplace = str(item.get('workplace_type') or item.get('workplace_type_text') or '')
        published = str(item.get('published_at') or '')
        yield Job(company, str(item.get('id') or ''), str(item.get('title') or ''),
                  str(loc), workplace, published,
                  'pinpoint_published_at' if published else 'pinpoint_no_publish_time',
                  str(item.get('url') or ''), clean_description(item.get('description') or ''))


def parse_smartrecruiters(company, payload):
    """Read the public SmartRecruiters company-postings listing.

    Its releasedDate is a listing release timestamp. Missing or date-only
    values remain unverified under the strict 24-hour rule.
    """
    jobs = payload.get('content')
    if not isinstance(jobs, list):
        raise ValueError('SmartRecruiters payload lacks content list')
    for item in jobs:
        if not isinstance(item, dict):
            continue
        loc_obj = item.get('location') or {}
        if not isinstance(loc_obj, dict):
            loc_obj = {}
        city = str(loc_obj.get('city') or '').strip()
        country = str(loc_obj.get('country') or loc_obj.get('countryCode') or '').strip()
        country = 'India' if country.lower() in ('in', 'ind') else country
        loc = ', '.join(p for p in (city, country) if p)
        if bool(loc_obj.get('remote')):
            loc = ('Remote ' + loc).strip()
        ident = str(item.get('id') or '')
        url = str(item.get('applyUrl') or item.get('jobUrl') or '')
        if not url and ident:
            url = 'https://jobs.smartrecruiters.com/' + quote(company.replace(' ', ''), safe='') + '/' + quote(ident, safe='')
        yield Job(company, ident, str(item.get('name') or item.get('title') or ''),
                  loc, 'Remote' if loc_obj.get('remote') else '',
                  str(item.get('releasedDate') or item.get('releaseDate') or ''),
                  'smartrecruiters_releasedDate', url)


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


class EmptyHeadingParser(HTMLParser):
    """Treat visible empty-state headings as authoritative, not embedded
    hidden templates, marketing copy, or unrelated mentions in scripts.
    """
    def __init__(self):
        super().__init__()
        self.heading = None
        self.words = []
        self.headings = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() in ('h1','h2','h3','h4'):
            self.heading = tag.lower(); self.words=[]
    def handle_data(self, data):
        if self.heading:
            self.words.append(data)
    def handle_endtag(self, tag):
        if self.heading and tag.lower() == self.heading:
            self.headings.append(' '.join(' '.join(self.words).split()).lower())
            self.heading=None
            self.words=[]


def explicit_empty_page(page):
    parser = EmptyHeadingParser()
    parser.feed(page)
    rx = re.compile(r'^(?:there are )?no (?:current |open )?(?:jobs|openings|roles|positions|vacancies)(?: available| right now| at this time)?[.!]?$')
    return any(rx.fullmatch(x) for x in parser.headings)


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
            loc = ' / '.join('India' if a.upper() in ('IN', 'IND') else a for a in allowed if a)
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
            slug = m.group(1).strip('.')
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
    if kind == 'smartrecruiters':
        return f'https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100'
    if kind == 'pinpoint':
        return f'https://{s}.pinpointhq.com/postings.json'
    raise ValueError(f'Unknown ATS: {kind}')

PARSERS = {'greenhouse': parse_greenhouse, 'ashby': parse_ashby,
           'lever': parse_lever, 'workable': parse_workable,
           'smartrecruiters': parse_smartrecruiters,
           'pinpoint': parse_pinpoint}


def clean_description(raw):
    if not raw:
        return ''
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', str(raw))).split())


def enrich_greenhouse(company, slug, jobs, fetch=None, assumed_global=False):
    """Read details for plausible titles with generic remote geography.

    The summary feed can be missing job text. This bounded fetch supplies
    precise remote wording and a published timestamp when available, without
    substituting the later `updated_at` timestamp.
    """
    selected = [j for j in jobs if role_matches(j.title) and j.ident and
                (not j.timestamp or (
                    'remote' in (j.location or '').lower() and
                    not remote_region(j, assumed_global=assumed_global)))]
    selected.sort(key=lambda j: (not bool(j.timestamp), parse_timestamp(j.timestamp) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    selected, remainder = selected[:12], max(0, len(selected)-12)
    replacements = {}
    failed = 0
    for j in selected:
        try:
            detail = json.loads(get_text(
                f'https://boards-api.greenhouse.io/v1/boards/{quote(slug, safe=".-_")}/jobs/{quote(j.ident, safe="")}',
                fetch=fetch))
            replacements[j.ident] = Job(j.company, j.ident, j.title, j.location,
                                       j.workplace, str(detail.get('first_published') or j.timestamp),
                                       'first_published', j.url,
                                       clean_description(detail.get('content') or ''))
        except (ValueError, TypeError, KeyError, HTTPError, URLError, TimeoutError):
            failed += 1
    updated = [replacements.get(j.ident, j) for j in jobs]
    warnings = []
    if remainder:
        warnings.append(f'{remainder} candidate detail requests skipped (12 per-board cap)')
    if failed:
        warnings.append(f'{failed} job detail requests failed')
    return updated, '; '.join(warnings)


def valid_job(job):
    return bool(job.ident and job.title.strip() and safe_url(job.url))


def fetch_ats(name, kind, slug, *, fetch=None, assumed_global=False):
    url = endpoint(kind, slug)
    raw = get_text(url, fetch=fetch)
    payload = json.loads(raw)
    jobs = list(PARSERS[kind](name, payload))
    if kind == 'smartrecruiters':
        total = int(payload.get('totalFound') or len(jobs))
        offset = 100
        # Page the public listing instead of silently discarding jobs 101+.
        while len(jobs) < total and offset < min(total, 500):
            extra = json.loads(get_text(url + '&offset=' + str(offset), fetch=fetch))
            page = list(PARSERS[kind](name, extra))
            if not page:
                break
            jobs.extend(page)
            offset += 100
    bad = sum(not valid_job(j) for j in jobs)
    jobs = [j for j in jobs if valid_job(j)]
    if bad and not jobs:
        raise ValueError(f'All {bad} returned jobs missing identifier, title or application URL')
    warn = (f'{bad} incomplete job records skipped' if bad else '')
    if kind == 'pinpoint' and jobs:
        enriched, skipped = [], 0
        for j in jobs:
            if role_matches(j.title) and not j.timestamp and j.url.startswith('https://'):
                try:
                    page = get_text(j.url, fetch=fetch)
                    details = list(parse_jsonld_jobs(name, page, j.url))
                    if details and details[0].timestamp:
                        j = Job(j.company,j.ident,j.title,j.location,j.workplace,
                                details[0].timestamp,'jsonld_datePosted',j.url,j.description)
                except (HTTPError, URLError, ValueError, TypeError, TimeoutError):
                    skipped += 1
            enriched.append(j)
        jobs = enriched
        if skipped: warn = (warn + '; ' if warn else '') + f'{skipped} Pinpoint job pages failed'
    if kind == 'greenhouse' and jobs:
        jobs, enrich_warn = enrich_greenhouse(name, slug, jobs, fetch=fetch,
                                            assumed_global=assumed_global)
        if enrich_warn:
            warn = (warn + '; ' if warn else '') + enrich_warn
    return jobs, ('DEGRADED' if warn else ('OK' if jobs else 'EMPTY')), warn


def fetch_company(source, *, fetch=None):
    name, kind = source['name'], source['type']
    errors = []
    if kind in PARSERS:
        try:
            jobs, status, warning = fetch_ats(name, kind, source['slug'], fetch=fetch,
                                             assumed_global=source.get('global_remote_default', False))
            if jobs:
                return jobs, status, warning, kind
            # A genuinely empty API is valid evidence of an empty board.
            # The diagnostic makes it distinct from an unreachable source.
            return [], 'EMPTY', 'ATS listing returned zero published jobs', kind
        except (ValueError, KeyError, TypeError, HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f'{kind}: {type(exc).__name__}: {str(exc)[:130]}')
    if kind not in PARSERS and kind != 'website':
        return [], 'ERROR', 'Unsupported source type ' + kind, kind
    try:
        page = get_text(source['careers'], fetch=fetch)
        for provider, slug in discover_ats(page):
            if kind == provider and slug.lower() == str(source.get('slug', '')).lower():
                continue
            try:
                jobs, status, warning = fetch_ats(name, provider, slug, fetch=fetch,
                                                  assumed_global=source.get('global_remote_default', False))
                if jobs:
                    return jobs, status, warning, 'discovered ' + provider + ':' + slug
            except (ValueError, KeyError, TypeError, HTTPError, URLError, TimeoutError, OSError) as exc:
                errors.append(f'{provider}:{slug} {type(exc).__name__}')
        jobs = [j for j in parse_jsonld_jobs(name, page, source['careers']) if valid_job(j)]
        if jobs:
            return jobs, 'OK', '', 'public JSON-LD'
        details = candidate_detail_links(page, source['careers'], max_links=12)
        job_items, broken = [], 0
        for job_url in details:
            try:
                job_items.extend(j for j in parse_jsonld_jobs(name, get_text(job_url, fetch=fetch), job_url) if valid_job(j))
            except (ValueError, TypeError, HTTPError, URLError, TimeoutError, OSError):
                broken += 1
        if job_items:
            unique = {job_key(job): job for job in job_items}
            warning = f'{broken} unreadable detail pages' if broken else ''
            if len(details) == 12:
                warning += ('; ' if warning else '') + 'detail-link cap 12 reached'
            return list(unique.values()), 'DEGRADED' if warning else 'OK', warning, 'job-page JSON-LD'
        if explicit_empty_page(page):
            return [], 'EMPTY', 'Website explicitly says no jobs in a heading', 'website'
        if details:
            return [], 'NEEDS_ADAPTER', f'{len(details)} job detail links visible, but no usable postings/dates. ' + ' '.join(errors), 'website'
        return [], 'NEEDS_ADAPTER', 'No readable job listings. ' + ' '.join(errors), 'website'
    except (ValueError, KeyError, TypeError, HTTPError, URLError, TimeoutError, OSError) as exc:
        details = '; '.join(errors)
        return [], 'ERROR', f'{details}; careers: {type(exc).__name__}: {str(exc)[:130]}'.strip('; '), kind

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
        rows.append('First scan: verified postings from the last 24 hours are included. Older jobs are not emailed.')
    if readable < total:
        rows.append(f'Coverage warning: {total-readable} employers could not be verified in this scan; zero matches does not mean zero available jobs.')
    rows.append('The scanner uses employer publication timestamps. A last-published timestamp may reflect a republication.')
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
    # Old `seen.json` was polluted with every fetched posting, even jobs that
    # never qualified or generated an email. Do not use it to suppress alerts.
    # Keep that file untouched for historical analysis.
    if not path.exists():
        return {'version': 2, 'alerted': {}}, True
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 2 or not isinstance(data.get('alerted'), dict):
        raise ValueError('v2 alert history invalid; refusing to reset or overwrite it.')
    return data, False

def run(root=ROOT, *, fetch=None, now=None, workers=6):
    """Perform a real scan; no test data is written outside root.

    Important: only successfully alertable IDs become alerted. A missing
    publication date or location can never poison future alert history.
    """
    now = now or datetime.now(timezone.utc)
    config = json.loads((root / 'companies.json').read_text(encoding='utf-8'))
    sources = config.get('companies')
    if not isinstance(sources, list) or len(sources) != 51:
        raise ValueError('Expected 51 companies. Refusing to silently shrink coverage.')
    if len({x['name'].lower() for x in sources}) != 51:
        raise ValueError('Company names must be unique.')
    for x in sources:
        if x.get('type') not in PARSERS and x.get('type') != 'website':
            raise ValueError('Unknown source adapter: ' + str(x))
        if not str(x.get('careers','')).startswith('https://'):
            raise ValueError('Invalid careers URL: ' + str(x))
    out = root / 'output'
    out.mkdir(parents=True, exist_ok=True)
    state, first_run = load_state(root / 'state' / 'alerts_v2.json')
    prev_alerted = state['alerted']
    next_alerted = dict(prev_alerted)
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
    role_hits_all = location_hits_all = timestamp_hits_all = 0
    readable = 0
    health, audit, not_readable, raw_audit = [], [], [], []
    for src, result in zip(sources, results):
        jobs, status, error, adapter = result
        role_hits = location_hits = timestamp_hits = 0
        fetched += len(jobs)
        if status in ('OK', 'EMPTY', 'DEGRADED'):
            readable += 1
        else:
            not_readable.append([src['name'], status, error, src['careers']])
        matched = 0
        for j in jobs:
            raw_audit.append([src['name'], j.ident, j.title, j.location, j.workplace,
                              j.timestamp, j.date_basis, j.url, adapter])
            if not valid_job(j):
                continue
            if not role_matches(j.title):
                continue
            role_hits += 1
            region = remote_region(j, assumed_global=src.get('global_remote_default', False),
                                   locations_are_advertising_only=src.get('locations_are_advertising_only', False))
            pub = parse_timestamp(j.timestamp)
            age = round((now - pub).total_seconds() / 3600, 2) if pub else ''
            if not region:
                outcome = 'Excluded: remote geography not proven India or worldwide'
            elif pub is None:
                outcome = 'Excluded: no reliable publication timestamp'
            elif not recent(pub, now, config.get('window_hours', 24)):
                outcome = 'Excluded: older than 24 hours or future timestamp'
            else:
                outcome = 'Qualified within 24h'
            audit.append([j.company, j.title, j.location, j.workplace,
                          region or 'Not proven', j.timestamp, j.date_basis,
                          age, outcome, j.url])
            if not region:
                continue
            location_hits += 1
            if pub is None:
                undated += 1
                continue
            timestamp_hits += 1
            if not recent(pub, now, config.get('window_hours', 24)):
                continue
            matched += 1
            recent_matches.append((j, region, pub, job_key(j)))
        role_hits_all += role_hits
        location_hits_all += location_hits
        timestamp_hits_all += timestamp_hits
        health.append([src['name'], status, adapter, len(jobs), matched,
                       error, src['careers'], role_hits, location_hits, timestamp_hits])
    # Dedupe across multiple listings or fallback paths by the ATS requisition ID.
    recent_by_key = {}
    for j, region, pub, key in recent_matches:
        if key not in recent_by_key or pub > recent_by_key[key][2]:
            recent_by_key[key] = (j, region, pub, key)
    recent_matches = sorted(recent_by_key.values(), key=lambda v: v[2], reverse=True)
    new = [(j, region, pub) for j, region, pub, key in recent_matches if key not in prev_alerted]
    for j, region, pub in new:
        next_alerted[job_key(j)] = {'published': pub.isoformat(), 'notified_scan': now.isoformat()}
    # Fail closed on a total outage. Do not email an ungrounded empty result or advance state.
    if not readable:
        raise RuntimeError('All 51 sources failed; refusing to send an empty digest or update alert history')
    write_csv(out / 'source_health.csv',
              ['Company','Status','Adapter','Jobs found','24h matching jobs','Error / limitation',
               'Careers','Matching role titles','Matching India/global location',
               'Matching with usable timestamp'], health)
    write_csv(out / 'role_audit.csv',
              ['Company','Role','Raw ATS location','Workplace type','India/Global classification',
               'Raw published date','Date source','Hours since published','Audit result','Application link'], audit)
    write_csv(out / 'unreadable_sources.csv',
              ['Company','Status','Error / limitation','Careers'], not_readable)
    write_csv(out / 'raw_jobs_audit.csv',
              ['Company','Job ID','Role','Raw location','Remote type','Published raw',
               'Date field','Job link','Adapter'],raw_audit)
    def report_row(j, region, pub):
        hrs = max(0, (now - pub).total_seconds() / 3600)
        return [j.company, j.title + ' — ' + j.url, f'Yes — {hrs:.1f}h ago', 'Remote — ' + region]
    write_csv(out / 'current_24h.csv',
              ['Company','Role','Posted within 24 hours','Work location'],
              [report_row(j, reg, dt) for j, reg, dt, _ in recent_matches])
    write_csv(out / 'new_jobs.csv',
              ['Company','Role','Posted within 24 hours','Work location'],
              [report_row(j, reg, dt) for j, reg, dt in new])
    previous_report = out / 'previous_summary.json' if (out / 'previous_summary.json').exists() else out / 'summary.json'
    anomalies = []
    if previous_report.exists():
        try:
            old = json.loads(previous_report.read_text(encoding='utf-8'))
            if old.get('jobs_fetched',0) >= 100 and fetched < old['jobs_fetched'] * .5:
                anomalies.append('Job volume dropped by more than half since previous scan')
            if old.get('sources_readable',0) >= 10 and readable <= old['sources_readable'] - 8:
                anomalies.append('Eight or more previously readable company sources were lost')
        except (ValueError, OSError, TypeError):
            anomalies.append('Previous report unreadable; could not compare scan health')
    summary = {
        'scan_anomalies':anomalies,
        'companies_configured':len(sources), 'sources_readable':readable,
        'sources_needing_adapter_or_failed':len(sources)-readable,
        'sources_returning_jobs':sum(bool(r[0]) for r in results),
        'sources_empty':sum(r[1]=='EMPTY' for r in results),
        'sources_degraded':sum(r[1]=='DEGRADED' for r in results),
        'jobs_fetched': fetched,
        'matching_role_titles':role_hits_all,
        'matching_india_global_locations':location_hits_all,
        'matching_with_usable_publication_time':timestamp_hits_all,
        'date_unverified_role_location_matches':undated,
        'matching_postings_within_24h':len(recent_matches),
        'new_matches':len(new),
        'first_run':first_run,
        'first_run_baseline':False,  # verified new posts now alert even on first run
        'scanned_utc':now.isoformat(),
        'statuses':{row[0]:row[1] for row in health}
    }
    atomic_json(out / 'summary.json',summary)
    digest = make_email(new, now, len(sources), readable, first_run)
    if anomalies:
        digest += 'Scan-health warning: ' + '; '.join(anomalies) + '\n'
    (out / 'email.md').write_text(digest,encoding='utf-8')
    atomic_json(out / 'next_alerts_v2.json', {'version':2,'alerted':next_alerted})
    # Legacy state/seen.json is deliberately left untouched.
    return summary


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
