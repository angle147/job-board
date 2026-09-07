import json
import unittest

from scrape_cosco_iguopin import convert, parse_campus_config, parse_company_campus_config


class CoscoIguopinTests(unittest.TestCase):
    def test_parse_current_campus_project_from_public_config(self):
        result = {
            "data": {
                "company_id": "company-1",
                "content": json.dumps({
                    "params": {"nav": [{
                        "route": "/job",
                        "type": "job",
                        "props": {"projectId": "project-1", "nature": "campus,graduate"},
                    }]},
                }),
            },
        }
        self.assertEqual(parse_campus_config(result), ("project-1", ["campus", "graduate"], "company-1"))

    def test_convert_preserves_job_level_fields_and_cohort(self):
        record = convert({
            "job_id": "job-1",
            "job_name": "物流管理岗",
            "company_name": "中远海运物流有限公司",
            "recruitment_type_cn": "校园招聘",
            "major_cn": ["交通运输类", "物流管理与工程类"],
            "education_cn": "硕士",
            "amount": 2,
            "start_time": "2026-09-04 00:00:00",
            "end_time": "2026-10-31 00:00:00",
            "contents": "面向2027届应届毕业生",
            "district_list": [{"area_cn": "济南-历下区"}],
            "company_info": {"industry_cn": "道路运输业", "scale_cn": "1000-2000人"},
        })
        self.assertEqual(record["targetYears"], "2027届")
        self.assertEqual(record["majorReq"], "交通运输类、物流管理与工程类")
        self.assertEqual(record["deadline"], "2026-10-31")
        self.assertEqual(record["applyLink"], "https://coscoshipping.iguopin.com/job/detail?id=job-1")

    def test_parse_company_level_campus_config(self):
        result = {
            "data": {
                "company_id": "cmhk-company",
                "content": json.dumps({
                    "params": {"nav": [{
                        "route": "/jobCampus",
                        "type": "job",
                        "props": {"type": "campus", "nature": "campus,graduate"},
                    }]},
                }),
            },
        }
        self.assertEqual(parse_company_campus_config(result), (["campus", "graduate"], "cmhk-company"))


if __name__ == "__main__":
    unittest.main()
