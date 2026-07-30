"""sniff: token-efficient code-smell detection for AI agents."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sniff")  # dist name; Task 8 fixes this if PyPI forces a rename
except PackageNotFoundError:  # running from a checkout without install
    __version__ = "0.0.0.dev"
