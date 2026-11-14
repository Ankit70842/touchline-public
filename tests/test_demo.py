import unittest
from touchline.demo import build_demo


class DemoTests(unittest.TestCase):
    def test_demo_is_deterministic_fictional_and_does_not_claim_evaluation(self):
        first=build_demo();second=build_demo()
        self.assertEqual(first['players'],second['players'])
        self.assertTrue(first['metadata']['synthetic_demo'])
        self.assertFalse(first['evaluation']['evaluated'])
        self.assertEqual(len(first['players']),12)
        for p in first['players']:
            self.assertTrue(p['name'].startswith('Demo Player '))
            self.assertEqual(p['valuation_aware_value'],p['previous_value'])
            self.assertLess(p['previous_value_date'],p['date'])
            self.assertLess(p['stats_through'],p['date'])


if __name__=='__main__':
    unittest.main()
