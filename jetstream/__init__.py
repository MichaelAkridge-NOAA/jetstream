"""
NOAA JetStream - Cloud Data Manager
A comprehensive tool for managing local-to-cloud uploads with queue management,
statistics, and folder analysis.
"""

__version__ = "0.1.15"
__author__ = "Michael Akridge"
__description__ = "JetStream: Cloud Data Manager for local-to-cloud uploads"

# Lazy import to avoid triggering server initialization on package import
def _get_app():
    from jetstream.main import app
    return app

# For backwards compatibility
def __getattr__(name):
    if name == "app":
        return _get_app()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = ["__version__"]
