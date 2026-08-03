# AI Adaptive Learning and Assessment System

An AI powered adaptive quiz platform. Upload study material (PDF, DOCX, PPTX, TXT, or images), and the system automatically generates a personalized quiz whose difficulty adjusts in real time based on your performance, tracks weak topics, and produces a downloadable PDF report with topic level feedback, all on a single page with no reloads.

Built with Flask, Supabase (Postgres), and the Groq API (Llama 3.3 70B).

**AWS domain**: ai-quiz.eu-north-1.elasticbeanstalk.com

**Live Demo:** [http://13.62.177.170](http://13.62.177.170)

*(Note: the AWS domain may fail to resolve on some ISPs/DNS resolvers so use the direct IP link above if the domain doesn't load.)*

## Table of Contents

Features, Tech Stack, Architecture, Project Structure, How the Adaptive Difficulty Works, Setup and Installation, Environment Variables, Running Locally, Deploying to AWS Elastic Beanstalk, API Routes, Database Schema, Security Notes, Known Limitations, License

## Features

* **Multi format study material upload**: paste text directly, or upload PDF, DOCX, PPTX, TXT, or images (OCR)
* **AI generated questions**: Groq (Llama 3.3 70B) automatically detects topics from the material and generates easy, medium, or hard MCQ or fill in the blank questions, each with an explanation and a source quote from the original material
* **Adaptive difficulty**: every correct answer escalates difficulty (easy to medium to hard); every wrong answer lowers it, so the quiz continuously matches the student's level
* **Single page quiz experience**: no page reloads between questions; answers, feedback, and the next question are all handled via AJAX
* **Weak topic tracking**: the system records which topics you get wrong most often
* **Practice Weak Areas**: generates a brand new, targeted quiz using only your weak topics
* **PDF report generation**: a downloadable report with accuracy stats, topic mastery levels, AI generated learning summaries for weak topics, full question history, and recommendations
* **8 construct evaluation questionnaire**: a Likert scale (Strongly Agree to Strongly Disagree) feedback form covering learning gain, adaptive difficulty accuracy, feedback quality, weak topic remediation, AI content trustworthiness, engagement, usability, and overall preference, stored in the database for research and analysis purposes
* **Retake quiz**: resets progress and lets you try the same question pool again

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask, Flask SQLAlchemy |
| Database | PostgreSQL (Supabase), via `psycopg` v3 |
| AI | Groq API (`llama 3.3 70b versatile`) |
| File extraction | PyMuPDF (PDF), python docx (DOCX), python pptx (PPTX), pytesseract plus OpenCV (image OCR) |
| PDF report generation | fpdf2 |
| Frontend | Server rendered Jinja2 templates plus vanilla JavaScript (Fetch API) plus Bootstrap 5 |
| Deployment | Docker container on AWS Elastic Beanstalk (single instance, Amazon Linux 2023) |

No frontend framework (no React or Vue). The quiz page is one Jinja2 template with three cards (quiz, results, questionnaire) toggled by plain JavaScript.

## Architecture

A full activity diagram breakdown of every feature, showing which function calls which and in what order for both backend and frontend, is in [`architecture_diagrams.html`](architecture_diagrams.html). Open it in a browser to see the rendered flowcharts (Mermaid.js) for:

1. Upload and Question Generation
2. Quiz Page Load
3. Answer Submission (the adaptive step)
4. Next Question and Finish Quiz
5. Practice Weak Areas
6. Retake Quiz
7. Questionnaire Submission
8. PDF Report Download
9. Frontend component visibility (which card is shown or hidden and why)
10. Deployment flow (Docker build to Elastic Beanstalk to Nginx proxy to app)

## Project Structure

```
AIQuizSystem/
├── app.py                     Flask app factory, DB init, auto migration
├── config.py                  Configuration (env vars, DB URL normalization)
├── architecture_diagrams.html Mermaid activity diagrams for every feature
├── Dockerfile                 Container definition (used for AWS EB deployment)
├── Procfile                   Gunicorn start command
├── .platform/
│   └── nginx/conf.d/
│       └── uploads.conf       Raises Nginx upload limit (client_max_body_size) on EB
├── requirements.txt
├── .env.example                Template, copy to .env and fill in real values
├── .gitignore
│
├── models/
│   ├── __init__.py            db = SQLAlchemy()
│   └── models.py               LearningSession, Question, QuizState,
│                               QuizAttempt, Questionnaire
│
├── routes/
│   ├── __init__.py
│   └── main.py                 All Flask routes (upload, quiz, submit, next,
│                               retake, weak, download, questionnaire)
│
├── services/
│   ├── ai_service.py           Groq calls: generate_questions(), generate_summary()
│   ├── adaptive_service.py     Difficulty ladder plus internal Elo research metric
│   ├── file_service.py         PDF, DOCX, PPTX, TXT, image text extraction
│   └── report_service.py       PDF report generation (fpdf2)
│
├── templates/
│   ├── base.html
│   ├── home.html
│   ├── upload.html
│   └── quiz.html               Single page quiz plus results plus questionnaire
│
└── static/
    ├── css/style.css           Design tokens and color palette
    └── js/quiz.js              All AJAX logic (fetch calls, DOM updates)
```

## How the Adaptive Difficulty Works

**What the student sees and what actually drives question selection** is a simple, deterministic ladder:

```
correct answer  to  escalate one level    (easy to medium to hard)
wrong answer    to  step down one level   (hard to medium to easy)
```

`QuizState.current_difficulty` is always exactly `"easy"`, `"medium"`, or `"hard"`, and is updated directly after every answer. There is no hidden formula between an answer and what the student sees next.

**Underneath, in parallel, the system also maintains an Elo style ability rating** (per student and per topic), inspired by the same rating system used in chess and by adaptive testing research (cf. Pelánek, 2016; a similar idea underlies Duolingo's exercise difficulty model):

```
Expected(correct) = 1 / (1 + 10^((Q_elo - S_elo) / 400))
S_elo_new = S_elo + K_student * (actual - expected)
Q_elo_new = Q_elo - K_question * (actual - expected)
```

This Elo layer is **not** used to pick the next question or shown anywhere in the live quiz UI (a raw number like "1327" isn't meaningful to a student without training in psychometrics). It exists purely as a finer grained research and reporting metric. It powers the **Topic Mastery** section of the PDF report, converted into a human readable percentage and label (for example "Developing (52%)").

## Setup and Installation

### Prerequisites

* Python 3.10 or newer (3.12 or 3.13 recommended)
* A [Supabase](https://supabase.com) project (free tier is enough) for Postgres
* A [Groq](https://console.groq.com) API key

### Install

```bash
git clone https://github.com/yourusername/yourrepo.git
cd yourrepo

python -m venv venv
source venv/bin/activate       (Windows: venv\Scripts\activate)

pip install -r requirements.txt
```

## Environment Variables

Copy the example file and fill in real values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `SECRET_KEY` | Random string for Flask session signing. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | Supabase Postgres connection string, for example `postgresql://postgres:<password>@<host>:5432/postgres` |
| `GROQ_API_KEY` | From [console.groq.com](https://console.groq.com), under API Keys |

**Never commit `.env` to Git.** It is already listed in `.gitignore`. If you ever accidentally commit real credentials, rotate them immediately (regenerate the Groq key, reset the Supabase database password). Removing the file from a later commit does not remove it from Git history.

## Running Locally

```bash
python app.py
```

Visit `http://localhost:5000`. On first run, `app.py` automatically:
1. Creates any missing database tables (`db.create_all()`)
2. Adds any missing columns to tables that already existed, if the schema has changed since they were created (a lightweight auto migration safety net, see the comments in `app.py` for why this exists instead of a full migrations framework)

If `DATABASE_URL` isn't set, the app falls back to a local SQLite file at `instance/quiz.db` so it still boots for quick testing.

## Deploying to AWS Elastic Beanstalk

This project is deployed as a **single container Docker application** on AWS Elastic Beanstalk.

1. Package the project as a `.zip` using Unix style forward slash paths. A zip created on Windows via "Send to, Compressed folder" uses backslash paths and will fail to extract on the Linux instance
2. Upload the `.zip` via the EB console (**Upload and deploy**) or the EB CLI (`eb deploy`)
3. Set environment variables under **Configuration, Updates monitoring and logging, Environment properties** (`DATABASE_URL`, `GROQ_API_KEY`, `SECRET_KEY`), or better, reference them from **AWS Systems Manager Parameter Store** (as `SecureString` values) instead of plain text
4. The `Dockerfile` must include an `EXPOSE` directive matching the port Gunicorn binds to. EB's Docker platform needs this to know which port to forward traffic to
5. `.platform/nginx/conf.d/uploads.conf` raises Nginx's default 1MB upload limit (`client_max_body_size`) so larger PDF or DOCX uploads aren't rejected before reaching the app

**Instance sizing:** the app's dependencies (OpenCV, scikit learn, PyMuPDF) are memory heavy. A `t3.micro` (1GB RAM) can struggle under concurrent load. `t3.small` (2GB RAM) is recommended even for light traffic.

## API Routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Landing page |
| `/upload` | GET, POST | Upload form or process upload and generate questions |
| `/quiz/<session_id>` | GET | Load the quiz page (renders the first or current question) |
| `/submit/<session_id>` | POST | Grade an answer, update adaptive difficulty and weak topics |
| `/next/<session_id>` | POST | Advance to the next question, or return final results |
| `/retake/<session_id>` | POST | Reset quiz state and start over with the same questions |
| `/weak/<session_id>` | POST | Generate new AI questions from weak topics only |
| `/download/<session_id>` | GET | Generate and download the PDF report |
| `/questionnaire/<session_id>` | POST | Save the 8 question evaluation questionnaire |
| `/health` | GET | Simple health check endpoint |

## Database Schema

| Table | Purpose |
|---|---|
| `learning_sessions` | One row per upload: education level, question type, extracted study text |
| `questions` | AI generated questions, difficulty, topic, correct answer, explanation, source quote, plus internal Elo rating |
| `quiz_states` | Per session progress: current question, difficulty, correct and wrong counts, used questions, weak topics, Elo ratings |
| `quiz_attempts` | One row per answered question (for the PDF report's question history) |
| `questionnaires` | One row per submitted evaluation questionnaire (8 Likert responses plus comments) |

## Security Notes

* `.env` is gitignored. Real credentials should never be committed
* If credentials are ever exposed (for example pasted into a chat, committed by mistake, or shown in an AWS console screenshot), **rotate them immediately** rather than relying solely on removing them from the repo. Git history retains old commits unless explicitly rewritten (for example with the BFG Repo Cleaner)
* In production, set all secrets via your hosting platform's environment variable settings, ideally backed by **AWS Systems Manager Parameter Store** (SecureString) or **Secrets Manager** rather than plain text environment properties
* Recommend keeping the GitHub repository **private** given it's a student or research project with a live database connection

## Known Limitations

* The Elo based mastery metric is a reporting and research layer, not a peer reviewed psychometric model. Treat the PDF report's "Topic Mastery" percentages as an approximate signal, not a validated measurement
* AI generated topic names aren't normalized. The same underlying topic can occasionally be labeled slightly differently across questions (for example "Artificial Intelligence" versus "Machine Perception"), which can fragment weak topic tracking
* No authentication or user accounts. Anyone with a session URL can access that session's quiz
* Image OCR requires the `tesseract ocr` system package, bundled into the Docker image for deployment
* Single instance deployment (no auto scaling or load balancer redundancy). Sufficient for light traffic (a handful of concurrent users) but not resilient to instance failure
