#!/usr/bin/env python3
"""STDIO entry point for the new employee collaboration protocol."""

import sys

import app_secrets
from runteams_core.protocol import main


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(2)
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3],
         credential_resolver=app_secrets.resolve)
