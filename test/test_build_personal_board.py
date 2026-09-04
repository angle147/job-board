import unittest

from build_personal_board import SourceSpec, classify_record, merge_bucket


class BroadSoeEntryTests(unittest.TestCase):
    def setUp(self):
        self.soe = SourceSpec("fixture.js", "FIXTURE", "测试官方国企源", "soe", "官方")
        self.public = SourceSpec("fixture.js", "FIXTURE", "测试编制源", "public", "官方")

    def test_campus_notice_no_longer_requires_position_major_or_deadline(self):
        bucket, record = classify_record({
            "id": "1",
            "companyName": "某央企",
            "positions": "某央企校园招聘公告",
            "targetYears": "",
            "noticeLink": "https://www.sasac.gov.cn/example",
        }, self.soe)
        self.assertEqual(bucket, "soe")
        self.assertEqual(record["fitLevel"], "待核验")
        self.assertEqual(record["deadline"], "待核验")

    def test_explicit_2026_soe_is_excluded(self):
        bucket, record = classify_record({
            "id": "2026",
            "companyName": "某央企",
            "positions": "某央企2026届校园招聘公告",
            "targetYears": "2026届",
            "noticeLink": "https://www.sasac.gov.cn/example-2026",
        }, self.soe)
        self.assertEqual(bucket, "excluded")
        self.assertIn("不面向目标届别", record["exclusionReasons"])

    def test_mixed_2026_and_2027_notice_is_excluded(self):
        bucket, record = classify_record({
            "id": "mixed",
            "companyName": "某央企",
            "positions": "2026届校园招聘、2027届实习生招聘",
            "targetYears": "2027届",
            "noticeLink": "https://www.sasac.gov.cn/example-mixed",
        }, self.soe)
        self.assertEqual(bucket, "excluded")
        self.assertIn("不面向目标届别", record["exclusionReasons"])

    def test_explicit_2026_campus_year_is_excluded(self):
        bucket, record = classify_record({
            "id": "2026-campus",
            "companyName": "某央企",
            "positions": "某央企2026年校招补招公告",
            "targetYears": "待核验",
            "noticeLink": "https://www.sasac.gov.cn/example-2026-campus",
        }, self.soe)
        self.assertEqual(bucket, "excluded")
        self.assertIn("不面向目标届别", record["exclusionReasons"])

    def test_non_graduate_recruitment_stays_in_review(self):
        bucket, _ = classify_record({
            "id": "2",
            "companyName": "某央企",
            "positions": "某央企公开招聘公告",
            "noticeLink": "https://www.sasac.gov.cn/example2",
        }, self.soe)
        self.assertEqual(bucket, "review")

    def test_pure_social_recruitment_is_still_excluded(self):
        bucket, _ = classify_record({
            "id": "3",
            "companyName": "某央企",
            "positions": "某央企社会招聘公告",
            "recruitType": "社招",
            "noticeLink": "https://www.sasac.gov.cn/example3",
        }, self.soe)
        self.assertEqual(bucket, "excluded")

    def test_public_board_does_not_inherit_broadened_rule(self):
        bucket, _ = classify_record({
            "id": "4",
            "companyName": "某事业单位",
            "positions": "2026届高校毕业生招聘公告",
            "targetYears": "2026届",
            "noticeLink": "https://www.gov.cn/example4",
        }, self.public)
        self.assertEqual(bucket, "excluded")

    def test_formal_soe_wins_over_review_duplicate_in_either_order(self):
        self.assertEqual(merge_bucket("soe", "review"), "soe")
        self.assertEqual(merge_bucket("review", "soe"), "soe")

    def test_excluded_duplicate_still_wins_over_formal_bucket(self):
        self.assertEqual(merge_bucket("soe", "excluded"), "excluded")


if __name__ == "__main__":
    unittest.main()
