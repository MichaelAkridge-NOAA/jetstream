#!/usr/bin/env python3
"""
JetStream Diagnostic Script
"""

import sys
import os
from pathlib import Path

def print_header(title):
    """Print a section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def check_python_version():
    """Check Python version."""
    print_header("Python Version")
    version = sys.version_info
    print(f"Python {version.major}.{version.minor}.{version.micro}")
    
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print("❌ ERROR: Python 3.10+ required")
        return False
    else:
        print("✓ Python version OK")
        return True

def check_dependencies():
    """Check if all required packages can be imported."""
    print_header("Python Dependencies")
    
    # Core dependencies (absolutely required)
    core_packages = {
        'fastapi': 'FastAPI',
        'uvicorn': 'Uvicorn',
        'sqlalchemy': 'SQLAlchemy',
        'pydantic': 'Pydantic',
        'pydantic_settings': 'Pydantic Settings',
    }
    
    # Optional dependencies (nice to have, may have fallbacks)
    optional_packages = {
        'apscheduler': 'APScheduler',
    }
    
    print("Core Dependencies:")
    core_ok = True
    for module_name, display_name in core_packages.items():
        try:
            module = __import__(module_name)
            version = getattr(module, '__version__', 'unknown')
            print(f"  ✓ {display_name}: {version}")
        except ImportError as e:
            print(f"  ❌ {display_name}: NOT INSTALLED")
            print(f"     Install with: pip install {module_name}")
            core_ok = False
    
    print("\nOptional Dependencies:")
    for module_name, display_name in optional_packages.items():
        try:
            module = __import__(module_name)
            version = getattr(module, '__version__', 'unknown')
            print(f"  ✓ {display_name}: {version}")
        except ImportError as e:
            print(f"  ⚠️  {display_name}: NOT INSTALLED (scheduler features limited)")
            print(f"     Install with: pip install {module_name}")
    
    return core_ok

def check_project_structure():
    """Check if project files exist."""
    print_header("Project Structure")
    
    required_files = [
        'jetstream_api/__init__.py',
        'jetstream_api/main.py',
        'jetstream_api/config.py',
        'jetstream_api/database.py',
        'jetstream_api/scheduler.py',
        'jetstream_api/static/index.html',
        'requirements.txt',
    ]
    
    all_ok = True
    for file_path in required_files:
        path = Path(file_path)
        if path.exists():
            print(f"✓ {file_path}")
        else:
            print(f"❌ {file_path} - NOT FOUND")
            all_ok = False
    
    return all_ok

def check_imports():
    """Try to import the main app."""
    print_header("Application Import Test")
    
    try:
        from jetstream_api.main import app
        print("✓ Successfully imported FastAPI app")
        return True
    except Exception as e:
        print(f"❌ Failed to import app:")
        print(f"   {type(e).__name__}: {e}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        return False

def check_database():
    """Try to initialize database."""
    print_header("Database Initialization")
    
    try:
        from jetstream_api.database import init_db
        init_db()
        print("✓ Database initialized successfully")
        
        # Check if file was created
        if Path('jetstream.db').exists():
            size = Path('jetstream.db').stat().st_size
            print(f"✓ Database file created: jetstream.db ({size} bytes)")
        
        return True
    except Exception as e:
        print(f"❌ Database initialization failed:")
        print(f"   {type(e).__name__}: {e}")
        return False

def check_gcloud():
    """Check Google Cloud authentication."""
    print_header("Google Cloud Authentication (Optional)")
    
    import subprocess
    
    gcloud_found = False
    gsutil_found = False
    authenticated = False
    
    # Check for gcloud
    try:
        result = subprocess.run(
            ['gcloud', 'auth', 'list'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            gcloud_found = True
            print("✓ gcloud is installed")
            if 'ACTIVE' in result.stdout:
                authenticated = True
                print("✓ You are authenticated with gcloud")
                print("\nActive accounts:")
                for line in result.stdout.split('\n'):
                    if line.strip() and not line.startswith('ACTIVE') and '@' in line:
                        print(f"  {line.strip()}")
            else:
                print("⚠️  No active gcloud account")
                print("   Run: gcloud auth login --no-launch-browser")
                
    except FileNotFoundError:
        print("⚠️  gcloud not found in PATH")
    except subprocess.TimeoutExpired:
        print("⚠️  gcloud command timed out")
    
    # Check for gsutil (alternative upload tool)
    try:
        result = subprocess.run(
            ['gsutil', 'version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            gsutil_found = True
            print("✓ gsutil is installed")
            # If gsutil works, we can likely authenticate
            if not gcloud_found:
                print("   Note: gsutil found but gcloud not in PATH")
                print("   Uploads may still work using gsutil")
                
    except FileNotFoundError:
        if not gcloud_found:
            print("⚠️  gsutil not found in PATH")
    except subprocess.TimeoutExpired:
        pass
    
    # Summary
    if not gcloud_found and not gsutil_found:
        print("\n ⚠️ Note: If the app runs fine, gcloud/gsutil might be in a")
        print("         different PATH/ENV (conda env vs system vs user vs etc.)")
        print("\n⚠️  But if neither gcloud nor gsutil found in PATH(s)")
        print("   Uploads won't work until Google Cloud SDK is installed")
        print("   Install from: https://cloud.google.com/sdk/docs/install")
        return 'warning'
    elif gcloud_found and authenticated:
        return 'pass'
    elif gsutil_found:
        return 'warning'  # Works but not ideal
    else:
        return 'warning'

def check_permissions():
    """Check write permissions in current directory."""
    print_header("File System Permissions")
    
    try:
        test_file = Path('.__jetstream_test__')
        test_file.write_text('test')
        test_file.unlink()
        print("✓ Write permissions OK")
        return True
    except Exception as e:
        print(f"❌ Cannot write to current directory:")
        print(f"   {e}")
        return False

def main():
    """Run all diagnostic checks."""
    print("\n" + "="*60)
    print("  JetStream Diagnostic Tool")
    print("  Platform:", sys.platform)
    print("  Working Directory:", os.getcwd())
    print("="*60)
    
    # Critical checks (must pass for app to start)
    critical_results = {
        'Python Version': check_python_version(),
        'Dependencies': check_dependencies(),
        'Project Structure': check_project_structure(),
        'Application Import': check_imports(),
        'Database': check_database(),
        'Permissions': check_permissions(),
    }
    
    # Optional checks (warnings only)
    gcloud_status = check_gcloud()
    
    print_header("Summary")
    
    print("\nCritical Checks (required to start app):")
    for check, passed in critical_results.items():
        status = "✓ PASS" if passed else "❌ FAIL"
        print(f"  {status:10} - {check}")
    
    print("\nOptional Features:")
    if gcloud_status == 'pass':
        print(f"  ✓ PASS     - Google Cloud (uploads enabled)")
    else:
        print(f"  ⚠️  WARNING - Google Cloud may/may not work (check above)")
    
    critical_passed = all(critical_results.values())
    
    print("\n" + "="*60)
    if critical_passed:
        print("✓ JetStream can start!")
        print("\nStart the application with:")
        if sys.platform == "win32":
            print("  python -m uvicorn jetstream_api.main:app --reload")
        else:
            print("  python3 -m uvicorn jetstream_api.main:app --reload")
        
        if gcloud_status != 'pass':
            print("\n⚠️  Note: Google Cloud uploads won't work until gcloud is configured.")
            print("   The app will still run - you can configure GCS later.")
    else:
        print("❌ Critical checks failed - app cannot start.")
        print("\nPlease fix the issues above, then try again.")
        print("For help, see TROUBLESHOOTING.md")
    print("="*60 + "\n")
    
    return 0 if critical_passed else 1

if __name__ == "__main__":
    sys.exit(main())
