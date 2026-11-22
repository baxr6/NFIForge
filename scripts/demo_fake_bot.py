# runs the test fake freqtrade on :18080 so the ui can be tried without a real bot
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "tests"))
from fake_freqtrade import make_fake  # noqa: E402

uvicorn.run(make_fake(), host="127.0.0.1", port=18080, log_level="warning")
