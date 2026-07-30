"""Allow `python -m sniff` and `python -m sniff.cli`."""
import sys

from sniff.cli import main

sys.exit(main())
