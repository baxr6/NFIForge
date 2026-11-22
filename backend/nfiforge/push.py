# ===========================================================================
# PHONE ALERTS: web push, so an alert reaches a phone with the app closed. payloads are encrypted for the phone
# (rfc 8291) and signed with this server's key (rfc 8292); the push services only ever see encrypted bytes
# ===========================================================================
import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from nfiforge.access import Access
from nfiforge.store import Store

log = logging.getLogger(__name__)

# the browsers' push services; a subscription anywhere else is refused so nobody can make the server post to
# an address of their choosing
PUSH_HOSTS = ("fcm.googleapis.com", ".push.apple.com", ".push.services.mozilla.com", ".notify.windows.com")
SUB = "https://github.com/baxr6/NFIForge"


def b64(data: bytes) -> str:
  return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
  return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
  return HKDF(hashes.SHA256(), length, salt, info).derive(ikm)


def _raw(key: ec.EllipticCurvePublicKey) -> bytes:
  return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def allowed(endpoint: str) -> bool:
  parts = urlsplit(endpoint)
  host = (parts.hostname or "").lower()
  return parts.scheme == "https" and any(
    host.endswith(known) if known.startswith(".") else host == known for known in PUSH_HOSTS
  )


def encrypt(
  payload: bytes,
  ua_public: bytes,
  auth: bytes,
  salt: bytes | None = None,
  as_key: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
  # aes128gcm, one record: salt, record size, sender key, then the sealed payload with its 0x02 end marker
  as_key = as_key or ec.generate_private_key(ec.SECP256R1())
  salt = salt or os.urandom(16)
  as_public = _raw(as_key.public_key())
  ecdh = as_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
  ikm = _hkdf(auth, ecdh, b"WebPush: info\0" + ua_public + as_public, 32)
  cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\0", 16)
  nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\0", 12)
  sealed = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
  return salt + (4096).to_bytes(4, "big") + bytes([len(as_public)]) + as_public + sealed


class Push:
  def __init__(self, data_dir: str | Path, store: Store) -> None:
    self.store = store
    key_file = Path(data_dir) / "vapid.pem"
    if not key_file.exists():
      pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
      )
      fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
      with os.fdopen(fd, "wb") as out:
        out.write(pem)
    key = serialization.load_pem_private_key(key_file.read_bytes(), None)
    assert isinstance(key, ec.EllipticCurvePrivateKey)
    self.key = key
    self.public = b64(_raw(key.public_key()))
    self._tasks: set[asyncio.Task] = set()

  def _jwt(self, endpoint: str) -> str:
    parts = urlsplit(endpoint)
    head = b64(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    exp = int(time.time()) + 12 * 3600
    claims = b64(json.dumps({"aud": f"{parts.scheme}://{parts.netloc}", "exp": exp, "sub": SUB}).encode())
    sig_r, sig_s = decode_dss_signature(self.key.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"{head}.{claims}.{b64(sig_r.to_bytes(32, 'big') + sig_s.to_bytes(32, 'big'))}"

  async def send(self, note: dict[str, Any], user_id: int | None = None) -> int:
    # every subscribed phone (or one user's); gone ones (404 / 410) are dropped. returns how many took it
    subs = self.store.push_subs(user_id)
    if user_id is None:  # an alert: only to who may see it (a user's own test goes to them)
      subs = [subscription for subscription in subs if Access(subscription).note(note)]
    if not subs:
      return 0
    msg = json.dumps(
      {
        "title": f"{note['bot']}: {note['title']}" if note.get("bot") else note["title"],
        "body": str(note.get("detail") or "")[:1000],
        "tag": f"{note.get('bot')}:{note.get('key')}",
        "level": note.get("level"),
      }
    ).encode()
    ok = 0
    async with httpx.AsyncClient(timeout=10) as client:
      for subscription in subs:
        try:
          response = await client.post(
            subscription["endpoint"],
            content=encrypt(msg, unb64(subscription["p256dh"]), unb64(subscription["auth"])),
            headers={
              "Content-Encoding": "aes128gcm",
              "TTL": "86400",
              "Urgency": "high",
              "Authorization": f"vapid t={self._jwt(subscription['endpoint'])}, k={self.public}",
            },
          )
        except httpx.HTTPError as e:
          log.warning("push to %s failed: %s", urlsplit(subscription["endpoint"]).hostname, type(e).__name__)
          continue
        if response.status_code in (404, 410):
          self.store.drop_push(subscription["endpoint"])
        elif response.status_code >= 400:
          log.warning(
            "push to %s refused: %s %s",
            urlsplit(subscription["endpoint"]).hostname,
            response.status_code,
            response.text[:200],
          )
        else:
          ok += 1
    return ok

  def notify(self, note: dict[str, Any]) -> None:
    # from sync code on the event loop: send in the background, keep the task so it isn't collected early
    try:
      task = asyncio.get_running_loop().create_task(self.send(note))
    except RuntimeError:
      return
    self._tasks.add(task)
    task.add_done_callback(self._tasks.discard)
