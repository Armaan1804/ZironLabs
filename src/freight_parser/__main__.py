"""Allows `python -m freight_parser` as an alias for `python -m freight_parser.cli`."""

import sys
from freight_parser.cli import main

sys.exit(main())
