#!/bin/bash
echo "Stopping R&D Proposal Monitor..."
pkill -f "scraper.py" && echo "  Scraper stopped" || echo "  Scraper was not running"
pkill -f "api_server.py" && echo "  API server stopped" || echo "  API server was not running"
echo "Done."
