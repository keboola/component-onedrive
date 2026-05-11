#!/bin/sh
set -e

ruff check
python -m pytest --tb=short -q
