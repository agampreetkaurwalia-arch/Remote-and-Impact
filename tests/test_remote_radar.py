import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote_radar as r
import notify as n

NOW = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)
TS = (NOW - timedelta(hours=2)).isoformat()


def test_job(location='Remote, Global', title='Product Manager', date=TS,
             workplace='Remote', company='Example', ident='a'):
    return r.Job(company, ident, title, location, workplace, date, 'first_published',
                 f'https://example.org/jobs/{ident}')


class CoreRules(unittest.TestCase):
    def test_exact_roster(self):
        c = json.loads((r.ROOT / 'companies.json').read_text())
        self.assertEqual(51, len(c['companies']))
        self.assertEqual(51, len({x['name'].lower() for x in c['companies']}))
        for name in ['Fingerprint', 'Strike', 'Brave', 'Alpaca']:
            self.assertIn(name, {x['name'] for x in c['companies']})

    def test_role_families(self):
        for title in ['Chief of Staff', "Founder's Associate", 'Product Manager',
                      'Strategy & Operations', 'Strategy Consultant', 'Consulting Manager',
                      'Program Manager', 'Programme Manager', 'Project Manager',
                      'Technical Program Manager']:
            with self.subTest(title=title):
                self.assertTrue(r.role_matches(title))

    def test_unrelated_roles(self):
        for title in ['Software Engineer', 'Senior Account Executive', 'Product Designer',
                      'Business Development Manager', 'Office Administrator', 'Growth Hacker']:
            with self.subTest(title=title):
                self.assertFalse(r.role_matches(title))

    def test_global_remote(self):
        for loc in ['Remote, Global', 'Remote - Anywhere', 'Worldwide Remote',
                    'Global Anywhere', 'Work from anywhere']:
            with self.subTest(loc=loc):
                self.assertEqual('Global / Anywhere', r.remote_region(test_job(location=loc)))

    def test_india_remote(self):
        for loc in ['Remote - India', 'India, Remote', 'Remote - India and Canada']:
            with self.subTest(loc=loc):
                self.assertEqual('India', r.remote_region(test_job(location=loc)))

    def test_excludes_geo(self):
        for loc in ['US Remote', 'Remote - USA', 'Remote US Only', 'Remote - Europe',
                    'Remote - EMEA', 'Remote - APAC', 'Remote - North America',
                    'Anywhere in the US', 'Remote - UK only', 'Remote - Canada']:
            with self.subTest(loc=loc):
                self.assertEqual('', r.remote_region(test_job(location=loc)))

    def test_unspecified_and_onsite(self):
        self.assertEqual('', r.remote_region(test_job(location='Remote')))
        self.assertEqual('', r.remote_region(test_job(location='India', workplace='OnSite')))
        self.assertEqual('', r.remote_region(test_job(location='Remote Global', workplace='Hybrid')))
        self.assertEqual('', r.remote_region(test_job(location='Global', workplace='')))
        self.assertEqual('Global / Anywhere', r.remote_region(test_job(location='Anywhere', workplace='')))
        self.assertEqual('', r.remote_region(test_job(location='London', workplace='Remote')))

    def test_remote_type_works_with_location_global(self):
        self.assertEqual('Global / Anywhere', r.remote_region(test_job(location='Global', workplace='Remote')))

    def test_date_exact(self):
        for h in [0, 1, 12, 23.99, 24]:
            with self.subTest(hours=h):
                self.assertTrue(r.recent(NOW - timedelta(hours=h), NOW))
        self.assertFalse(r.recent(NOW - timedelta(hours=24, seconds=1), NOW))
        self.assertFalse(r.recent(NOW + timedelta(hours=1), NOW))

    def test_date_only_refused(self):
        self.assertIsNone(r.parse_timestamp('2026-11-03'))
        self.assertIsNone(r.parse_timestamp('2026-11-03T02:00:00'))
        self.assertIsNone(r.parse_timestamp('not a date'))

    def test_epoch_seconds_and_milliseconds(self):
        value = int(NOW.timestamp())
        self.assertEqual(NOW, r.parse_timestamp(value))
        self.assertEqual(NOW, r.parse_timestamp(str(value)))
        self.assertEqual(NOW, r.parse_timestamp(value * 1000))
        self.assertEqual(NOW, r.parse_timestamp(str(value * 1000)))

    def test_malformed_greenhouse_location_string(self):
        j = list(r.parse_greenhouse('G', {'jobs':[{'id':1, 'title':'Product Manager',
                        'location':'Remote Global', 'first_published':TS,
                        'absolute_url':'https://e.org/1'}]}))[0]
        self.assertEqual('Global / Anywhere', r.remote_region(j))

    def test_strategist_role(self):
        self.assertTrue(r.role_matches('Business Strategist'))

    def test_greenhouse_shape(self):
        j = list(r.parse_greenhouse('G', {'jobs':[{'id': 42, 'title':'Product Manager',
               'location': {'name': 'Remote, India'}, 'first_published': TS,
               'absolute_url':'https://example.org/42'}]}))[0]
        self.assertEqual('India', r.remote_region(j))
        self.assertEqual(42, int(j.ident))

    def test_ashby_shape(self):
        j = list(r.parse_ashby('A', {'jobs':[{'id':'a','title':'Strategy Manager',
                'location':'Global','workplaceType':'Remote','publishedAt':TS,
                'jobUrl':'https://a.com/1'}]}))[0]
        self.assertEqual('Global / Anywhere', r.remote_region(j))
        self.assertEqual('last_published', j.date_basis)

    def test_ashby_unlisted_excluded(self):
        self.assertEqual([], list(r.parse_ashby('A', {'jobs':[{'id':'a','isListed':False}]})))

    def test_lever_shape(self):
        j = list(r.parse_lever('L', [{'id':'a','text':'Chief of Staff',
               'categories':{'location':'Remote India'}, 'workplaceType':'remote',
               'createdAt':int(NOW.timestamp() * 1000), 'hostedUrl':'https://lever.example/1'}]))[0]
        self.assertEqual('India', r.remote_region(j))
        self.assertEqual(NOW, r.parse_timestamp(j.timestamp))

    def test_workable_shape(self):
        jobs = list(r.parse_workable('W', {'jobs': [{'shortcode': 'a', 'title': 'Project Manager',
                'location': {'location_str': 'Global'}, 'telecommuting': True,
                'published_at': TS, 'url':'https://w.test/a'}]}))
        self.assertEqual('Global / Anywhere', r.remote_region(jobs[0]))

    def test_jsonld(self):
        page = '<script type="application/ld+json">' + json.dumps({
            '@context': 'https://schema.org', '@type':'JobPosting',
            'title': 'Program Manager', 'datePosted': TS,
            'jobLocationType':'TELECOMMUTE',
            'applicantLocationRequirements': {'@type':'Country','name':'India'},
            'url': 'https://jobs.example/job1'}) + '</script>'
        jobs = list(r.parse_jsonld_jobs('J', page, 'https://jobs.example'))
        self.assertEqual(1, len(jobs))
        self.assertEqual('India', r.remote_region(jobs[0]))

    def test_career_job_links_discover_role_pages(self):
        page = '<a href="/jobs/strategy-1">Strategy Manager</a>' + \
               '<a href="/about">About us</a>'
        self.assertEqual(['https://example.org/jobs/strategy-1'],
                         r.candidate_detail_links(page, 'https://example.org/careers'))

    def test_career_link_blocks_other_hosts(self):
        page = '<a href="https://attacker.example/jobs/a">Product Manager</a>'
        self.assertEqual([], r.candidate_detail_links(page, 'https://example.org/careers'))

    def test_website_job_details_jsonld(self):
        src = {'name':'X','type':'website','careers':'https://example.org/careers'}
        def fake(url):
            if url.endswith('/careers'):
                return '<a href="/jobs/1">Product Manager</a>'
            return '<script type="application/ld+json">' + json.dumps({
                '@type':'JobPosting', 'title':'Product Manager',
                'jobLocationType':'TELECOMMUTE',
                'applicantLocationRequirements':{'name':'India'},
                'datePosted':TS, 'url':url}) + '</script>'
        jobs, status, _, _ = r.fetch_company(src, fetch=fake)
        self.assertEqual('OK',status)
        self.assertEqual(1,len(jobs))
        self.assertEqual('India',r.remote_region(jobs[0]))

    def test_ats_discovery(self):
        html = '<iframe src="https://jobs.ashbyhq.com/chilipiper"></iframe>'
        self.assertEqual([('ashby','chilipiper')], r.discover_ats(html))

    def test_no_false_same_title_dedup(self):
        a = test_job(ident='123')
        b = test_job(ident='456')
        self.assertNotEqual(r.job_key(a), r.job_key(b))

    def test_email_four_columns_only(self):
        text = r.make_email([(test_job(), 'Global / Anywhere', NOW-timedelta(hours=2))], NOW, 51, 20, False)
        self.assertIn('| Company | Role | Posted within 24 hours | Work location |', text)
        self.assertIn('Yes — 2.0h ago', text)
        self.assertIn('](https://example.org/jobs/a)', text)

    def test_explicit_date_not_updated_at(self):
        jobs = list(r.parse_greenhouse('G', {'jobs': [{'id':1,'title':'Strategy Manager',
           'location': {'name':'Remote Global'}, 'updated_at': TS,
           'absolute_url':'https://e.org/1'}]}))
        self.assertEqual('', jobs[0].timestamp)

    def test_missing_state_fails_closed_when_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'seen.json'
            p.write_text('{}')
            with self.assertRaises(ValueError):
                r.load_state(p)
            p.write_text('{invalid')
            with self.assertRaises(json.JSONDecodeError):
                r.load_state(p)

    def test_website_without_machine_readable_jobs_not_marked_ok(self):
        src = {'name':'X','type':'website','careers':'https://example.org/careers'}
        jobs, status, msg, adapter = r.fetch_company(src,fetch=lambda url: '<h1>Careers</h1><div id="jobs"></div>')
        self.assertEqual([], jobs)
        self.assertEqual('NEEDS_ADAPTER', status)

    def test_website_explicitly_empty(self):
        src = {'name':'X','type':'website','careers':'https://example.org/careers'}
        jobs, status, _, _ = r.fetch_company(src,fetch=lambda url: '<h1>No open positions</h1>')
        self.assertEqual([], jobs)
        self.assertEqual('EMPTY', status)

    def test_greenhouse_detail_enriches_timestamp(self):
        def fake(url):
            if url.endswith('/jobs/1'):
                return json.dumps({'first_published': TS})
            return json.dumps({'jobs': [{'id':1,'title':'Product Manager',
               'location':{'name':'Remote Global'},'absolute_url':'https://e.org/1'}]})
        src = {'name':'G','type':'greenhouse','slug':'g','careers':'https://e.org'}
        jobs, status, _, _ = r.fetch_company(src,fetch=fake)
        self.assertEqual('OK', status)
        self.assertEqual(TS, jobs[0].timestamp)


def make_fetch(dynamic=False):
    def fake(url):
        if 'boards-api.greenhouse.io' in url:
            if url.rstrip('/').split('/')[-1].isdigit():
                return json.dumps({'first_published':TS})
            jobs = [{'id':1,'title':'Product Manager','location':{'name':'Remote India'},
                     'first_published':TS, 'absolute_url':'https://example.org/jobs/1'}]
            if dynamic and '/alpaca/' in url:
                jobs.append({'id':2,'title':'Chief of Staff','location':{'name':'Remote Global'},
                             'first_published':TS,'absolute_url':'https://example.org/jobs/2'})
            return json.dumps({'jobs':jobs})
        if 'posting-api/job-board' in url:
            return json.dumps({'jobs':[{'id':'a','title':'Product Manager','location':'Remote Global',
                       'workplaceType':'Remote','publishedAt':TS,'jobUrl':'https://example.org/ashby/a'}]})
        if 'api.lever.co' in url:
            return json.dumps([{'id':'l1','text':'Chief of Staff',
                     'categories':{'location':'Remote India'},'workplaceType':'remote',
                     'createdAt':int((NOW-timedelta(hours=2)).timestamp()*1000),
                     'hostedUrl':'https://example.org/lever/1'}])
        # Every fallback page contains a structured posting.
        return '<script type="application/ld+json">' + json.dumps({
             '@type':'JobPosting','title':'Program Manager', 'datePosted':TS,
             'jobLocationType':'TELECOMMUTE',
             'applicantLocationRequirements':{'name':'India'},
             'url':url.rstrip('/')+'/opening1'}) + '</script>'
    return fake


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'state').mkdir()
        (self.root/'companies.json').write_bytes((r.ROOT/'companies.json').read_bytes())
    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_includes_verified_recent_jobs_then_only_new_ids(self):
        first = r.run(self.root, fetch=make_fetch(), now=NOW, workers=8)
        self.assertEqual(51, first['companies_configured'])
        self.assertGreater(first['new_matches'], 0)
        self.assertTrue(first['first_run'])
        self.assertFalse(first['first_run_baseline'])
        self.assertGreater(first['matching_postings_within_24h'],0)
        (self.root/'state'/'alerts_v2.json').write_bytes((self.root/'output'/'next_alerts_v2.json').read_bytes())
        second = r.run(self.root, fetch=make_fetch(True), now=NOW, workers=8)
        self.assertEqual(1, second['new_matches'])
        self.assertIn('Chief of Staff', (self.root/'output'/'email.md').read_text())
        (self.root/'state'/'alerts_v2.json').write_bytes((self.root/'output'/'next_alerts_v2.json').read_bytes())
        third = r.run(self.root, fetch=make_fetch(True), now=NOW, workers=8)
        self.assertEqual(0, third['new_matches'])

    def test_unexpected_source_crash_is_isolated(self):
        with unittest.mock.patch.object(r, 'fetch_company', side_effect=RuntimeError('broken parser')):
            with self.assertRaisesRegex(RuntimeError, 'All 51 sources failed'):
                r.run(self.root, now=NOW)
        self.assertFalse((self.root/'output'/'next_alerts_v2.json').exists())

    def test_existing_saved_state_not_erased_if_sources_fail(self):
        (self.root/'state'/'seen.json').write_text(json.dumps({'version':1, 'seen':{'old::job':'2026-10-31T00:00:00Z'}}))
        with self.assertRaisesRegex(RuntimeError, 'All 51 sources failed'):
            r.run(self.root, fetch=lambda url: (_ for _ in ()).throw(ValueError('bad')),now=NOW)
        self.assertTrue((self.root/'state'/'seen.json').exists())
        self.assertFalse((self.root/'output'/'next_alerts_v2.json').exists())

    def test_early_older_posting_excluded(self):
        stale = (NOW-timedelta(hours=30)).isoformat()
        def fetch(url):
            return '<script type="application/ld+json">' + json.dumps({
                '@type':'JobPosting','title':'Product Manager','jobLocationType':'TELECOMMUTE',
                'applicantLocationRequirements':{'name':'India'}, 'datePosted':stale,
                'url':url + '/j'}) + '</script>'
        c = json.loads((self.root/'companies.json').read_text())
        # Use 51 site configurations to avoid needing synthetic ATS endpoints.
        for row in c['companies']:
            row['type']='website'
            row.pop('slug',None)
        (self.root/'companies.json').write_text(json.dumps(c))
        summary = r.run(self.root, fetch=fetch, now=NOW)
        self.assertEqual(0, summary['matching_postings_within_24h'])


class Notification(unittest.TestCase):
    def test_ist_slot(self):
        self.assertEqual('Remote Anywhere Radar | 2026-11-03 | morning',
                         n.issue_title('2026-11-03T02:41:00+00:00'))
        self.assertEqual('Remote Anywhere Radar | 2026-11-03 | evening',
                         n.issue_title('2026-11-03T14:41:00+00:00'))

    def test_no_issue_duplicated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'output').mkdir()
            (root/'output'/'summary.json').write_text(json.dumps({'scanned_utc': NOW.isoformat()}))
            (root/'output'/'email.md').write_text('body')
            title=n.issue_title(NOW.isoformat())
            calls=[]
            def fake(args, **kwargs):
                calls.append(args)
                return Mock(stdout=json.dumps([{'title':title}]), returncode=0)
            status=n.notify(root, env={'GH_TOKEN':'fake','GITHUB_REPOSITORY':'owner/repo'},invoke=fake)
            self.assertEqual('already_sent',status)
            self.assertEqual(1,len(calls))

    def test_issue_create_after_listing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'output').mkdir()
            (root/'output'/'summary.json').write_text(json.dumps({'scanned_utc':NOW.isoformat()}))
            (root/'output'/'email.md').write_text('body')
            calls=[]
            def fake(args,**kwargs):
                calls.append(args)
                return Mock(stdout='[]',returncode=0)
            self.assertEqual('sent',n.notify(root,env={'GH_TOKEN':'fake','GITHUB_REPOSITORY':'o/r'},invoke=fake))
            self.assertEqual(2,len(calls))
            self.assertIn('--body-file',calls[1])

    def test_missing_permission_fails_loud(self):
        with self.assertRaises(RuntimeError):
            n.notify(env={})


if __name__ == '__main__':
    unittest.main()
