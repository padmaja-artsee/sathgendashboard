#!/usr/bin/env python3
"""Run the sathgen dashboard locally."""
import os
import sys

# Point both the CRM and Finance modules to the shared App Support database
# so the local dev server and the desktop app always use the same data.
_app_support = os.path.expanduser("~/Library/Application Support/SathgenDashboard")
os.makedirs(_app_support, exist_ok=True)
os.environ.setdefault("SATHGEN_DATA_DIR", _app_support)
os.environ.setdefault("FINANCE_DB_PATH",  os.path.join(_app_support, "finance.db"))
os.environ.setdefault("SATHGEN_DB_PATH",  os.path.join(_app_support, "sathgendashboard.db"))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=True,
        reload_dirs=["app", "finance", "templates", "static"],
    )
