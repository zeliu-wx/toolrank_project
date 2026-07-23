"""Launch GPTScan in-process without exposing its API key in OS argv."""

from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys


def main() -> None:
    script = Path(os.environ["LAKES_GPTSCAN_MAIN"]).resolve()
    source = os.environ["LAKES_GPTSCAN_SOURCE"]
    output = os.environ["LAKES_GPTSCAN_OUTPUT"]
    key = os.environ.get("OPENAI_API_KEY", "")
    os.chdir(script.parent)
    sys.path.insert(0, str(script.parent))
    sys.argv = [str(script), "-s", source, "-o", output, "-k", key]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
