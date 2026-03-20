"""
JetStream Startup Wrapper with Enhanced Error Reporting
Run this instead of uvicorn to see detailed startup errors.
"""

import sys
import os
import traceback
import logging
import platform

# Fix Windows console encoding for Unicode support
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    os.environ['PYTHONIOENCODING'] = 'utf-8'

# Configure logging FIRST
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('jetstream_startup.log')
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Start JetStream with detailed error reporting."""
    
    print("\n" + "="*70)
    print("  JetStream Startup - Enhanced Diagnostics")
    print("="*70 + "\n")
    
    # Step 1: Check working directory
    logger.info(f"Working Directory: {os.getcwd()}")
    logger.info(f"Python Version: {sys.version}")
    logger.info(f"Platform: {sys.platform} ({platform.machine()}, {platform.architecture()[0]})")
    
    # Step 2: Test imports one by one
    print("\n[1/6] Testing core imports...")
    try:
        import fastapi
        logger.info(f"[OK] FastAPI {fastapi.__version__}")
    except Exception as e:
        logger.error(f"[FAIL] FastAPI import failed: {e}")
        traceback.print_exc()
        return 1
    
    try:
        import uvicorn
        logger.info(f"[OK] Uvicorn {uvicorn.__version__}")
    except Exception as e:
        logger.error(f"[FAIL] Uvicorn import failed: {e}")
        traceback.print_exc()
        return 1
    
    try:
        import sqlalchemy
        logger.info(f"[OK] SQLAlchemy {sqlalchemy.__version__}")
    except Exception as e:
        logger.error(f"[FAIL] SQLAlchemy import failed: {e}")
        traceback.print_exc()
        return 1
    
    # Step 3: Test config import
    print("\n[2/6] Loading configuration...")
    try:
        from jetstream_api.config import settings
        logger.info(f"[OK] Config loaded")
        logger.info(f"  - Host: {settings.HOST}")
        logger.info(f"  - Port: {settings.PORT}")
        logger.info(f"  - Database: {settings.DATABASE_URL}")
    except Exception as e:
        logger.error(f"[FAIL] Config import failed: {e}")
        traceback.print_exc()
        return 1
    
    # Step 4: Test database module import
    print("\n[3/6] Testing database module...")
    try:
        from jetstream_api import database
        logger.info(f"[OK] Database module imported")
    except Exception as e:
        logger.error(f"[FAIL] Database module import failed: {e}")
        traceback.print_exc()
        return 1
    
    # Step 5: Test database initialization
    print("\n[4/6] Initializing database...")
    try:
        from jetstream_api.database import init_db
        init_db()
        logger.info(f"[OK] Database initialized")
        
        # Check if file was created
        if os.path.exists('jetstream.db'):
            size = os.path.getsize('jetstream.db')
            logger.info(f"[OK] Database file exists: jetstream.db ({size} bytes)")
        else:
            logger.warning(f"[WARN] Database file not found at: {os.path.abspath('jetstream.db')}")
            
    except Exception as e:
        logger.error(f"[FAIL] Database initialization failed: {e}")
        traceback.print_exc()
        logger.error("\nDatabase Error Details:")
        logger.error(f"  - Attempted location: {os.path.abspath('jetstream.db')}")
        logger.error(f"  - Current directory: {os.getcwd()}")
        logger.error(f"  - Write permissions: {os.access('.', os.W_OK)}")
        return 1
    
    # Step 6: Test full app import
    print("\n[5/6] Importing FastAPI application...")
    try:
        from jetstream_api.main import app
        logger.info(f"[OK] FastAPI app imported successfully")
    except Exception as e:
        logger.error(f"[FAIL] App import failed: {e}")
        traceback.print_exc()
        return 1
    
    # Step 7: Start uvicorn
    print("\n[6/6] Starting Uvicorn server...")
    print("="*70)
    print("  If the server starts successfully, you should see:")
    print("  - 'Application startup complete.'")
    print("  - Browser should auto-open (if enabled)")
    print("  - You should be able to access http://localhost:8000")
    print("="*70 + "\n")
    
    try:
        import uvicorn
        uvicorn.run(
            "jetstream_api.main:app",
            host=settings.HOST,
            port=settings.PORT,
            reload=False,  # Disabled for cleaner diagnostic output
            log_level="debug",
            access_log=True
        )
    except Exception as e:
        logger.error(f"[FAIL] Uvicorn failed to start: {e}")
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nShutdown requested by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"CRITICAL ERROR: {e}")
        traceback.print_exc()
        
        print("\n" + "="*70)
        print("  STARTUP FAILED - See jetstream_startup.log for full details")
        print("="*70)
        
        sys.exit(1)
