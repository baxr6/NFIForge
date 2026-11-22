# accounts: scrypt password hashes, server-side sessions (only a hash of the cookie is stored), one-time phone
# pairing codes, and a small login rate limit. storage is the store's users / sessions / pairs tables

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

ROLES = ("admin", "viewer")
SESSION_DAYS = 30
PAIR_MINUTES = 10
COOKIE = "nfiforge_session"

# scrypt cost: ~16 MB, ~50 ms per check; stored with the hash so it can be raised later
N, R, P = 2**14, 8, 1


def _b64(data: bytes) -> str:
  return base64.b64encode(data).decode()


def hash_password(password: str) -> str:
  salt = secrets.token_bytes(16)
  derived = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
  return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, stored: str) -> bool:
  try:
    kind, cost, block_size, parallel, salt, derived = stored.split("$")
    if kind != "scrypt":
      return False
    got = hashlib.scrypt(
      password.encode(), salt=base64.b64decode(salt), n=int(cost), r=int(block_size), p=int(parallel), dklen=32
    )
    return hmac.compare_digest(got, base64.b64decode(derived))
  except (ValueError, TypeError):
    return False


# a dummy hash so a login for an unknown user takes as long as a wrong password (no username probing)
_DUMMY = hash_password(secrets.token_urlsafe(16))


def check_login(user: dict | None, password: str) -> bool:
  if not user or user.get("disabled"):
    verify_password(password, _DUMMY)
    return False
  return verify_password(password, user["pw"])


def password_problem(password: str) -> str | None:
  if len(password) < 10:
    return "password must be at least 10 characters"
  if len(password) > 256:
    return "password is too long"
  return None


def username_problem(username: str) -> str | None:
  if not (1 <= len(username) <= 40) or not all(char.isalnum() or char in "._-" for char in username):
    return "username: 1-40 letters, digits, dots, dashes or underscores"
  return None


def new_secret() -> tuple[str, str]:
  # (value given out once, hash kept in the database)
  value = secrets.token_urlsafe(32)
  return value, digest(value)


def digest(value: str) -> str:
  return hashlib.sha256(value.encode()).hexdigest()


class RateLimit:
  # failed logins per client address: 5 in 5 minutes, then wait
  def __init__(self, limit: int = 5, window: float = 300) -> None:
    self.limit, self.window = limit, window
    self.fails: dict[str, deque[float]] = defaultdict(deque)

  def blocked(self, key: str) -> float:
    fails, now = self.fails[key], time.time()
    while fails and fails[0] < now - self.window:
      fails.popleft()
    return (fails[0] + self.window - now) if len(fails) >= self.limit else 0

  def fail(self, key: str) -> None:
    self.fails[key].append(time.time())

  def clear(self, key: str) -> None:
    self.fails.pop(key, None)
