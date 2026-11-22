#!/usr/bin/env bash
# Developer start (Linux/macOS): uses this Python to build the environments once, then runs the studio.
cd "$(dirname "$0")" && exec python3.11 -m studio.bootstrap "$@"
