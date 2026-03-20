"""
JetStream API - FastAPI Cloud Data Manager
A comprehensive tool for managing local-to-cloud uploads with queue management,
statistics, and folder analysis.
"""

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

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - startup and shutdown events."""
    # Startup
    try:
        logger.info("🚀 Starting NOAA JetStream...")
        logger.info(f"   Platform: {os.name} | Python: {os.sys.version.split()[0]}")
        
        init_db()
        logger.info("✓ Database initialized")
        
        await scheduler.start()
        
        # Open browser after startup (only in main worker process)
        if settings.AUTO_OPEN_BROWSER and os.environ.get("BROWSER_OPENED") != "true":
            os.environ["BROWSER_OPENED"] = "true"
            asyncio.create_task(open_browser())
        
        logger.info(f"✓ Server ready at http://localhost:{settings.PORT}")
        logger.info(f"   Access the dashboard at: http://localhost:{settings.PORT}")
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {type(e).__name__}: {e}")
        logger.error("   Run diagnostics: python diagnose.py")
        raise
    
    yield
    
    # Shutdown
    try:
        logger.info("Shutting down...")
        await scheduler.stop()
        close_db()
        logger.info("✓ Shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

async def open_browser():
    """Open the default browser after a short delay."""
    await asyncio.sleep(2)  # Wait for server to be fully ready
    url = f"http://localhost:{settings.PORT}"
    try:
        logger.info(f"🌐 Opening browser to {url}")
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
