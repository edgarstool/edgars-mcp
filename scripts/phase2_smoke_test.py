"""Phase 2.0 smoke test: minimal FastAPI app to verify uvicorn + fastapi + fastmcp co-existence."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok", "phase": "2.0-smoke"}


if __name__ == "__main__":
    # Verify fastmcp can be imported alongside fastapi
    import fastmcp
    print(f"fastapi + fastmcp import OK (fastmcp version: {fastmcp.__version__})")
