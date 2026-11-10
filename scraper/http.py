"""Polite HTTP client: one request at a time, pauses, no retries on 403."""
import random
import time
import urllib.error
import urllib.request

from . import config

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")
BACKOFF = (10, 30, 60)


class FetchError(Exception):
    pass


class Blocked(FetchError):
    pass


class NotFound(FetchError):
    pass


class Fetcher:
    def __init__(self, delay=config.DELAY, sleep=time.sleep, opener=urllib.request.urlopen):
        self.delay = delay
        self.sleep = sleep
        self.opener = opener
        self.count = 0

    def get(self, url):
        if self.count:
            self.sleep(random.uniform(*self.delay))
        self.count += 1
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "pl-PL,pl;q=0.9"})
        for attempt in range(len(BACKOFF) + 1):
            try:
                with self.opener(req, timeout=30) as resp:
                    return resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    raise Blocked("%s: HTTP 403" % url)
                if e.code in (404, 410):
                    raise NotFound("%s: HTTP %d" % (url, e.code))
                if e.code != 429 and e.code < 500:
                    raise FetchError("%s: HTTP %d" % (url, e.code))
                error = "HTTP %d" % e.code
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                error = str(e)
            if attempt < len(BACKOFF):
                self.sleep(BACKOFF[attempt])
        raise FetchError("%s: %s" % (url, error))
