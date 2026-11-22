import httpx
import pytest
from nfiforge import fx
from nfiforge.fx import Fx


async def test_rate_mid_fallback_and_stale(monkeypatch):
  now = [1000.0]
  monkeypatch.setattr(fx.time, "time", lambda: now[0])
  calls = []
  kraken_up = [True]

  async def get(self, url, params=None):
    calls.append(url)
    request = httpx.Request("GET", url)
    if "kraken" in url:
      if not kraken_up[0]:
        raise httpx.ConnectError("down", request=request)
      return httpx.Response(
        200, json={"error": [], "result": {"USDTAUD": {"a": ["1.4320"], "b": ["1.4310"]}}}, request=request
      )
    return httpx.Response(200, json={"bestBid": "1.4300", "bestAsk": "1.4340"}, request=request)

  monkeypatch.setattr(httpx.AsyncClient, "get", get)
  rates = Fx()
  rate = await rates.rate("aud")
  assert rate["rate"] == pytest.approx(1.4315) and rate["source"] == "kraken"
  # cached inside a minute
  now[0] += 30
  await rates.rate("AUD")
  assert len(calls) == 1
  # kraken down: btc markets for aud
  kraken_up[0] = False
  now[0] += 60
  rate = await rates.rate("AUD")
  assert rate["rate"] == pytest.approx(1.432) and rate["source"] == "btcmarkets"
  # eur has no fallback: last rate shown up to 5 minutes, then none
  kraken_up[0] = True
  monkeypatch.setattr(httpx.AsyncClient, "get", get)
  assert (await rates.rate("EUR"))["source"] == "kraken"
  kraken_up[0] = False
  now[0] += 120
  assert (await rates.rate("EUR")) is not None
  now[0] += 200
  assert (await rates.rate("EUR")) is None
  with pytest.raises(ValueError):
    await rates.rate("NZD")
