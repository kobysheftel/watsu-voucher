"""
Watsu Gift Voucher System — V1
FastAPI entry point.

Run with:
    uvicorn main:app --reload --port 8000

Then open: http://localhost:8000
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import init_db
from app.routers import holders, vouchers, reports

# --- App setup ---
app = FastAPI(
    title="Watsu Gift Voucher System",
    version="1.0.0",
    docs_url="/docs",   # Swagger UI at /docs (useful during dev)
)

# --- Static files (assets: images, CSS) ---
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# --- Serve generated voucher files (PDFs, QR images) ---
app.mount("/vouchers", StaticFiles(directory="vouchers"), name="vouchers")

# --- Register routers ---
app.include_router(holders.router)
app.include_router(vouchers.router)
app.include_router(reports.router)


# --- Startup: create DB tables + ensure folders exist ---
@app.on_event("startup")
def startup():
    init_db()


# --- Root redirect to home page ---
from fastapi.responses import RedirectResponse

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/home")
