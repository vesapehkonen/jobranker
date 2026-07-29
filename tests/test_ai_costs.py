import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_costs import track_openai_response
from database import connect


class AiCostTests(unittest.TestCase):
    def test_tracks_token_breakdown_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            usage = SimpleNamespace(
                input_tokens=1_000_000,
                output_tokens=100_000,
                total_tokens=1_100_000,
                input_tokens_details=SimpleNamespace(cached_tokens=200_000),
                output_tokens_details=SimpleNamespace(reasoning_tokens=25_000),
            )
            response = SimpleNamespace(
                id="resp_123", model="gpt-5.4-mini-2026-03-17", usage=usage
            )

            tracked = track_openai_response(
                response,
                "job_rank",
                profile_name="backend",
                database_file=database_file,
            )
            track_openai_response(
                response,
                "job_rank",
                profile_name="backend",
                database_file=database_file,
            )

            self.assertEqual(200_000, tracked["cached_input_tokens"])
            self.assertEqual(25_000, tracked["reasoning_output_tokens"])
            self.assertAlmostEqual(1.065, tracked["total_cost_usd"])
            with connect(database_file) as db:
                count = db.execute("SELECT COUNT(*) FROM ai_costs").fetchone()[0]
            self.assertEqual(1, count)

    def test_unknown_model_tracks_tokens_without_guessing_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            response = SimpleNamespace(
                id="resp_unknown",
                model="custom-model",
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                ),
            )
            tracked = track_openai_response(
                response, "job_extract", database_file=database_file
            )
            self.assertEqual(15, tracked["total_tokens"])
            self.assertIsNone(tracked["total_cost_usd"])

    def test_gpt_5_6_model_prices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            response = SimpleNamespace(
                id="resp_terra",
                model="gpt-5.6-terra",
                usage=SimpleNamespace(
                    input_tokens=1_000_000,
                    output_tokens=100_000,
                    total_tokens=1_100_000,
                ),
            )
            tracked = track_openai_response(
                response, "job_rank", database_file=database_file
            )
            self.assertAlmostEqual(4.0, tracked["total_cost_usd"])

    def test_gpt_5_4_nano_price(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "jobranker.db"
            response = SimpleNamespace(
                id="resp_nano",
                model="gpt-5.4-nano-2026-03-17",
                usage=SimpleNamespace(
                    input_tokens=1_000_000,
                    output_tokens=100_000,
                    total_tokens=1_100_000,
                ),
            )
            tracked = track_openai_response(
                response, "job_extract", database_file=database_file
            )
            self.assertAlmostEqual(0.325, tracked["total_cost_usd"])


if __name__ == "__main__":
    unittest.main()
