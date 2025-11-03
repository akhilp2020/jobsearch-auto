# Jobsearch Auto

Monorepo scaffold for job search automation services. This repository currently provides service skeletons with health check endpoints and shared libraries ready for future development.

## Storage Service

- `services/storage_svc` exposes a FastAPI app with `/write` and `/list` endpoints that proxy to the MCP filesystem server (`mcp_fs`).  
- All storage lives under `$JOBSEARCH_HOME` (defaults to `~/JobSearch`) with the enforced layout:
  ```
  ~/JobSearch/
    profile/
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
- Tests in `tests/test_storage_svc.py` swap in an in-process MCP filesystem client and verify writes, listings, and policy validation. Run them with:
  ```bash
  uv run pytest tests/test_storage_svc.py
  ```
