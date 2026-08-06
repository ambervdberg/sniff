import os
import shutil
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def tool_available(name: str) -> bool:
    """Whether `name` is on PATH.

    Locally a missing tool just skips the suite that needs it. In CI
    (SNIFF_TEST_REQUIRE_TOOLS set) it is a hard error instead, so an image
    without ast-grep or git cannot turn the run green by skipping everything.
    """
    found = shutil.which(name) is not None
    if not found and os.environ.get("SNIFF_TEST_REQUIRE_TOOLS"):
        raise RuntimeError(f"{name} is required in CI but was not found on PATH")
    return found


def write_tree_file(root: str, rel: str, body: str) -> str:
    """Write `body` (dedented) at `root/rel`, creating parents. Returns the path."""
    path = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(textwrap.dedent(body))
    return path
