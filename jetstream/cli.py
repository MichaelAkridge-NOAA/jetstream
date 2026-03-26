"""
Command-line interface for NOAA JetStream
"""
import sys
import argparse
import uvicorn
import webbrowser
import threading
import time
import os


def open_browser(url, delay=2.0):
    """Open browser after a delay to ensure server is ready"""
    def _open():
        time.sleep(delay)
        print(f"\n🌐 Opening browser: {url}")
        webbrowser.open(url)
    
    thread = threading.Thread(target=_open, daemon=True)
    thread.start()


def main():
    """Start the JetStream server"""
    parser = argparse.ArgumentParser(
        description="NOAA JetStream - Cloud Data Manager"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't automatically open browser"
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Log level (default: info)"
    )
    
    args = parser.parse_args()
    
    print()
    print("=" * 60)
    print("  🚀 NOAA JetStream - Cloud Data Manager")
    print("  Local-to-Cloud Upload Management System")
    print("=" * 60)
    print()
    print(f"📋 Configuration:")
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Log Level: {args.log_level}")
    print()
    print(f"🌐 Web Interface: http://localhost:{args.port}")
    print(f"📚 API Documentation: http://localhost:{args.port}/docs")
    print()
    print("Press Ctrl+C to stop the server")
    print()
    
    # Open browser automatically unless disabled
    if not args.no_browser:
        url = f"http://localhost:{args.port}"
        open_browser(url, delay=2.0)
    
    # Start server
    uvicorn.run(
        "jetstream.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
