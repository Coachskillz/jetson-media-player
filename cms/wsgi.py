"""
WSGI Entry Point for CMS Service.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cms.app import create_app

application = create_app()
app = application

if __name__ == "__main__":
    application.run()
