"""Polite HTTP: one shared session, per-host minimum spacing between requests
and retry with backoff. SEC allows max 10 req/s, GDELT one per 5 s."""
import time
from urllib.parse import urlparse

import requests

MIN_INTERVAL_S = {
    "www.sec.gov": 0.2,
    "api.gdeltproject.org": 8.0,
}
_last_call: dict = {}
_session = requests.Session()


def get(url: str, headers: dict = None, params: dict = None, timeout: float = 30.0,
        retries: int = 3) -> requests.Response:
    host = urlparse(url).hostname or ""
    wait = MIN_INTERVAL_S.get(host, 0.0)
    last_err = None
    for attempt in range(retries + 1):
        elapsed = time.monotonic() - _last_call.get(host, 0.0)
        if elapsed < wait:
            time.sleep(wait - elapsed)
        _last_call[host] = time.monotonic()
        try:
            resp = _session.get(url, headers=headers, params=params, timeout=timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last_err = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                raise
            time.sleep(max(wait, 1.0) * (2 ** attempt))
    raise last_err
