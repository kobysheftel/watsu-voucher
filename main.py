"""
Watsu Gift Voucher System — V1
FastAPI entry point.

Run with:
    uvicorn main:app --reload --port 8000

Then open: http://localhost:8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import init_db
from app import auth
from app.routers import holders, vouchers, reports, pages
from app.routers import auth as auth_router


# --- Ensure required directories exist ---
Path("vouchers").mkdir(exist_ok=True)
Path("config").mkdir(exist_ok=True)
Path("static").mkdir(exist_ok=True)


# --- Lifespan: replaces deprecated @app.on_event("startup") ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()   # create DB tables on startup
    yield       # app runs here


# --- Auth Middleware — protect all routes except /auth/* and static files ---
class AuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated requests to login page."""

    # Paths that don't require authentication
    PUBLIC_PREFIXES = ("/auth/", "/static/", "/assets/", "/docs", "/openapi.json")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths through
        if any(path.startswith(p) for p in self.PUBLIC_PREFIXES):
            return await call_next(request)

        # If setup not complete, redirect to setup
        if not auth.is_setup_complete():
            return RedirectResponse(url="/auth/setup", status_code=303)

        # If not authenticated, redirect to login
        if not auth.is_authenticated(request):
            return RedirectResponse(url="/auth/login", status_code=303)

        return await call_next(request)


# --- App setup ---
app = FastAPI(
    title="Watsu Gift Voucher System",
    version="1.0.0",
    docs_url="/docs",
    lifespan=lifespan,
)

# --- Add auth middleware ---
app.add_middleware(AuthMiddleware)

# --- Register routers FIRST (before mounts, to avoid /vouchers path conflict) ---
app.include_router(auth_router.router)  # auth routes — must be before other routers
app.include_router(holders.router)
app.include_router(vouchers.router)
app.include_router(reports.router)
app.include_router(pages.router)

# --- Static files ---
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
app.mount("/files",  StaticFiles(directory="vouchers"), name="voucher_files")


# --- Root redirect to home page ---
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/all-vouchers/view")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
