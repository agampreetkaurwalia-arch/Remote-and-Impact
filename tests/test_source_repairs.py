"""Regression coverage for 2026-11-03 source repair.
No network and no writes to the live state or output directory.
"""
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
import remote_radar as r

NOW = datetime(2026, 11, 3, 2, 11, tzinfo=timezone.utc)

class SourceRepairTests(unittest.TestCase):
    def test_roster_unchanged(self):
        c=json.loads((r.ROOT/'companies.json').read_text())
        self.assertEqual(51,len(c['companies']))
        self.assertEqual(51,len({s['name'] for s in c['companies']}))
        self.assertEqual(24,c['window_hours'])
        self.assertEqual('Asia/Kolkata',c['timezone'])

    def test_product_growth_manager_is_role_match(self):
        self.assertTrue(r.role_matches("Senior Product Growth Manager"))

    def test_verified_candidates_configured(self):
        c=json.loads((r.ROOT/'companies.json').read_text())
        by={s['name']:s for s in c['companies']}
        for name,typ,slug in [
            ('Automattic','greenhouse','automatticcareers'),
            ('Kit','ashby','kit'),
            ('Zyte','workable','zyte'),
            ('John Snow Labs','smartrecruiters','JohnSnowLabs'),
        ]:
            self.assertEqual((typ,slug),(by[name]['type'],by[name]['slug']))
        self.assertTrue(by['Automattic']['global_remote_default'])
        self.assertTrue(by['John Snow Labs']['global_remote_default'])
        self.assertFalse(by['Kit'].get('global_remote_default',False))

    def test_generic_remote_only_with_verified_company_default(self):
        job=r.Job('Automattic','123','Product Manager','Remote','',NOW.isoformat(),'first_published','https://example.com/job')
        self.assertEqual('',r.remote_region(job))
        self.assertEqual('Global / Anywhere',r.remote_region(job,assumed_global=True))

    def test_title_region_restriction_beats_global_company(self):
        for title in ('Product Manager - US','Strategy Consultant — EMEA', 'Project Manager (Europe)'):
            job=r.Job('Automattic','123',title,'Remote','',NOW.isoformat(),'first_published','https://example.com/job')
            self.assertEqual('',r.remote_region(job,assumed_global=True),title)
        job=r.Job('Automattic','123','Product Manager - India','Remote','',NOW.isoformat(),'first_published','https://example.com/job')
        self.assertEqual('India',r.remote_region(job,assumed_global=True))

    def test_smartrecruiters_released_date(self):
        item={'content':[{'id':'test-1','name':'Product Manager','releasedDate':NOW.isoformat(),
             'location':{'remote':True,'country':'IN'},'jobUrl':'https://example.org/smart/1'}]}
        job=list(r.parse_smartrecruiters('John Snow Labs',item))[0]
        self.assertEqual('India',r.remote_region(job))
        self.assertEqual(NOW,r.parse_timestamp(job.timestamp))
        self.assertEqual('smartrecruiters_releasedDate',job.date_basis)

    def test_smartrecruiters_missing_date_not_converted_to_posted(self):
        item={'content':[{'id':'t','name':'Product Manager','location':{'remote':True}}]}
        job=list(r.parse_smartrecruiters('John Snow Labs',item))[0]
        self.assertIsNone(r.parse_timestamp(job.timestamp))
        self.assertEqual('Global / Anywhere',r.remote_region(job,assumed_global=True))

    def test_source_health_has_filter_stage_counts_and_email_stays_four_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'state').mkdir()
            (root/'companies.json').write_bytes((r.ROOT/'companies.json').read_bytes())
            def fake(url):
                if 'smartrecruiters' in url:
                    return json.dumps({'content': [
                        {'id':'1','name':'Product Manager','releasedDate':NOW.isoformat(),
                         'location':{'remote':True,'country':'India'},
                         'jobUrl':'https://example.org/job1'}]})
                if 'boards-api.greenhouse.io' in url:
                    return json.dumps({'jobs':[{'id':1,'title':'Product Manager',
                        'location':{'name':'Remote India'},'first_published':NOW.isoformat(),
                        'absolute_url':'https://example.org/job1'}]})
                if 'posting-api/job-board' in url:
                    return json.dumps({'jobs':[{'id':'1','title':'Product Manager',
                        'location':'India','workplaceType':'Remote',
                        'publishedAt':NOW.isoformat(),
                        'jobUrl':'https://example.org/job1'}]})
                if 'api.lever.co' in url:
                    return json.dumps([])
                if 'apply.workable.com/api/' in url:
                    return json.dumps({'jobs':[]})
                return '<h2>No open roles</h2>'
            summary=r.run(root,fetch=fake,now=NOW,workers=3)
            self.assertTrue(summary['first_run_baseline'])
            import csv
            with (root/'output/source_health.csv').open() as f:
                health=list(csv.DictReader(f))
            self.assertEqual(51,len(health))
            self.assertIn('Matching role titles',health[0])
            self.assertIn('Matching with usable timestamp',health[0])
            self.assertIn('Matching India/global location',health[0])
            email=(root/'output/email.md').read_text()
            self.assertIn('| Company | Role | Posted within 24 hours | Work location |',email)
            self.assertEqual(0,summary['new_matches'])

if __name__ == '__main__':
    unittest.main()
