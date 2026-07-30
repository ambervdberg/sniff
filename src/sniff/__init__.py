"""sniff: token-efficient code-smell detection for AI agents."""
from importlib.metadata import PackageNotFoundError, version

for _dist in ("sniff-smells", "sniff"):
    try:
        __version__ = version(_dist)
        break
    except PackageNotFoundError:
        continue
else:  # running from a checkout without install
    __version__ = "0.0.0.dev"
