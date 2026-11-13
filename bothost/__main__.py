import asyncio
import logging
import sys

from .app import Host
from .config import load

if len(sys.argv) != 2:
    raise SystemExit("usage: python -m bothost <config.json>")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
asyncio.run(Host(load(sys.argv[1])).serve())
