"""
WSGI Entry Point for Content Catalog Service.

This module provides the WSGI application object for production deployment
with gunicorn or other WSGI servers.

Usage:
    gunicorn -w 4 -b 0.0.0.0:8080 wsgi:application
"""

import os
import sys

# Add the parent directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

# Create the application instance
application = create_app()

# Alias for compatibility
app = application

if __name__ == "__main__":
    application.run()
