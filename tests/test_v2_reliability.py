"""V2 regressions for real ATS failure patterns and persistent alert history."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import remote_radar as r

NOW = datetime(2026,11,3,2,30,tzinfo=timezone.utc)
ISO = (NOW-timedelta(hours=3)).isoformat()

class ReliabilityV2(unittest.TestCase):
    def test_fingerprint_is_direct_greenhouse(self):
        c = json.loads((r.ROOT/'companies.json').read_text())
        x = next(i for i in c['companies'] if i['name']=='Fingerprint')
        self.assertEqual(('greenhouse','fingerprint'), (x['type'],x['slug']))

    def test_all_51_still_present_and_existing_restrictions(self):
        c=json.loads((r.ROOT/'companies.json').read_text())
        self.assertEqual(51,len(c['companies']))
        self.assertEqual(24,c['window_hours'])
        self.assertEqual('Asia/Kolkata', c['timezone'])

    def test_ashby_secondary_india_location(self):
        job=list(r.parse_ashby('A', {'jobs':[{'id':'1','title':'Product Manager',
             'location':'Europe','secondaryLocations':[{'location':'India'}],
             'isRemote':True,'publishedAt':ISO,'jobUrl':'https://a.test/job'}]}))[0]
        self.assertEqual('India',r.remote_region(job))

    def test_lever_all_locations_when_first_country_excludes_india(self):
        job=list(r.parse_lever('A', [{'id':'1','text':'Strategy Manager',
             'categories':{'location':'Remote US', 'allLocations':['Remote US','Remote India']},
             'workplaceType':'remote','createdAt':int(NOW.timestamp()*1000),
             'hostedUrl':'https://a.test/job'}]))[0]
        self.assertEqual('India',r.remote_region(job))

    def test_title_remote_india_even_if_ats_location_india(self):
        job=r.Job('X','1','Product Manager — Remote India','India','',ISO,'created','https://a.test/job')
        self.assertEqual('India',r.remote_region(job))

    def test_global_company_does_not_override_emea_location(self):
        job=r.Job('X','1','Product Manager','Remote - Europe','',ISO,'created','https://a.test/job')
        self.assertEqual('',r.remote_region(job,assumed_global=True))

    def test_remote_usa_anywhere_is_not_global(self):
        for s in ('Remote - Anywhere in USA','Remote EMEA', 'Remote US Only'):
            job=r.Job('X','1','Product Manager',s,'',ISO,'created','https://a.test/job')
            self.assertEqual('',r.remote_region(job),s)

    def test_worldwide_evidence_in_full_ats_description(self):
        job=r.Job('X','1','Project Manager','Remote','Remote',ISO,'created','https://a.test/job',
                  'This role is fully remote and you can work from anywhere in the world.')
        self.assertEqual('Global / Anywhere',r.remote_region(job))

    def test_description_does_not_override_us_restriction(self):
        job=r.Job('X','1','Project Manager','Remote US','Remote',ISO,'created','https://a.test/job',
                  'You can work from anywhere in the world. Candidates must be based in US.')
        self.assertEqual('',r.remote_region(job))

    def test_ashby_pub_time_is_last_publish_not_first(self):
        x=next(r.parse_ashby('A',{'jobs':[{'id':'1','title':'Product Manager',
                 'location':'Global','workplaceType':'Remote','publishedAt':ISO,
                 'jobUrl':'https://a.test/job'}]}))
        self.assertEqual('last_published',x.date_basis)

    def test_date_only_not_used_as_24_hours(self):
        self.assertIsNone(r.parse_timestamp('2026-11-03'))
        self.assertFalse(r.recent(r.parse_timestamp('2026-11-03'),NOW))

    def test_partial_smartrecruiters_pagination(self):
        def fetch(url):
            offset = 100 if 'offset=100' in url else 0
            if offset==100:
                return json.dumps({'totalFound':101,'content':[{'id':'101','name':'Product Manager',
                  'location':{'remote':True,'country':'India'},'releasedDate':ISO,'jobUrl':'https://a.test/101'}]})
            return json.dumps({'totalFound':101,'content':[{'id':str(i),'name':'Product Manager',
              'location':{'remote':True,'country':'India'},'releasedDate':ISO,'jobUrl':f'https://a.test/{i}'} for i in range(1,101)]})
        jobs,status,msg=r.fetch_ats('Test','smartrecruiters','Test',fetch=fetch)
        self.assertEqual(101,len(jobs)); self.assertEqual('OK',status)

    def test_malformed_feed_is_error_not_fake_empty(self):
        source={'name':'Bad','type':'ashby','slug':'bad','careers':'https://career.test'}
        def fetch(url):
            if 'api.ashbyhq.com' in url:
                return json.dumps({'jobs':[{'title':'Product Manager','id':'1','location':'Global'}]})
            raise ValueError('bad careers')
        jobs,status,error,adapter=r.fetch_company(source,fetch=fetch)
        self.assertEqual([],jobs)
        self.assertEqual('ERROR',status)
        self.assertIn('missing',error.lower())

    def test_excluded_job_never_poison_alert_history(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'state').mkdir()
            conf=json.loads((r.ROOT/'companies.json').read_text())
            conf['companies']=[{'name':f'Company-{i}','type':'website','careers':f'https://c{i}.test/jobs'} for i in range(51)]
            (root/'companies.json').write_text(json.dumps(conf))
            def feed(url, now=NOW, missing=False):
                date='' if missing else (now-timedelta(hours=2)).isoformat()
                return '<script type="application/ld+json">'+json.dumps({'@type':'JobPosting',
                   'title':'Product Manager','jobLocationType':'TELECOMMUTE',
                   'applicantLocationRequirements':{'name':'India'},'url':url+'/j',
                   **({'datePosted':date} if date else {})})+'</script>'
            one=r.run(root,fetch=lambda u: feed(u,missing=True),now=NOW)
            self.assertEqual(0,one['new_matches'])
            (root/'state'/'alerts_v2.json').write_bytes((root/'output'/'next_alerts_v2.json').read_bytes())
            two=r.run(root,fetch=feed,now=NOW)
            self.assertEqual(51,two['new_matches'])
            (root/'state'/'alerts_v2.json').write_bytes((root/'output'/'next_alerts_v2.json').read_bytes())
            three=r.run(root,fetch=feed,now=NOW)
            self.assertEqual(0,three['new_matches'])

    def test_previous_seen_json_does_not_block_actual_alert(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'state').mkdir()
            (root/'state'/'seen.json').write_text('{"version":1,"seen":{"x::1":"2026-11-01"}}')
            c=json.loads((r.ROOT/'companies.json').read_text())
            c['companies']=[{'name':str(i),'type':'website','careers':f'https://a{i}.test'} for i in range(51)]
            (root/'companies.json').write_text(json.dumps(c))
            def fetch(url):
                return '<script type="application/ld+json">'+json.dumps({'@type':'JobPosting',
                     'title':'Product Manager','datePosted':ISO,'url':url+'/j',
                     'jobLocationType':'TELECOMMUTE','applicantLocationRequirements':{'name':'India'}})+'</script>'
            sumry=r.run(root,fetch=fetch,now=NOW)
            self.assertGreater(sumry['new_matches'],0)
            self.assertTrue((root/'state'/'seen.json').exists())
            with (root/'output/new_jobs.csv').open() as f:
                rows=list(csv.reader(f))
            self.assertEqual(4,len(rows[0]))

    def test_bad_v2_state_refuses_reset(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'alerts_v2.json'; p.write_text('{}')
            with self.assertRaises(ValueError): r.load_state(p)

    def test_unreadable_sources_report_is_written_when_partial(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'state').mkdir()
            conf=json.loads((r.ROOT/'companies.json').read_text())
            conf['companies']=[{'name':str(i),'type':'website','careers':f'https://i{i}.test/jobs'} for i in range(51)]
            (root/'companies.json').write_text(json.dumps(conf))
            def fetch(url):
                if url.startswith('https://i0.'):
                    return '<h2>No open roles</h2>'
                raise ValueError('unreadable')
            summary=r.run(root,fetch=fetch,now=NOW)
            self.assertEqual(1,summary['sources_readable'])
            with (root/'output/unreadable_sources.csv').open() as f:
                self.assertEqual(50,len(list(csv.DictReader(f))))
            self.assertIn('Coverage warning', (root/'output/email.md').read_text())

if __name__=='__main__':unittest.main()

class NotificationIdempotenceV2(unittest.TestCase):
    def test_later_real_jobs_after_empty_slot_receive_new_issue(self):
        from unittest.mock import Mock
        import notify as n
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'output').mkdir()
            (root/'output'/'summary.json').write_text(json.dumps({'scanned_utc':NOW.isoformat(),'new_matches':1}))
            (root/'output'/'email.md').write_text('New Product Manager')
            with (root/'output'/'new_jobs.csv').open('w', newline='') as f:
                writer=csv.writer(f);writer.writerow(['Company','Role','Posted within 24 hours','Work location'])
                writer.writerow(['Alpaca','Product Manager — https://x.test/123','Yes — 2h ago','Global'])
            calls=[]
            def fake(args,**kw):
                calls.append(args)
                return Mock(stdout=json.dumps([{'title':n.issue_title(NOW.isoformat())}]))
            status=n.notify(root,env={'GH_TOKEN':'fake','GITHUB_REPOSITORY':'a/b'},invoke=fake)
            self.assertEqual('sent',status)
            self.assertTrue(any('jobs-' in str(x) for x in calls))

    def test_identical_job_set_hash_independent_of_relative_age(self):
        from unittest.mock import Mock
        import notify as n
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'output').mkdir()
            (root/'output'/'summary.json').write_text(json.dumps({'scanned_utc':NOW.isoformat(),'new_matches':1}))
            (root/'output'/'email.md').write_text('New Product Manager')
            fn=root/'output'/'new_jobs.csv'
            def write(age):
                with fn.open('w',newline='') as f:
                    w=csv.writer(f);w.writerow(['Company','Role','Posted within 24 hours','Work location'])
                    w.writerow(['Alpaca','Product Manager — https://x.test/123',age,'Global'])
            calls=[]; existing=[]
            def fake(args,**kw):
                calls.append(args)
                if args[2]=='list': return Mock(stdout=json.dumps([{'title':x} for x in existing]))
                existing.append(args[args.index('--title')+1])
                return Mock(stdout='')
            write('2 hours')
            env={'GH_TOKEN':'fake','GITHUB_REPOSITORY':'a/b'}
            self.assertEqual('sent',n.notify(root,env=env,invoke=fake))
            write('3 hours')
            self.assertEqual('already_sent',n.notify(root,env=env,invoke=fake))

class PinpointAndEmptyStateTests(unittest.TestCase):
    def test_pinpoint_sources_connected(self):
        conf=json.loads((r.ROOT/'companies.json').read_text())
        by={x['name']:x for x in conf['companies']}
        for company in ('SafetyWing','YNAB'):
            self.assertEqual('pinpoint',by[company]['type'])
            self.assertIn('pinpointhq.com/postings.json',r.endpoint('pinpoint',by[company]['slug']))

    def test_pinpoint_real_schema_and_no_invented_timestamp(self):
        payload={'data':[{'id':'118475', 'title':'Product Manager',
             'url':'https://safetywing.pinpointhq.com/en/postings/id',
             'location':{'name':'Remote'},'workplace_type':'remote',
             'description':'<p>Work from anywhere globally</p>',
             'deadline_at':'2026-11-03T08:00:00Z'}]}
        job=list(r.parse_pinpoint('SafetyWing',payload))[0]
        self.assertEqual('Global / Anywhere',r.remote_region(job))
        self.assertIsNone(r.parse_timestamp(job.timestamp))
        self.assertEqual('pinpoint_no_publish_time',job.date_basis)

    def test_pinpoint_can_enrich_jsonld_date_on_post_page(self):
        source={'name':'SafetyWing','type':'pinpoint','slug':'safetywing',
                'careers':'https://safetywing.pinpointhq.com/en',
                'global_remote_default':True}
        detail='https://safetywing.pinpointhq.com/en/postings/xxx'
        def fetch(url):
            if url.endswith('postings.json'):
                return json.dumps({'data':[{'id':'x','title':'Product Manager',
                    'url':detail,'location':{'name':'Remote'}, 'workplace_type':'remote'}]})
            return '<script type="application/ld+json">'+json.dumps({'@type':'JobPosting',
                   'title':'Product Manager','datePosted':ISO,'jobLocationType':'TELECOMMUTE',
                   'applicantLocationRequirements':{'name':'India'},'url':detail})+'</script>'
        jobs,status,warning,kind=r.fetch_company(source,fetch=fetch)
        self.assertEqual('OK',status)
        self.assertEqual(1,len(jobs))
        self.assertEqual(ISO,jobs[0].timestamp)

    def test_no_false_empty_from_hidden_template_text(self):
        self.assertFalse(r.explicit_empty_page('<p>We are hiring!</p><template>No open roles</template>'))
        self.assertTrue(r.explicit_empty_page('<h2>No open roles</h2>'))

    def test_health_report_uses_existing_diagnostics(self):
        import health_summary
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'output').mkdir()
            (root/'output/summary.json').write_text(json.dumps({
                 'sources_readable':32,'companies_configured':51,'jobs_fetched':504,
                 'matching_role_titles':72,'matching_india_global_locations':6,
                 'matching_with_usable_publication_time':6,
                 'matching_postings_within_24h':0,'new_matches':0}))
            with (root/'output/unreadable_sources.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['Company','Status','Error / limitation','Careers'])
                w.writerow(['Toggl','ERROR','HTTP 404','https://toggl.com/jobs'])
            summary=health_summary.report(root)
            self.assertIn('Toggl',summary)
            self.assertIn('504 jobs fetched',summary)

class ContradictoryGeographyTests(unittest.TestCase):
    def test_us_only_location_overrides_india_in_title(self):
        j=r.Job('X','1','Product Manager - India','Remote US Only','remote',ISO,'published','https://a.test')
        self.assertEqual('',r.remote_region(j))
    def test_multi_country_remote_including_india_stays_valid(self):
        j=r.Job('X','1','Product Manager','Remote United States; Remote India','remote',ISO,'published','https://a.test')
        self.assertEqual('India',r.remote_region(j))
