from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
