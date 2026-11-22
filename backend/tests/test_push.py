import json

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from nfiforge.push import Push, _hkdf, _raw, allowed, b64, encrypt, unb64
from nfiforge.store import Store
from test_phase0 import _cfg, _signin

# rfc 8291 section 5 / appendix a
RFC = {
  "plain": b"When I grow up, I want to be a watermelon",
  "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
  "ua_private": "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94",
  "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
  "salt": "DGv6ra1nlYgDCS1FRnbzlw",
  "auth": "BTBZMqHH6r4Tts7J_aSIgg",
  "body": "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
  "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
  "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
}


def _key(private_value: str) -> ec.EllipticCurvePrivateKey:
  return ec.derive_private_key(int.from_bytes(unb64(private_value), "big"), ec.SECP256R1())


def _decrypt(body: bytes, user_agent_key: ec.EllipticCurvePrivateKey, auth: bytes) -> bytes:
  # the phone's side, to check what we send opens
  salt, key_length = body[:16], body[20]
  as_public, sealed = body[21 : 21 + key_length], body[21 + key_length :]
  ua_public = _raw(user_agent_key.public_key())
  ecdh = user_agent_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
  ikm = _hkdf(auth, ecdh, b"WebPush: info\0" + ua_public + as_public, 32)
  cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\0", 16)
  nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\0", 12)
  out = AESGCM(cek).decrypt(nonce, sealed, None)
  assert out.endswith(b"\x02")
  return out[:-1]


def test_rfc8291_example():
  body = encrypt(RFC["plain"], unb64(RFC["ua_public"]), unb64(RFC["auth"]), unb64(RFC["salt"]), _key(RFC["as_private"]))
  assert b64(body) == RFC["body"]
  assert _decrypt(body, _key(RFC["ua_private"]), unb64(RFC["auth"])) == RFC["plain"]


def test_push_hosts():
  assert allowed("https://fcm.googleapis.com/fcm/send/abc")
  assert allowed("https://web.push.apple.com/QK1")
  assert allowed("https://updates.push.services.mozilla.com/wpush/v2/x")
  assert allowed("https://wns2-par02p.notify.windows.com/w/?token=x")
  assert not allowed("http://fcm.googleapis.com/fcm/send/abc")
  assert not allowed("https://evilpush.apple.com.example.org/x")
  assert not allowed("https://127.0.0.1:8081/api/v1/forceexit")
  assert not allowed("https://notify.windows.com.evil/x")


async def test_send_and_drop(tmp_path, monkeypatch):
  db = Store(tmp_path)
  user_id = db.add_user("p", "x", "viewer")
  push = Push(tmp_path, db)
  assert (tmp_path / "vapid.pem").stat().st_mode & 0o777 == 0o600
  phone = ec.generate_private_key(ec.SECP256R1())
  auth = b"0123456789abcdef"
  db.add_push(user_id, "https://fcm.googleapis.com/fcm/send/a", b64(_raw(phone.public_key())), b64(auth), "ua")
  db.add_push(user_id, "https://fcm.googleapis.com/fcm/send/gone", b64(_raw(phone.public_key())), b64(auth), "ua")
  sent = []

  async def post(self, url, content=None, headers=None):
    sent.append((url, content, headers))
    return httpx.Response(410 if url.endswith("gone") else 201, request=httpx.Request("POST", url))

  monkeypatch.setattr(httpx.AsyncClient, "post", post)
  note = {"bot": "C86", "key": "liq", "level": "bad", "title": "BTC near liquidation", "detail": "12 % away"}
  assert await push.send(note) == 1
  url, content, headers = sent[0]
  msg = json.loads(_decrypt(content, phone, auth))
  assert msg["title"] == "C86: BTC near liquidation" and msg["body"] == "12 % away" and msg["tag"] == "C86:liq"
  # vapid: es256 jwt for the push service's origin, signed by the key we hand out
  token, public_key = headers["Authorization"].removeprefix("vapid t=").split(", k=")
  head, claims, signature = token.split(".")
  assert json.loads(unb64(claims))["aud"] == "https://fcm.googleapis.com" and public_key == push.public
  pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(public_key))
  raw = unb64(signature)
  der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
  pub.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
  # the gone one was dropped, and signing out everywhere drops the rest
  assert [sub_row["endpoint"] for sub_row in db.push_subs()] == ["https://fcm.googleapis.com/fcm/send/a"]
  db.end_sessions(user_id)
  assert db.push_subs() == []
  # same key after a restart
  assert Push(tmp_path, db).public == push.public


async def test_push_routes(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  transport = httpx.ASGITransport(app=app)
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://t") as client:
    assert (await client.get("/api/push/key")).status_code == 401
    await _signin(app, client, role="viewer")
    key = (await client.get("/api/push/key")).json()["key"]
    assert len(unb64(key)) == 65
    keys = {"p256dh": key, "auth": "MDEyMzQ1Njc4OWFiY2RlZg"}
    bad = await client.post("/api/push/subscribe", json={"endpoint": "https://127.0.0.1:8081/x", "keys": keys})
    assert bad.status_code == 400
    assert (
      await client.post("/api/push/subscribe", json={"endpoint": "https://web.push.apple.com/a"})
    ).status_code == 400
    endpoint = "https://web.push.apple.com/a"
    assert (await client.post("/api/push/subscribe", json={"endpoint": endpoint, "keys": keys})).json()["ok"]
    assert len(app.state.db.push_subs()) == 1
    # signing this device out stops its alerts
    await client.post("/api/auth/logout", json={"push": endpoint})
    assert app.state.db.push_subs() == []


def test_only_alerts_are_pushed(tmp_path):
  from nfiforge.alerts import Notifier
  from nfiforge.settings import AlertSettings

  pushed = []
  notifier = Notifier(Store(tmp_path), lambda: AlertSettings(), lambda message: None, pushed.append)
  notifier._emit({"kind": "alert", "title": "a"})
  notifier._emit({"kind": "trade", "title": "t"})
  notifier._emit({"kind": "action", "title": "x"})
  assert [pushed_item["title"] for pushed_item in pushed] == ["a"]
