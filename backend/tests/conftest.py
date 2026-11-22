import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

sys.path.insert(0, str(Path(__file__).parent))

from fake_freqtrade import make_fake  # noqa: E402  (needs the path above)


def _free_port() -> int:
  sock = socket.socket()
  sock.bind(("127.0.0.1", 0))
  port = sock.getsockname()[1]
  sock.close()
  return port


@pytest.fixture
def fake():
  app = make_fake()
  port = _free_port()
  server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
  thread = threading.Thread(target=server.run, daemon=True)
  thread.start()
  while not server.started:
    time.sleep(0.02)
  yield app, f"http://127.0.0.1:{port}", server
  server.should_exit = True
  thread.join(5)
