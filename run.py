#!/usr/bin/env python3
"""Run the sathgen dashboard locally."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=True,
        reload_dirs=["app", "finance", "templates", "static"],
    )
