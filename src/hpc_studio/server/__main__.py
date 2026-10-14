"""Executable module entrypoint for python -m hpc_studio.server."""

import sys
from hpc_studio.server.cli import main

if __name__ == "__main__":
    sys.exit(main())
