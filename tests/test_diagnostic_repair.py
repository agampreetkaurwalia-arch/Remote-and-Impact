import json
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import remote_radar as r

class DiagnosticRepairTests(unittest.TestCase):
    def test_51_still_configured(self):
        config = json.loads((ROOT / 'companies.json').read_text())
        self.assertEqual(len(config['companies']), 51)
        source = {x['name']: x for x in config['companies']}
        self.assertEqual((source['Kinsta']['type'], source['Kinsta']['slug']), ('lever','kinsta'))
        self.assertEqual((source['Remote']['type'], source['Remote']['slug']), ('greenhouse','remotecom'))
        self.assertEqual((source['Doist']['type'], source['Doist']['slug']), ('workable','doist'))
        self.assertEqual((source['Whereby']['type'], source['Whereby']['slug']), ('lever','whereby'))

    def test_never_override_regional_scope_with_global_company_default(self):
        cases=['Remote EMEA','Remote-UK&I','Remote Americas','Remote - US','Remote APAC','Europe (Remote)','Remote Canada']
        for loc in cases:
            with self.subTest(loc=loc):
                job=r.Job('Company','123','Product Manager',loc,'Remote','2026-11-03T03:01:00Z','published','https://example.org')
                self.assertEqual(r.remote_region(job,assumed_global=True),'')

    def test_global_default_works_with_plain_remote(self):
        job=r.Job('Doist','1','Product Manager','Remote','Remote','2026-11-03T03:01:00Z','published','https://example.org')
        self.assertEqual(r.remote_region(job,assumed_global=True),'Global / Anywhere')

    def test_advertising_only_location_at_doist(self):
        job=r.Job('Doist','x','Project Manager','Remote - Germany','Remote', '2026-11-03T03:01:00Z','published','https://example.org')
        self.assertEqual(r.remote_region(job, assumed_global=True, locations_are_advertising_only=True),'Global / Anywhere')

    def test_india_override_remains_eligible(self):
        job=r.Job('Company','1','Project Manager','Remote - India','Remote','2026-11-03T03:01:00Z','published','https://example.org')
        self.assertEqual(r.remote_region(job,assumed_global=True),'India')

if __name__=='__main__': unittest.main()
