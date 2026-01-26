import os
import uvicorn
from classificationg2s.app import app
from classificationg2s.cli import main as cli_main
import sys

if __name__ == "__main__":
    # Check if any CLI arguments are passed (other than script name)
    # This is a simple heuristic to switch between API server and CLI tools
    if len(sys.argv) > 1:
        # Pass control to the CLI handler (which handles arg parsing)
        sys.exit(cli_main())
    else:
        # Run the API server
        # Note: --reload is effective only when passed to uvicorn command line or via reload=True here
        # Local dev usually runs: uv run uvicorn main:app --reload
        # In that case, this block is NOT executed because uvicorn imports main:app directly.
        # This block is for `python main.py` execution.
        config_host = os.getenv("HOST", "0.0.0.0")
        config_port = int(os.getenv("PORT", 8000))
        uvicorn.run("main:app", host=config_host, port=config_port, reload=True)
