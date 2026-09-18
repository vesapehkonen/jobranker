import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from experiments.structured_matching.run import run
from experiments.structured_matching.capabilities import extract_capabilities
from experiments.structured_matching.qualifications import extract_education, extract_experience
from experiments.structured_matching.technologies import extract_technologies


class TechnologyExtractionTests(unittest.TestCase):
    def test_capabilities_are_canonicalized_and_kept_separate_from_technologies(self):
        text = (
            "Build containerized microservices and distributed systems. Own CI/CD, "
            "infrastructure-as-code, automated testing, observability, and incident response."
        )
        capability_names = {item["name"] for item in extract_capabilities(text)}
        technology_names = {item["name"] for item in extract_technologies(text)}
        self.assertTrue({
            "CI/CD", "Containerization", "Distributed Systems",
            "Infrastructure as Code", "Microservices", "Observability",
            "Production Support", "Test Automation",
        } <= capability_names)
        self.assertTrue(capability_names.isdisjoint(technology_names))

    def test_education_extraction_handles_degree_levels_and_equivalent_experience(self):
        result = extract_education("""Minimum Qualifications:
Bachelor’s degree in Computer Science or equivalent professional experience.
Preferred Qualifications:
Master's degree in Computer Science.
""")
        self.assertIsNone(result["minimum_level"])
        self.assertEqual(["bachelor", "master"], result["levels_found"])
        self.assertTrue(result["equivalent_experience_allowed"])
        self.assertEqual("required", result["mentions"][0]["classification"])
        self.assertEqual("preferred", result["mentions"][1]["classification"])

    def test_education_extraction_handles_coordinated_degree_phrase(self):
        result = extract_education(
            "Bachelor’s or Master’s degree in Computer Science, Engineering, or related field."
        )
        self.assertEqual("bachelor", result["minimum_level"])
        self.assertEqual(["bachelor", "master"], result["levels_found"])

    def test_education_preference_in_later_sentence_does_not_change_high_school(self):
        result = extract_education(
            "High school diploma or equivalent. Technical training or certification "
            "in CMM programming, metrology, quality control, or a related field preferred."
        )
        self.assertEqual("high_school", result["minimum_level"])
        self.assertEqual("unspecified", result["mentions"][0]["classification"])

    def test_preferred_associate_degree_does_not_set_required_minimum(self):
        result = extract_education(
            "Associate degree or higher in manufacturing technology, mechanical "
            "engineering, computer-aided manufacturing, or a related technical "
            "discipline is a plus."
        )
        self.assertIsNone(result["minimum_level"])
        self.assertEqual(["associate"], result["levels_found"])
        self.assertEqual("preferred", result["mentions"][0]["classification"])

    def test_standalone_bs_and_ms_abbreviations_are_education(self):
        result = extract_education(
            "MS with 6+ years, or BS (or equivalent experience) with 8+ years "
            "of relevant experience in Computer Science, Computer Engineering, "
            "or a related technical field."
        )
        self.assertIsNone(result["minimum_level"])
        self.assertEqual(["bachelor", "master"], result["levels_found"])
        self.assertTrue(result["equivalent_experience_allowed"])

    def test_slash_separated_degrees_with_abbreviated_fields_are_education(self):
        result = extract_education("BS/MS in CS, EE, Math or a related STEM field")
        self.assertEqual("bachelor", result["minimum_level"])
        self.assertEqual(["bachelor", "master"], result["levels_found"])

    def test_standalone_ms_without_education_context_is_ignored(self):
        result = extract_education("The request completed in 25 MS without errors.")
        self.assertIsNone(result["minimum_level"])

    def test_experience_extraction_uses_highest_required_minimum(self):
        result = extract_experience("""Minimum Qualifications:
At least 7+ years of professional software development experience.
3-5 years working with distributed systems.
Preferred Qualifications:
Ten years of cloud engineering experience.
Our company has 20 years of experience serving customers.
""")
        self.assertEqual(7, result["minimum_years"])
        self.assertEqual([7, 3, 10], [item["minimum_years"] for item in result["mentions"]])
        self.assertEqual("preferred", result["mentions"][2]["classification"])

    def test_experience_extraction_excludes_company_tenure(self):
        result = extract_experience(
            "With more than 40 years of experience in design and manufacturing, "
            "we provide precision components."
        )
        self.assertIsNone(result["minimum_years"])
        self.assertEqual([], result["mentions"])

    def test_experience_extraction_excludes_first_person_company_history(self):
        result = extract_experience(
            "We've been innovating fearlessly for 40 years to create solutions "
            "that power how humans and technology work together across the "
            "physical and digital worlds."
        )
        self.assertIsNone(result["minimum_years"])
        self.assertEqual([], result["mentions"])

        curly_apostrophe = extract_experience(
            "We’ve served technology customers for 25 years across the world."
        )
        self.assertIsNone(curly_apostrophe["minimum_years"])

    def test_experience_extraction_keeps_candidate_duration_using_for(self):
        result = extract_experience(
            "You have worked in software development for 5 years."
        )
        self.assertEqual(5, result["minimum_years"])

    def test_experience_extraction_keeps_explicit_long_candidate_requirement(self):
        result = extract_experience(
            "Candidates must have a minimum of 20 years of engineering experience."
        )
        self.assertEqual(20, result["minimum_years"])

    def test_experience_handles_plus_ranges_parentheses_and_months(self):
        ranged = extract_experience(
            "Candidates need 2–12+ years of professional software development experience."
        )
        parenthetical = extract_experience(
            "Minimum of five (5) years of related engineering experience."
        )
        months = extract_experience(
            "A degree and 60 months of professional development experience are required."
        )
        self.assertEqual(2, ranged["minimum_years"])
        self.assertEqual(12, ranged["mentions"][0]["maximum_years"])
        self.assertEqual(5, parenthetical["minimum_years"])
        self.assertEqual(5, months["minimum_years"])

    def test_experience_recognizes_years_in_named_engineering_role(self):
        result = extract_experience(
            "Candidates need 5+ years in DevOps, SRE, or a closely related role."
        )
        self.assertEqual(5, result["minimum_years"])

    def test_aliases_are_canonicalized_and_word_boundaries_avoid_java_false_match(self):
        extracted = extract_technologies(
            "Build JavaScript services on Amazon Web Services with Postgres and K8s."
        )
        names = {item["name"] for item in extracted}
        self.assertTrue({"JavaScript", "AWS", "PostgreSQL", "Kubernetes"} <= names)
        self.assertNotIn("Java", names)

    def test_bare_aws_service_names_are_detected_in_technical_context(self):
        names = {
            item["name"]
            for item in extract_technologies(
                "Migrate data from EMR and Redshift to RDS Aurora on AWS."
            )
        }
        self.assertTrue({"AWS", "Aurora", "EMR", "RDS", "Redshift"} <= names)

    def test_system_and_performance_resume_technologies_are_detected(self):
        names = {
            item["name"]
            for item in extract_technologies(
                "AVX-512, iptables, McAfee Data Exchange Layer (DXL), LZ4, "
                "Zstandard, Async Profiler, Linux perf, and Ångström Linux"
            )
        }
        self.assertTrue({
            "AVX-512", "iptables", "McAfee DXL", "LZ4", "Zstandard",
            "async-profiler", "Linux perf", "Ångström Linux",
        } <= names)

    def test_dxl_requires_vendor_or_expansion_context(self):
        names = {item["name"] for item in extract_technologies("A DXL file was provided")}
        self.assertNotIn("McAfee DXL", names)

    def test_ambiguous_short_language_names_are_not_normal_words(self):
        names = {item["name"] for item in extract_technologies("Go to work and see plan C.")}
        self.assertNotIn("Go", names)
        self.assertNotIn("C", names)
        names = {item["name"] for item in extract_technologies("Golang and C programming")}
        self.assertTrue({"Go", "C"} <= names)

    def test_capitalized_short_language_names_are_detected(self):
        names = {
            item["name"]
            for item in extract_technologies("Programming languages: Python, Go, C, and VB.")
        }
        self.assertTrue({"Go", "C", "Visual Basic"} <= names)

    def test_ambiguous_product_words_require_technical_context(self):
        names = {
            item["name"]
            for item in extract_technologies(
                "Companies can react faster. Donkey Kong and SOC 2 are trademarks and standards."
            )
        }
        self.assertTrue({"React", "Kong", "SoC"}.isdisjoint(names))

    def test_portal_chrome_is_excluded_from_extraction(self):
        text = """Recommended Python Developer
Full job description
Build services with Java.
Similar Jobs (5)
React Developer
"""
        self.assertEqual(
            ["Java"],
            [item["name"] for item in extract_technologies(text)],
        )

    def test_end_to_end_run_writes_word_search_review_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "jobs.db"
            output = root / "output"
            with sqlite3.connect(database) as db:
                db.executescript("""
                    CREATE TABLE jobs (
                        job_uid TEXT, page_title TEXT, application_status TEXT, created_at TEXT
                    );
                    CREATE TABLE job_artifacts (job_uid TEXT, cleaned_json TEXT);
                    CREATE TABLE profiles (profile_name TEXT, profile_json TEXT);
                    CREATE TABLE profile_rankings (
                        job_uid TEXT, profile_name TEXT, score INTEGER
                    );
                """)
                db.execute("INSERT INTO jobs VALUES ('j1', 'Backend Engineer', 'experiment', '2026-01-01')")
                db.execute(
                    "INSERT INTO job_artifacts VALUES ('j1', ?)",
                    (json.dumps({"description_text": (
                        "We are looking for a backend engineer. You will build Python "
                        "services with PostgreSQL and Azure, write tests, review code, "
                        "and operate reliable production APIs with the engineering team."
                    )}),),
                )
                profile = {"programming_languages": ["Python"], "tools": ["PostgreSQL", "AWS"]}
                db.execute("INSERT INTO profiles VALUES ('backend', ?)", (json.dumps(profile),))
                db.execute("INSERT INTO profile_rankings VALUES ('j1', 'backend', 88)")

            args = SimpleNamespace(
                database=database, status="experiment", profile="backend", limit=None,
                output=output,
            )
            summary = run(args)

            self.assertEqual("deterministic_python_extraction", summary["mode"])
            self.assertFalse(summary["llm_enabled"])
            self.assertFalse(summary["embeddings_enabled"])
            local = json.loads((output / "jobs/j1.local.json").read_text())
            self.assertEqual(["PostgreSQL", "Python"], local["matched_profile_technologies"])
            self.assertEqual(["Azure"], local["job_only_technologies"])
            self.assertIn("capabilities", local)
            self.assertIn("education", local)
            self.assertIn("experience", local)
            comparison = (output / "jobs/j1.comparison.md").read_text()
            self.assertIn("build Python services", comparison)
            self.assertIn("66.667", (output / "scores.csv").read_text())


if __name__ == "__main__":
    unittest.main()
