#!/usr/bin/env python3
"""Run the web dashboard."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
