"""`python3 -m panel.api` — the API server without a window."""
import sys

from .http_adapter import main

if __name__ == "__main__":
    sys.exit(main())
