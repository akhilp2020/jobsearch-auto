# Jobsearch Auto

End-to-end job search automation pipeline that finds jobs, ranks them by fit, generates tailored application materials (CVs, cover letters, supplementals), validates them against profile guardrails, and creates a review dashboard.

## Storage Service

- `services/storage_svc` exposes a FastAPI app with `/write` and `/list` endpoints that proxy to the MCP filesystem server (`mcp_fs`).  
- All storage lives under `$JOBSEARCH_HOME` (defaults to `~/JobSearch`) with the enforced layout:
  ```
  ~/JobSearch/
    profile/
      canonical_profile.json
      profile_history.jsonl
    jobs/{company}_{title}_{jobId}/
    logs/
    exports/
  ```
  Write operations must target files inside these top-level folders. Job directories require a trailing numeric job ID.
- The service calls the new reusable client in `libs/mcp_clients`, which wraps MCP stdio servers and raises `MCPClientError` when a tool invocation fails.
- To run the service locally:
  ```bash
  export JOBSEARCH_HOME=${JOBSEARCH_HOME:-$HOME/JobSearch}
  uv run --project services/storage_svc uvicorn storage_svc.main:app --host 0.0.0.0 --port 8000
  ```
  Example write call:
  ```bash
  curl -X POST "http://localhost:8000/write" \
    -H "Content-Type: application/json" \
    -d '{"path":"exports/test.txt","content":"ok","kind":"text"}'
  ```
- `POST /ingest-cv` extracts structured resume data using both heuristics and the configured LLM, storing a canonical profile JSON at `profile/canonical_profile.json`.
- `GET /profile` returns the latest canonical profile; `POST /clarify` surfaces targeted follow-up questions (salary target, relocation, visa, remote %, industries, seniority, target titles); `POST /clarify/answers` merges the responses into the canonical profile and appends a diff entry to `profile/profile_history.jsonl`.
- Tests in `tests/test_storage_svc.py` swap in an in-process MCP filesystem client and verify writes, listings, CV ingestion, clarification flows, and policy validation. Run them with:
  ```bash
  uv run pytest tests/test_storage_svc.py
  ```

## Job Finder Service

- `services/job_finder_svc` searches for job postings across multiple ATS platforms (Greenhouse, Lever, Workday).
- `POST /search` accepts search filters (titles, locations, remote, salary_min) and returns normalized job postings from all sources.
- Implements rate limiting and robots.txt checking to respect external APIs.
- Deduplicates results by apply_url and saves up to 10 jobs to storage automatically.
- To run the service:
  ```bash
  JOBSEARCH_HOME="$HOME/JobSearch" \
  STORAGE_SERVICE_HOST=localhost \
  STORAGE_SERVICE_PORT=8000 \
  uv run --project services/job_finder_svc uvicorn job_finder_svc.main:app --host 0.0.0.0 --port 9000
  ```
  Example search:
  ```bash
  curl -X POST http://localhost:9000/search \
    -H "Content-Type: application/json" \
    -d '{"titles":["Engineering Manager"],"locations":["Remote"]}'
  ```

## Job Ranker Service

- `services/job_ranker_svc` uses LLM-based scoring to rank job postings against a candidate profile.
- `POST /rank` accepts a profile and list of jobs, returns ranked results with fit scores (0-100).
- Generates detailed fit analysis including matched skills, gaps, seniority match, and explanation.
- Automatically saves fit reports for top 10 jobs to `jobs/{company}_{title}_{id}/fit_report.json`.
- To run the service:
  ```bash
  JOBSEARCH_HOME="$HOME/JobSearch" \
  STORAGE_SERVICE_HOST=localhost \
  STORAGE_SERVICE_PORT=8000 \
  LLM_PROVIDER=openai \
  LLM_MODEL=gpt-4o-mini \
  LLM_API_KEY="your-api-key" \
  uv run --project services/job_ranker_svc uvicorn job_ranker_svc.main:app --host 0.0.0.0 --port 9001
  ```

## CV Builder Service

- `services/cv_builder_svc` generates tailored CVs for specific job applications.
- `POST /tailor-cv` accepts a job_id and generates markdown, HTML, and PDF versions of a tailored CV.
- Uses LLM to select relevant experience, skills, and achievements from the canonical profile.
- Embeds evidence comments (e.g., `<!-- evidence:skills[0] -->`) linking each bullet to profile data.
- `POST /validate` validates CV artifacts against profile guardrails.
- To run the service:
  ```bash
  JOBSEARCH_HOME="$HOME/JobSearch" \
  STORAGE_SERVICE_HOST=localhost \
  STORAGE_SERVICE_PORT=8000 \
  LLM_PROVIDER=openai \
  LLM_MODEL=gpt-4o-mini \
  LLM_API_KEY="your-api-key" \
  uv run --project services/cv_builder_svc uvicorn cv_builder_svc.main:app --host 0.0.0.0 --port 9002
  ```

## Document Builder Service

- `services/doc_builder_svc` generates cover letters and supplemental documents.
- `POST /cover-letter` generates a cover letter with configurable tone (default: "concise, impact-focused").
- `POST /supplementals` answers a list of application questions with optional word limits.
- All documents include evidence comments and are saved as markdown, HTML, and PDF with timestamps.
- `POST /validate` validates all artifacts against profile guardrails.
- To run the service:
  ```bash
  JOBSEARCH_HOME="$HOME/JobSearch" \
  STORAGE_SERVICE_HOST=localhost \
  STORAGE_SERVICE_PORT=8000 \
  LLM_PROVIDER=openai \
  LLM_MODEL=gpt-4o-mini \
  LLM_API_KEY="your-api-key" \
  uv run --project services/doc_builder_svc uvicorn doc_builder_svc.main:app --host 0.0.0.0 --port 9003
  ```
  Example cover letter generation:
  ```bash
  curl -X POST http://localhost:9003/cover-letter \
    -H "Content-Type: application/json" \
    -d '{"job_id":"gh_airbnb_7271799","tone":"enthusiastic"}'
  ```

## Orchestrator Service

- `services/orchestrator` coordinates the entire job application pipeline.
- `POST /prepare` orchestrates end-to-end preparation:
  1. Searches for jobs using job_finder_svc
  2. Ranks all results using job_ranker_svc
  3. Selects top N jobs (configurable, default 5)
  4. For each job:
     - Generates tailored CV via cv_builder_svc
     - Generates cover letter via doc_builder_svc (optional)
     - Generates supplemental answers via doc_builder_svc (optional)
  5. Runs guardrails validation on all artifacts
  6. Creates `review_dashboard.json` with all results
- To run the service:
  ```bash
  JOBSEARCH_HOME="$HOME/JobSearch" \
  STORAGE_SERVICE_HOST=localhost \
  STORAGE_SERVICE_PORT=8000 \
  JOB_FINDER_SERVICE_HOST=localhost \
  JOB_FINDER_SERVICE_PORT=9000 \
  JOB_RANKER_SERVICE_HOST=localhost \
  JOB_RANKER_SERVICE_PORT=9001 \
  CV_BUILDER_SERVICE_HOST=localhost \
  CV_BUILDER_SERVICE_PORT=9002 \
  DOC_BUILDER_SERVICE_HOST=localhost \
  DOC_BUILDER_SERVICE_PORT=9003 \
  LLM_PROVIDER=openai \
  LLM_MODEL=gpt-4o-mini \
  LLM_API_KEY="your-api-key" \
  uv run --project services/orchestrator uvicorn orchestrator.main:app --host 0.0.0.0 --port 9004
  ```
  Example preparation:
  ```bash
  curl -X POST http://localhost:9004/prepare \
    -H "Content-Type: application/json" \
    -d '{
      "titles":["Engineering Manager","Product Manager"],
      "locations":["San Francisco","Remote"],
      "top_n":3,
      "generate_cover_letter":true,
      "cover_letter_tone":"concise, impact-focused"
    }'
  ```
  Response includes:
  ```json
  {
    "dashboard_path": "/Users/you/JobSearch/review_dashboard.json",
    "jobs_prepared": 3,
    "jobs": [
      {
        "job_id": "gh_company_12345",
        "job_title": "Engineering Manager",
        "company": "Example Corp",
        "fit_score": 85,
        "cv_pdf_path": "/path/to/cv_20241103T120000Z.pdf",
        "cover_letter_pdf_path": "/path/to/cover_20241103T120000Z.pdf",
        "validation_passed": true,
        "validation_violations": 0
      }
    ],
    "total_violations": 0
  }
  ```

## Guardrails Library

- `libs/guardrails` provides validation rules to ensure generated artifacts remain truthful to the profile.
- Three validation rules:
  1. **Evidence Tracing**: Every content bullet must have an evidence comment mapping to a real profile entry
  2. **Unverified Skills Ban**: No skills or technologies not present in the canonical profile
  3. **Date/Title Mismatch Detection**: Job titles and dates must match profile roles exactly
- Used by both cv_builder_svc and doc_builder_svc validation endpoints.
- Example validation:
  ```python
  from guardrails import validate_artifacts

  result = validate_artifacts(
      profile_path="profile/canonical_profile.json",
      artifact_paths=["jobs/Company_Title_123/cv_20241103.html"]
  )
  print(f"Passed: {result.passed}")
  for violation in result.violations:
      print(f"Line {violation.line}: {violation.reason}")
  ```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Orchestrator Service                    │
│                         (port 9004)                         │
└────────────┬────────────────────────────────────────────────┘
             │
    ┌────────┼────────┬───────────┬──────────────┐
    │        │        │           │              │
    ▼        ▼        ▼           ▼              ▼
┌─────┐  ┌─────┐  ┌─────┐    ┌─────┐        ┌─────┐
│Job  │  │Job  │  │CV   │    │Doc  │        │Stor-│
│Find-│  │Rank-│  │Build│    │Build│        │age  │
│er   │  │er   │  │er   │    │er   │        │Svc  │
│9000 │  │9001 │  │9002 │    │9003 │        │8000 │
└─────┘  └─────┘  └─────┘    └─────┘        └─────┘
                     │           │              │
                     └───────────┴──────────────┘
                                 │
                          ┌──────▼──────┐
                          │ Guardrails  │
                          │   Library   │
                          └─────────────┘
```

## File Naming Conventions

All generated artifacts use ISO 8601 timestamps:
- CVs: `cv_20241103T120000Z.{md,html,pdf}`
- Cover letters: `cover_20241103T120000Z.{md,html,pdf}`
- Supplementals: `supplemental_20241103T120000Z.{md,html,pdf}`
- Fit reports: `fit_report.json`

## Evidence Comments

All generated HTML includes evidence comments linking content to profile data:
```html
<!-- evidence:skills[2] -->
<li>Led implementation of distributed systems using Python and Go</li>

<!-- evidence:roles[0].achievements[1] -->
<li>Increased team velocity by 40% through CI/CD improvements</li>
```

These are validated by the guardrails library to prevent hallucinations.
