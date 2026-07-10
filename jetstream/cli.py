"""
Command-line interface for NOAA JetStream
"""
import sys
import argparse
import json
from urllib import error, parse, request
import uvicorn
import webbrowser
import threading
import time
import os
from pathlib import Path


def open_browser(url, delay=2.0):
    """Open browser after a delay to ensure server is ready"""
    def _open():
        time.sleep(delay)
        print(f"\n🌐 Opening browser: {url}")
        webbrowser.open(url)
    
    thread = threading.Thread(target=_open, daemon=True)
    thread.start()


def _request_json(method: str, url: str, payload: dict | None = None) -> dict:
    """Perform a JSON HTTP request against JetStream API."""
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def _format_server_url(server_url: str) -> str:
    return server_url.rstrip("/")


def handle_cloud_audit_start(args) -> int:
    """Start a cloud audit scan in the background."""
    server_url = _format_server_url(args.server_url)
    payload = {
        "bucket_name": args.bucket,
        "prefix": args.prefix,
        "max_objects": args.max_objects,
        "junk_regex_patterns": args.patterns if args.patterns else None,
        "dry_run": args.dry_run,
    }
    response = _request_json("POST", f"{server_url}/api/cloud-audit/scan/start", payload)
    print(json.dumps(response, indent=2))
    return 0


def handle_cloud_audit_runs(args) -> int:
    """List recent cloud audit runs."""
    server_url = _format_server_url(args.server_url)
    query = parse.urlencode({"limit": args.limit})
    response = _request_json("GET", f"{server_url}/api/cloud-audit/runs?{query}")
    print(json.dumps(response, indent=2))
    return 0


def handle_cloud_audit_findings(args) -> int:
    """List findings for a run."""
    server_url = _format_server_url(args.server_url)
    params = {
        "skip": args.skip,
        "limit": args.limit,
    }
    if args.status:
        params["action_status"] = args.status
    query = parse.urlencode(params)
    response = _request_json("GET", f"{server_url}/api/cloud-audit/runs/{args.run_id}/findings?{query}")
    print(json.dumps(response, indent=2))
    return 0


def handle_cloud_audit_summary(args) -> int:
    """Get aggregate summary for an audit run."""
    server_url = _format_server_url(args.server_url)
    response = _request_json("GET", f"{server_url}/api/cloud-audit/runs/{args.run_id}/summary")
    print(json.dumps(response, indent=2))
    return 0


def handle_cloud_audit_cancel(args) -> int:
    """Request cancellation for an in-flight audit run."""
    server_url = _format_server_url(args.server_url)
    response = _request_json("POST", f"{server_url}/api/cloud-audit/runs/{args.run_id}/cancel", {})
    print(json.dumps(response, indent=2))
    return 0


def handle_cloud_audit_quarantine(args) -> int:
    """Execute quarantine operation for a run."""
    server_url = _format_server_url(args.server_url)
    payload = {
        "confirm_text": args.confirm_text,
        "quarantine_bucket": args.quarantine_bucket,
        "quarantine_prefix": args.quarantine_prefix,
        "dry_run": args.dry_run,
        "limit": args.limit,
    }
    response = _request_json("POST", f"{server_url}/api/cloud-audit/runs/{args.run_id}/quarantine", payload)
    print(json.dumps(response, indent=2))
    return 0


def handle_cloud_audit_manifest(args) -> int:
    """Get findings manifest URL response for the selected run."""
    server_url = _format_server_url(args.server_url)
    params = {"format": args.format}
    if args.status:
        params["action_status"] = args.status
    query = parse.urlencode(params)
    url = f"{server_url}/api/cloud-audit/runs/{args.run_id}/manifest?{query}"
    # Stream raw bytes so the command can be redirected to a file.
    req = request.Request(url, headers={"Accept": "*/*"}, method="GET")
    try:
        with request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            sys.stdout.buffer.write(body)
            return 0
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def main():
    """Start the JetStream server"""
    parser = argparse.ArgumentParser(
        description="NOAA JetStream - Cloud Data Manager"
    )
    subparsers = parser.add_subparsers(dest="command")

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

    audit_start = subparsers.add_parser("cloud-audit-start", help="Start a background cloud audit scan")
    audit_start.add_argument("--bucket", required=True, help="Bucket to scan")
    audit_start.add_argument("--prefix", default="", help="Prefix filter for object names")
    audit_start.add_argument("--max-objects", type=int, default=0, help="Override scan object cap")
    audit_start.add_argument("--pattern", dest="patterns", action="append", help="Junk regex pattern (repeatable)")
    audit_start.add_argument("--server-url", default="http://localhost:8000", help="JetStream server base URL")
    audit_start.add_argument("--dry-run", action="store_true", default=False, help="Record dry-run intent on run metadata")
    audit_start.set_defaults(func=handle_cloud_audit_start)

    audit_runs = subparsers.add_parser("cloud-audit-runs", help="List recent cloud audit runs")
    audit_runs.add_argument("--limit", type=int, default=20, help="Maximum runs to list")
    audit_runs.add_argument("--server-url", default="http://localhost:8000", help="JetStream server base URL")
    audit_runs.set_defaults(func=handle_cloud_audit_runs)

    audit_findings = subparsers.add_parser("cloud-audit-findings", help="List findings for a run")
    audit_findings.add_argument("--run-id", required=True, help="Audit run ID")
    audit_findings.add_argument("--status", default=None, help="Optional action_status filter")
    audit_findings.add_argument("--skip", type=int, default=0, help="Records to skip")
    audit_findings.add_argument("--limit", type=int, default=100, help="Maximum records to return")
    audit_findings.add_argument("--server-url", default="http://localhost:8000", help="JetStream server base URL")
    audit_findings.set_defaults(func=handle_cloud_audit_findings)

    audit_summary = subparsers.add_parser("cloud-audit-summary", help="Get aggregate summary for a run")
    audit_summary.add_argument("--run-id", required=True, help="Audit run ID")
    audit_summary.add_argument("--server-url", default="http://localhost:8000", help="JetStream server base URL")
    audit_summary.set_defaults(func=handle_cloud_audit_summary)

    audit_cancel = subparsers.add_parser("cloud-audit-cancel", help="Request cancellation for a running run")
    audit_cancel.add_argument("--run-id", required=True, help="Audit run ID")
    audit_cancel.add_argument("--server-url", default="http://localhost:8000", help="JetStream server base URL")
    audit_cancel.set_defaults(func=handle_cloud_audit_cancel)

    audit_quarantine = subparsers.add_parser("cloud-audit-quarantine", help="Execute quarantine move for pending findings")
    audit_quarantine.add_argument("--run-id", required=True, help="Audit run ID")
    audit_quarantine.add_argument("--confirm-text", default="MOVE_TO_QUARANTINE", help="Required confirmation text")
    audit_quarantine.add_argument("--quarantine-bucket", default=None, help="Optional quarantine bucket override")
    audit_quarantine.add_argument("--quarantine-prefix", default="quarantine", help="Destination prefix")
    audit_quarantine.add_argument("--limit", type=int, default=500, help="Maximum findings to process")
    audit_quarantine.add_argument("--dry-run", action="store_true", default=False, help="Preview only")
    audit_quarantine.add_argument("--server-url", default="http://localhost:8000", help="JetStream server base URL")
    audit_quarantine.set_defaults(func=handle_cloud_audit_quarantine)

    audit_manifest = subparsers.add_parser("cloud-audit-manifest", help="Export findings manifest for a run")
    audit_manifest.add_argument("--run-id", required=True, help="Audit run ID")
    audit_manifest.add_argument("--format", choices=["csv", "jsonl"], default="csv", help="Manifest output format")
    audit_manifest.add_argument("--status", default=None, help="Optional action_status filter")
    audit_manifest.add_argument("--server-url", default="http://localhost:8000", help="JetStream server base URL")
    audit_manifest.set_defaults(func=handle_cloud_audit_manifest)
    
    args = parser.parse_args()

    if getattr(args, "func", None):
        try:
            return args.func(args)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    
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
    
    # Open browser automatically unless disabled.
    # Also set BROWSER_OPENED so the lifespan in main.py doesn't open a second tab.
    if not args.no_browser:
        url = f"http://localhost:{args.port}"
        os.environ["BROWSER_OPENED"] = "true"
        open_browser(url, delay=2.0)

    # Start server
    reload_dir = str(Path(__file__).resolve().parent)
    uvicorn.run(
        "jetstream.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[reload_dir] if args.reload else None,
        reload_excludes=[".git", ".git/*", "**/.git/**", ".browser_lock", "*.lock"] if args.reload else None,
        log_level=args.log_level,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
