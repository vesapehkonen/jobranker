import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app import saved_job_description


class SavedDescriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = Request({
            "type": "http",
            "method": "GET",
            "path": "/jobs/job-1/description",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
        })

    def test_saved_description_renders_archived_text_safely(self) -> None:
        job = {
            "title": "Platform Engineer",
            "company": "Example & Co",
            "location": "Remote",
            "workplace_type": "Remote",
            "employment_type": "Full-time",
            "salary_range": "$100–120k",
            "cleaned_description_text": "About the job\nBuild <reliable> systems.",
            "description": "Short fallback",
        }
        with patch("app.read_job", return_value=job):
            response = saved_job_description(self.request, "job-1")

        self.assertEqual(200, response.status_code)
        body = response.body.decode()
        self.assertIn("Platform Engineer", body)
        self.assertIn("<h3>About the job</h3>", body)
        self.assertIn("<p>Build &lt;reliable&gt; systems.</p>", body)
        self.assertNotIn("Short fallback", body)

    def test_saved_description_returns_not_found_for_unknown_job(self) -> None:
        with patch("app.read_job", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                saved_job_description(self.request, "missing")
        self.assertEqual(404, raised.exception.status_code)


if __name__ == "__main__":
    unittest.main()
