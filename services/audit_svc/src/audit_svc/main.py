from fastapi import FastAPI

app = FastAPI(title="Audit Service")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
