import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ai_cost_report import print_report
from database import initialize_database, record_ai_cost


class AiCostReportTests(unittest.TestCase):
    def test_report_lists_calls_and_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            initialize_database(database_file)
            record_ai_cost(
                provider="openai",
                operation="job_extract",
                model="gpt-5.4-mini",
                response_id="resp_report",
                job_uid=None,
                profile_name=None,
                input_tokens=1_000,
                cached_input_tokens=100,
                output_tokens=200,
                reasoning_output_tokens=50,
                total_tokens=1_200,
                input_cost_usd=0.000675,
                cached_input_cost_usd=0.0000075,
                output_cost_usd=0.0009,
                total_cost_usd=0.0015825,
                database_file=database_file,
            )

            output = io.StringIO()
            with redirect_stdout(output):
                print_report(database_file)

            report = output.getvalue()
            self.assertIn("All AI calls", report)
            self.assertIn("job_extract", report)
            self.assertIn("By operation", report)
            self.assertIn("By model", report)
            self.assertIn("Grand total: 1 calls, 1,200 tokens, $0.001582", report)


if __name__ == "__main__":
    unittest.main()
