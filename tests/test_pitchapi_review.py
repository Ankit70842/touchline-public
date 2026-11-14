import json
from pathlib import Path
import tempfile
import unittest
from touchline.pitchapi_review import decide, review_queue


class ReviewWorkflowTests(unittest.TestCase):
    def test_review_is_explicit_audited_and_rejections_are_not_approvals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'artifacts/pitchapi').mkdir(parents=True)
            queue = [{'provider_player_id':'p_a','provider_name':'Fixture','status':'needs_review',
                      'candidate_ids':[1], 'observations':[]}]
            (root/'artifacts/pitchapi/review_queue.json').write_text(json.dumps(queue))
            (root/'artifacts/players.json').write_text(json.dumps([{'player_id':1,'name':'Fixture'}]))
            with self.assertRaises(ValueError):
                decide(root,'p_a','approve',1,'','',review_queue(root)[0]['revision'])
            revision = review_queue(root)[0]['revision']
            result = decide(root,'p_a','reject',1,'fixture source','Different person',revision)
            self.assertEqual(result['action'],'reject')
            self.assertEqual(review_queue(root)[0]['rejected_candidate_ids'],[1])
            self.assertFalse((root/'data/pitchapi-local/manual_mappings.json').exists())
            with self.assertRaises(ValueError):
                decide(root,'p_a','approve',1,'fixture source','Stale review',revision)
            with self.assertRaises(ValueError):
                decide(root,'p_a','approve',999,'fixture source','Wrong reference',review_queue(root)[0]['revision'])
            decide(root,'p_a','approve',1,'fixture independent crosswalk','Confirmed stable identity',review_queue(root)[0]['revision'])
            manual = json.loads((root/'data/pitchapi-local/manual_mappings.json').read_text())
            self.assertEqual(manual[0]['player_id'],1)
            self.assertEqual(len(review_queue(root)[0]['review_history']),2)


if __name__ == '__main__':
    unittest.main()
