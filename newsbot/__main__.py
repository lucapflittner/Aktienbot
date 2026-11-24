import sys

from .cli import main

rc = main()
sys.exit(rc if isinstance(rc, int) else 0)
