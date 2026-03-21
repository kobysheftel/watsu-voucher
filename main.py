"""
Watsu Gift Voucher System — V1
FastAPI entry point.

Run with:
    uvicorn main:app --reload --port 8000

Then open: http://localhost:8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import holders, vouchers, reports, pages


# --- Ensure required directories exist ---
Path("vouchers").mkdir(exist_ok=True)
Path("config").mkdir(exist_ok=True)
Path("static").mkdir(exist_ok=True)


# --- Lifespan: replaces deprecated @app.on_event("startup") ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()   # create DB tables on startup
    yield       # app runs here


# --- App setup ---
app = FastAPI(
    title="Watsu Gift Voucher System",
    version="1.0.0",
    docs_url="/docs",
    lifespan=lifespan,
)

# --- Register routers FIRST (before mounts, to avoid /vouchers path conflict) ---
app.include_router(holders.router)
app.include_router(vouchers.router)
app.include_router(reports.router)
app.include_router(pages.router)

# --- Static files ---
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
app.mount("/files",  StaticFiles(directory="vouchers"), name="voucher_files")


# --- Root redirect to home page ---
from fastapi.responses import RedirectResponse

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/all-vouchers/view")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
