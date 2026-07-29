from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

JOB_EXTRACT_MODEL = os.environ.get(
    "OPENAI_JOB_EXTRACT_MODEL", "gpt-5.4-nano"
)
JOB_RANK_MODEL = os.environ.get(
    "OPENAI_JOB_RANK_MODEL", "gpt-5.4-mini"
)
RESUME_EXTRACT_MODEL = os.environ.get(
    "OPENAI_RESUME_EXTRACT_MODEL", "gpt-5.4-mini"
)
