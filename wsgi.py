"""WSGI entry point for PythonAnywhere deployment.

Setup steps on PythonAnywhere:
1. Upload the project to /home/<your-username>/personal-finance-analyzer
2. In the Web tab, set the WSGI file path to this file
3. Set the working directory to /home/<your-username>/personal-finance-analyzer
4. In the Web tab > Environment variables, add:
     SECRET_KEY = (a long random string — e.g. run: python -c "import secrets; print(secrets.token_hex(32))")
5. Install dependencies:
     pip install --user -r requirements.txt
"""
import sys
import os

# Replace <your-username> with your actual PythonAnywhere username
project_path = os.path.expanduser("~/personal-finance-analyzer")
if project_path not in sys.path:
    sys.path.insert(0, project_path)

from app.server import app as application
