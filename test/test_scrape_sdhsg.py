import unittest

from scrape_sdhsg import convert, extract_date, extract_target_years, job_matches_announcement


class ShandongExpresswayScraperTests(unittest.TestCase):
    def test_extracts_deadline_and_target_year(self):
        text = "面向2027届应届毕业生，报名截止时间：2026年10月18日。"
        self.assertEqual(extract_target_years(text), "2027届")
        self.assertEqual(extract_date(text, deadline=True), "2026-10-18")

    def test_does_not_treat_age_calculation_as_deadline(self):
        text = "年龄计算截止时间2026年5月31日。\n2.截止时间\n自公告发布之日起至2026年6月17日。"
        self.assertEqual(extract_date(text, deadline=True), "2026-06-17")

    def test_infers_cohort_from_campus_batch_year(self):
        self.assertEqual(extract_target_years("2026年上半年校园招聘公告"), "2026届")

    def test_matches_job_by_org_id(self):
        announcement = {"title": "山东高速集团有限公司2027届校园招聘公告", "orgId": 1}
        self.assertTrue(job_matches_announcement({"orgId": 1, "name": "物流管理岗"}, announcement))
        self.assertFalse(job_matches_announcement({"orgId": 2, "name": "物流管理岗"}, announcement))

    def test_marks_two_channel_match(self):
        announcement = {"id": 9, "orgId": 1, "recruitType": 3, "title": "山东高速集团有限公司2027届校园招聘公告"}
        detail = {
            "title": announcement["title"], "releaseTime": "2026-09-01 10:00:00",
            "content": "报名截止时间：2026年10月18日。报名网址：https://zhaopin.sdhsg.com/#/centralizedRecruitment?orgId=1",
        }
        record = convert(announcement, detail, [{"orgId": 1, "name": "物流管理岗"}], [])
        self.assertEqual(record["verificationStatus"], "cross_verified")
        self.assertEqual(record["sourceChannelCount"], 2)
        self.assertEqual(record["deadline"], "2026-10-18")

    def test_attachment_is_independent_recruitment_artifact(self):
        announcement = {"id": 9, "orgId": 1, "recruitType": 3, "title": "山东高速集团有限公司2027届校园招聘公告"}
        attachment = {"name": "招聘岗位计划表.xlsx", "url": "https://zhaopin.sdhsg.com/files/jobs.xlsx"}
        record = convert(announcement, {"title": announcement["title"], "content": ""}, [], [], [attachment])
        self.assertEqual(record["verificationStatus"], "cross_verified")
        self.assertEqual(record["sourceChannelCount"], 2)
        self.assertEqual(record["attachmentLink"], attachment["url"])

    def test_keeps_single_source_explicit(self):
        announcement = {"id": 9, "orgId": 1, "recruitType": 3, "title": "山东高速集团有限公司2027届校园招聘公告"}
        record = convert(announcement, {"title": announcement["title"], "content": ""}, [], [])
        self.assertEqual(record["verificationStatus"], "single_source")
        self.assertIn("单源待复核", record["notes"])


if __name__ == "__main__":
    unittest.main()
