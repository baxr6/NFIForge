# newer release check: github's public releases api, at most once a day, silent on any failure (private repo, offline)

from __future__ import annotations

import time
from pathlib import Path

import httpx

from nfiforge import REPO, __version__

_cache: dict[str, tuple[float, dict]] = {}


def _ver(version: str) -> tuple[int, ...]:
  try:
    return tuple(int(part) for part in version.lstrip("v").split("-")[0].split("."))
  except ValueError:
    return (0,)


async def latest_release(repo: str) -> dict:
  # a repo's latest github release, cached a day; {} when unknown
  fetched_at, data = _cache.get(repo, (0.0, None))
  if time.time() - fetched_at > 86400 or data is None:
    try:
      async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(
          f"https://api.github.com/repos/{repo}/releases/latest", headers={"Accept": "application/vnd.github+json"}
        )
      data = response.json() if response.status_code == 200 else {}
    except httpx.HTTPError:
      data = {}
    _cache[repo] = (time.time(), data)
  return data or {}


def newer(latest: str, current: str) -> bool:
  return _ver(latest) > _ver(current)


async def check(enabled: bool = True) -> dict:
  # docker installs update with the installer, pipx ones by installing the release's wheel
  how = "./install.sh --update" if Path("/.dockerenv").exists() else "nfiforge update"
  out = {"current": __version__, "latest": None, "newer": False, "url": None, "how": how}
  if not enabled:
    return out
  release = await latest_release(REPO)
  if release.get("tag_name"):
    out.update(latest=release["tag_name"].lstrip("v"), url=release.get("html_url"))
    out["newer"] = newer(out["latest"], __version__)
  return out
