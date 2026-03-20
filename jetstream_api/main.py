"""
JetStream API - FastAPI Cloud Data Manager
A comprehensive tool for managing local-to-cloud uploads with queue management,
statistics, and folder analysis.
"""

import sys
import os

# Fix Windows console encoding for Unicode support (for emoji/symbols in logs)
if sys.platform == 'win32':
    try:
        import codecs
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
        os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    except:
        pass  # If encoding fix fails, ASCII symbols will be used

from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import webbrowser
import asyncio
import os
import logging

from .routers import uploads, stats, queue, folders, analytics, cloud_analyzer, settings as settings_router
from .database import init_db, close_db
from .config import settings
from .scheduler import scheduler

# Configure logging to be very verbose
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Log import success
logger.info("=" * 70)
logger.info("JetStream imports completed successfully")
logger.info("=" * 70)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - startup and shutdown events."""
    # Startup
    try:
        logger.info("=" * 70)
        logger.info(">> Starting NOAA JetStream...")
        logger.info(f"   Platform: {os.name} | Python: {os.sys.version.split()[0]}")
        logger.info(f"   Working Directory: {os.getcwd()}")
        logger.info(f"   Database Path: {os.path.abspath('jetstream.db')}")
        
        # Verify we're in the right directory
        if not os.path.exists('jetstream_api'):
            logger.error("=" * 70)
            logger.error("[ERROR] 'jetstream_api' folder not found!")
            logger.error("You must run this from the jetstream project directory.")
            logger.error(f"Current directory: {os.getcwd()}")
            logger.error("=" * 70)
            raise RuntimeError("Wrong working directory - run from jetstream folder")
        
        logger.info("=" * 70)
        
        logger.info("[1/3] Initializing database...")
        init_db()
        logger.info("[OK] Database initialized")
        
        logger.info("[2/3] Starting scheduler...")
        await scheduler.start()
        logger.info("[OK] Scheduler started")
        
        logger.info("[3/3] Preparing browser auto-launch...")
        # Open browser after startup (only in main worker process)
        if settings.AUTO_OPEN_BROWSER and os.environ.get("BROWSER_OPENED") != "true":
            os.environ["BROWSER_OPENED"] = "true"
            asyncio.create_task(open_browser())
        
        logger.info("=" * 70)
        logger.info(f"[OK] Server ready at http://localhost:{settings.PORT}")
        logger.info(f"   Access the dashboard at: http://localhost:{settings.PORT}")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error("=" * 70)
        logger.error(f"[ERROR] STARTUP FAILED: {type(e).__name__}: {e}")
        logger.error("=" * 70)
        logger.exception("Full error traceback:")
        logger.error("=" * 70)
        logger.error("   Troubleshooting:")
        logger.error("   1. Run diagnostics: python diagnose.py")
        logger.error("   2. Check write permissions in current directory")
        logger.error("   3. See TROUBLESHOOTING.md for more help")
        logger.error("=" * 70)
        # Re-raise to ensure uvicorn shows the error
        raise RuntimeError(f"JetStream startup failed: {e}") from e
    
    yield
    
    # Shutdown
    try:
        logger.info("Shutting down...")
        await scheduler.stop()
        close_db()
        logger.info("[OK] Shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

async def open_browser():
    """Open the default browser after a short delay."""
    await asyncio.sleep(2)  # Wait for server to be fully ready
    url = f"http://localhost:{settings.PORT}"
    try:
        logger.info(f"[BROWSER] Opening browser to {url}")
        webbrowser.open(url)
    except Exception as e:
        logger.warning(f"Could not auto-open browser: {e}")
        logger.info(f"   Please manually navigate to: {url}")

# Create FastAPI app
app = FastAPI(
    title="NOAA JetStream",
    description="Cloud Data Manager",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(uploads.router, prefix="/api/uploads", tags=["Uploads"])
app.include_router(stats.router, prefix="/api/stats", tags=["Statistics"])
app.include_router(queue.router, prefix="/api/queue", tags=["Queue"])
app.include_router(folders.router, prefix="/api/folders", tags=["Folders"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(cloud_analyzer.router, prefix="/api/cloud", tags=["Cloud Analyzer"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["Settings"])

# Serve static files (dashboard)
try:
    app.mount("/static", StaticFiles(directory="jetstream_api/static"), name="static")
except RuntimeError:
    pass  # Directory doesn't exist yet

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main dashboard."""
    try:
        return FileResponse("jetstream_api/static/index.html")
    except FileNotFoundError:
        return """
        <html>
            <head><title>NOAA JetStream</title></head>
            <body>
                <h1>🚀 NOAA JetStream - Cloud Data Manager</h1>
                <p>API is running. Access the interactive API docs at <a href="/docs">/docs</a></p>
                <p>Dashboard coming soon!</p>
            </body>
        </html>
        """

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "jetstream-api",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    uvicorn.run(
        "jetstream_api.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
