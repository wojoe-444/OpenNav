"""Read public S3 objects over plain HTTPS with range requests.

DuckDB extensions and the AWS SDK are not always reachable from locked-down
environments, but an anonymous HTTPS GET to the bucket usually is. This module
gives pyarrow a seekable file object backed by HTTP Range requests, so we can
read only the Parquet footers and the row groups we need.
"""
from __future__ import annotations

import io
import re
import time
import xml.etree.ElementTree as ET

import requests

_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
_session = requests.Session()


def _get(url: str, headers: dict | None = None, retries: int = 4) -> requests.Response:
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            r = _session.get(url, headers=headers or {}, timeout=120)
            if r.status_code in (200, 206):
                return r
            if r.status_code < 500:
                r.raise_for_status()
        except requests.RequestException:
            if attempt == retries:
                raise
        time.sleep(delay)
        delay *= 2
    raise IOError(f"GET failed: {url}")


def list_objects(bucket_url: str, prefix: str) -> list[tuple[str, int]]:
    """Return (key, size) for every object under prefix."""
    out: list[tuple[str, int]] = []
    token = None
    while True:
        url = f"{bucket_url}/?list-type=2&prefix={prefix}"
        if token:
            url += "&continuation-token=" + requests.utils.quote(token, safe="")
        root = ET.fromstring(_get(url).content)
        for c in root.findall("s3:Contents", _NS):
            out.append((c.find("s3:Key", _NS).text, int(c.find("s3:Size", _NS).text)))
        if root.findtext("s3:IsTruncated", namespaces=_NS) != "true":
            return out
        token = root.findtext("s3:NextContinuationToken", namespaces=_NS)


def list_prefixes(bucket_url: str, prefix: str) -> list[str]:
    root = ET.fromstring(_get(f"{bucket_url}/?list-type=2&prefix={prefix}&delimiter=/").content)
    return [p.findtext("s3:Prefix", namespaces=_NS) for p in root.findall("s3:CommonPrefixes", _NS)]


class HTTPRangeFile(io.RawIOBase):
    """Seekable, read-only file over HTTP Range requests with a small block cache."""

    BLOCK = 1 << 20

    def __init__(self, url: str, size: int):
        self.url, self.size, self.pos = url, size, 0
        self._cache: dict[int, bytes] = {}
        self.bytes_fetched = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def _fetch(self, start: int, end: int) -> bytes:
        r = _get(self.url, {"Range": f"bytes={start}-{end - 1}"})
        self.bytes_fetched += len(r.content)
        return r.content

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        if n == 0:
            return b""
        start, end = self.pos, self.pos + n
        if n > 4 * self.BLOCK:  # big column chunk: one direct request
            data = self._fetch(start, end)
        else:
            parts = []
            for b in range(start // self.BLOCK, (end - 1) // self.BLOCK + 1):
                if b not in self._cache:
                    lo = b * self.BLOCK
                    self._cache[b] = self._fetch(lo, min(lo + self.BLOCK, self.size))
                parts.append(self._cache[b])
            buf = b"".join(parts)
            off = start - (start // self.BLOCK) * self.BLOCK
            data = buf[off:off + n]
        self.pos = end
        return data

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)
