# ReviewVerse — Intelligent Multi-LLM Automatic Code Review

ReviewVerse is a complete web product that accepts a GitHub repository URL and generates a structured, comprehensive code review report by combining multiple model families:

- OpenAI
- Anthropic
- Groq
- Gemini
- Open-source local models (Ollama)
- Deterministic static analysis engine

The system merges perspectives into a consensus review with severity-ranked findings, actionable fixes, risk scoring, and exportable Markdown output.

## Why this is innovative

- **Multi-family consensus orchestration**: independent model perspectives reduce single-model blind spots.
- **Hybrid intelligence**: combines symbolic static analysis with generative model reasoning.
- **Action-oriented reporting**: recommendations are prioritized by severity and confidence, optimized for real engineering workflows.
- **Production-minded UX**: not a demo script—full web app with health checks, API endpoint, and downloadable report artifact.

## Product features

- GitHub repo URL input + optional branch
- Repository cloning and smart sampling of source files
- Static rules for security and maintainability
- Parallel LLM review execution
- Merged report with:
  - Executive summary
  - Overall risk score
  - Consensus findings by severity
  - Model-by-model perspective cards
  - Quick-win action plan
  - Markdown export

## Tech stack

- FastAPI backend
- Vanilla JS + Tailwind web interface
- HTTP-based provider adapters for model APIs

## Setup

1. Create and activate a Python environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment variables:

```bash
cp .env.example .env
```

Set any model keys you have available.

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`
- `GEMINI_API_KEY`
- `OLLAMA_ENDPOINT` (optional, default local)

If some providers are missing, the platform still works with available engines.

## Run

```bash
uvicorn app.main:app --reload
```

Open:

- `http://127.0.0.1:8000`

## Run with Docker

1. Create env file:

```bash
cp .env.example .env
```

2. Build and run container:

```bash
docker compose up --build
```

3. Open:

- `http://127.0.0.1:8000`

## API

### POST `/api/review`

Request body:

```json
{
  "repo_url": "https://github.com/owner/repository",
  "branch": "main"
}
```

Response includes full structured review report and `markdown_report` text.

### GET `/health`

Basic health endpoint for readiness checks.

## Notes

- This product intentionally prioritizes usability and real-world applicability over code golf.
- You can plug in additional providers (Gemini, Mistral, etc.) via the provider interface in `app/services/providers.py`.
