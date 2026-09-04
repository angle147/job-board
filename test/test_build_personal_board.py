import unittest

from build_personal_board import SourceSpec, classify_record


class BroadSoeEntryTests(unittest.TestCase):
    def setUp(self):
        self.soe = SourceSpec("fixture.js", "FIXTURE", "测试官方国企源", "soe", "官方")
        self.public = SourceSpec("fixture.js", "FIXTURE", "测试编制源", "public", "官方")

    def test_campus_notice_no_longer_requires_position_major_or_deadline(self):
        bucket, record = classify_record({
            "id": "1",
            "companyName": "某央企",
            "positions": "某央企2026届校园招聘公告",
            "targetYears": "2026届",
            "noticeLink": "https://www.sasac.gov.cn/example",
        }, self.soe)
        self.assertEqual(bucket, "soe")
        self.assertEqual(record["fitLevel"], "待核验")
        self.assertEqual(record["deadline"], "待核验")

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


if __name__ == "__main__":
    unittest.main()
