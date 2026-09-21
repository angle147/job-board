import json
import re
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]


class StatusKeyTests(unittest.TestCase):
    def test_soe_ids_are_unique_for_v3_status_keys(self):
        text = (BASE / "data" / "board_soe.js").read_text(encoding="utf-8")
        records = json.loads(re.search(r"=\s*(\[.*\]);", text, re.S).group(1))
        ids = [str(item["id"]) for item in records]
        self.assertEqual(len(ids), len(set(ids)))

    def test_frontend_uses_v3_per_job_keys(self):
        text = (BASE / "index.html").read_text(encoding="utf-8")
        self.assertIn("if (item.id) return String(item.id);", text)
        self.assertIn("job_status_v3|${tab}|", text)


if __name__ == "__main__":
    unittest.main()
