import unittest
from datetime import date
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from pydantic import ValidationError
from touchline.features import window_totals, FEATURES
from touchline.api import app, Stats, matrix, data
from touchline.train import interval

class FeatureTests(unittest.TestCase):
    def test_no_future_or_same_day_results(self):
        dates = pd.to_datetime(["2024-01-01","2024-12-31","2025-01-01","2025-01-02"])
        matches = pd.DataFrame({"date":dates,"minutes_played":[90]*4,"goals":[1,2,20,40],
                               "assists":[0]*4,"yellow_cards":[0]*4,"red_cards":[0]*4})
        totals, counts, _ = window_totals(matches, pd.to_datetime(["2025-01-01"]), 365)
        # 2024 was a leap year: Jan 1 lies outside this 365-day window.
        self.assertEqual(totals[0,1],2)
        self.assertEqual(counts[0],1)

    def test_no_price_inputs(self):
        self.assertFalse(any("value" in key or "price" in key for key in FEATURES))

    def test_range_brackets_point(self):
        low, high = interval(np.array([np.log1p(1e6)]), .5)
        self.assertLess(low[0],1e6)
        self.assertGreater(high[0],1e6)

class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.player = data()["players"][0]
        cls.payload = {key: cls.player[key] for key in FEATURES if key not in {"goals_per90","assists_per90"}}
        cls.payload["stats_as_of"] = cls.player["date"]

    def test_player_search_and_detail(self):
        result = self.client.get("/api/players",params={"q":self.player["name"]})
        self.assertEqual(result.status_code,200)
        self.assertTrue(any(p["player_id"]==self.player["player_id"] for p in result.json()))
        detail=self.client.get("/api/players/"+str(self.player["player_id"]))
        self.assertEqual(detail.status_code,200)
        self.assertIn("history",detail.json())

    def test_unknown_player(self):
        self.assertEqual(self.client.get("/api/players/-1").status_code,404)

    def test_predict_matches_export(self):
        result=self.client.post("/api/predict",json=self.payload)
        self.assertEqual(result.status_code,200,result.text)
        body=result.json()
        self.assertLessEqual(abs(body["predicted_value"]-self.player["predicted_value"]),1000)
        self.assertLessEqual(body["lower"],body["predicted_value"])
        self.assertGreaterEqual(body["upper"],body["predicted_value"])

    def test_reject_inconsistent_recent_stats(self):
        payload=self.payload|{"goals":0,"recent_goals":5}
        self.assertEqual(self.client.post("/api/predict",json=payload).status_code,422)

    def test_reject_zero_minutes(self):
        self.assertEqual(self.client.post("/api/predict",json=self.payload|{"minutes":0}).status_code,422)

    def test_reject_future_date(self):
        self.assertEqual(self.client.post("/api/predict",json=self.payload|{"stats_as_of":"2099-01-01"}).status_code,422)

    def test_filter_league_and_position(self):
        result=self.client.get("/api/players?league=ES1&position=Defender").json()
        self.assertTrue(result)
        self.assertTrue(all(x["league"]=="ES1" and x["position"]=="Defender" for x in result))

    def test_demo_dates_are_labeled_and_not_presented_as_real_evaluation(self):
        m=data()["metadata"]
        self.assertTrue(m['synthetic_demo'])
        self.assertFalse(data()['evaluation']['evaluated'])
        self.assertNotIn('train',m)
        self.assertLessEqual(date.fromisoformat(m["source"]["appearances_through"]),date.today())

    def test_homepage(self):
        self.assertEqual(self.client.get("/").status_code,200)
        self.assertEqual(self.client.get("/assets/app.js").status_code,200)

if __name__ == "__main__":
    unittest.main()
