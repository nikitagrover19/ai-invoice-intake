#!/usr/bin/env bash
# Starts the invoice processing app at http://localhost:8420
cd "$(dirname "$0")/backend"
python3 -m uvicorn main:app --host 0.0.0.0 --port 8420 --reload
