#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 scripts/catalog.py check
python3 -m unittest discover -s tests -t .
node --check site/assets/i18n.js
node --check site/assets/filters.js
node --check site/assets/analysis.js
node --check site/assets/app.js
node tests/test_filters.js
node tests/test_analysis.js
node tests/test_site.js
