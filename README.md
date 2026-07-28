# JobRanker

Local AI-powered job ranking and application workflow tool.

JobRanker helps you collect job postings directly from your browser, extract structured information using AI, rank opportunities against your interests, and manage your application workflow locally.

![JobRanker Screenshot](jobranker.jpg)

---

# Features

- Browser extension for capturing job postings
- AI-powered job extraction and ranking
- Local-first architecture
- Static HTML dashboard/report
- Application workflow tracking
- Resume profile support
- Queue-based background processing
- Simple setup with shell scripts

---

# Architecture

```text
Browser Extension
        ↓
FastAPI Capture API
        ↓
File Queue
        ↓
AI Extraction + Ranking Worker
        ↓
Static HTML Report
```

---

# Requirements

- Python 3.11+
- Node.js + npm
- OpenAI API key
- Linux or macOS

---

# Setup

Clone repository:

```bash
git clone https://github.com/vesapehkonen/jobranker.git
cd jobranker
```

Run setup:

```bash
./setup.sh
```

The setup script will:

- Create Python virtual environment
- Install Python dependencies
- Install and build browser extension
- Create `.env`
- Generate API token

Edit `.env` and add your OpenAI API key:

```env
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-5.4-mini
```

---

## Add Resume Profile

Resume profiles are stored in SQLite and used for AI-powered job ranking. Source resumes must be in text format (`.txt` or `.md`).

Add a resume profile using:

```bash
python extract_resume_ai.py <profile-name> <resume-file>
```

This extracts the structured profile and stores both it and the resume text in `data/jobranker.db`.

---

# Start

Run:

```bash
./start.sh
```

This will:

- Start FastAPI server
- Start worker process
- Generate report
- Open dashboard automatically

Dashboard URL:

```text
http://127.0.0.1:8000/report
```

---

# Browser Extension Setup

After running `setup.sh`:

1. Open browser extensions page
2. Enable Developer Mode
3. Click **Load unpacked**
4. Select the `extension` directory

When capturing the first job posting, the extension will ask for the API token.

Copy `API_TOKEN` from `.env` and paste it into the extension prompt.

You can now capture job postings directly from supported job sites.

---

# Development

## Build Browser Extension

```bash
cd extension
npm init -y
npm install -D typescript @types/chrome
npx tsc
```

## Backend

```bash
source .venv/bin/activate
uvicorn app:app --reload
```

## Worker

```bash
source .venv/bin/activate
python worker.py
```

---

# Project Structure

```text
jobranker/
├── app.py
├── worker.py
├── generate_report.py
├── setup.sh
├── start.sh
├── requirements.txt
├── extension/
├── queue/
├── reports/
├── templates/
└── data/
```

---

# Security Notes

- API protected using bearer token
- Backend binds to localhost by default
- No cloud storage
- Job data stays on local machine

---

# Future Ideas

- Better recommendation engine
- Resume tailoring
- Cover letter generation
- Company memory/history
- Search across captured jobs
- Better duplicate detection
- Docker support
- SQLite/Postgres backend

---

# License

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

