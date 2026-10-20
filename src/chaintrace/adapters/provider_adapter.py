"""Optional, read-only adapter for Blockscout-style public explorer APIs.

* Off by default: nothing in ChainTrace calls it unless the analyst asks.
* No API key is needed or accepted. Only HTTPS ``GET`` requests are made.
* Only native-coin transfers on the first result page are mapped (no token transfers,
  no pagination). See docs/LIMITATIONS.md.
* The response mapping follows the publicly documented ``/api/v2/addresses/{hash}/
  transactions`` shape. It is unit-tested against mocked responses and has NOT been
  verified against a live endpoint in this build; verify before relying on it.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Callable

import pandas as pd

from ..importer import ImportResult, validate_frame
from ..schema import ValidationConfig
from .base import TransactionSource

WEI_PER_ETH = Decimal(10) ** 18
_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

Fetcher = Callable[[str], dict]


class ProviderError(RuntimeError):
    """Provider unreachable, refused, or returned an unexpected shape."""


def default_fetcher(url: str) -> dict:
    """HTTPS GET returning parsed JSON. No credentials are ever attached."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProviderError("provider URL must use https")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "ChainTrace/0.1 (read-only)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # https enforced above
            return json.load(response)
    except Exception as exc:  # network, HTTP and JSON errors all surface as ProviderError
        raise ProviderError(f"request failed: {exc}") from exc


class BlockscoutStyleAdapter(TransactionSource):
    name = "provider-blockscout-style"

    def __init__(
        self,
        base_url: str,
        address: str,
        limit: int = 100,
        asset: str = "ETH",
        fetcher: Fetcher | None = None,
        config: ValidationConfig | None = None,
    ):
        if not base_url.lower().startswith("https://"):
            raise ValueError("base_url must start with https://")
        if not _ADDR_RE.match(address.strip()):
            raise ValueError("address must be a 0x-prefixed 40-hex-character address")
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        self.base_url = base_url.rstrip("/")
        self.address = address.strip().lower()
        self.limit = min(limit, 1000)
        self.asset = asset.upper()
        self._fetcher = fetcher or default_fetcher
        self._config = config
        self.skipped = 0

    def load(self) -> ImportResult:
        url = f"{self.base_url}/api/v2/addresses/{self.address}/transactions"
        payload = self._fetcher(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ProviderError("unexpected response shape (no 'items' list)")
        host = urllib.parse.urlparse(self.base_url).netloc
        rows, skipped = [], 0
        for item in payload["items"][: self.limit]:
            try:
                value = Decimal(str(item.get("value", "0"))) / WEI_PER_ETH
                to_obj = item.get("to") or {}
                block = item.get("block_number", item.get("block"))
                if value <= 0 or not to_obj.get("hash") or block is None:
                    skipped += 1
                    continue
                rows.append(
                    {
                        "tx_hash": item["hash"],
                        "block_number": str(block),
                        "timestamp": item["timestamp"],
                        "from_address": item["from"]["hash"],
                        "to_address": to_obj["hash"],
                        "asset": self.asset,
                        "amount": f"{value:f}",
                        "data_source": f"provider:{host} (public explorer API, read-only)",
                    }
                )
            except (KeyError, TypeError, InvalidOperation):
                skipped += 1
        self.skipped = skipped
        if not rows:
            raise ProviderError("provider returned no native-coin transfers to map")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        sha = hashlib.sha256(canonical).hexdigest()
        return validate_frame(pd.DataFrame(rows, dtype=str), sha, f"provider:{host}", self._config)
