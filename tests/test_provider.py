import io
import json
import urllib.request

import pytest
from helpers import addr, thash

from chaintrace.adapters import BlockscoutStyleAdapter, CsvAdapter, ProviderError
from chaintrace.adapters.provider_adapter import default_fetcher

BASE = "https://explorer.example"


def item(n, value="1500000000000000000", to=True, block=100):
    return {"hash": thash(n), "block_number": block, "timestamp": "2026-02-01T00:00:00.000000Z",
            "from": {"hash": addr(1)}, "to": {"hash": addr(2)} if to else None, "value": value}


def make(items, **kw):
    return BlockscoutStyleAdapter(BASE, addr(1), fetcher=lambda url: {"items": items}, **kw)


def test_maps_native_transfers_and_converts_wei():
    ad = make([item(1), item(2, value="250000000000000000")])
    res = ad.load()
    assert len(res.valid) == 2 and sorted(res.valid.amount) == [0.25, 1.5]
    assert "provider:explorer.example" in res.valid.data_source.iloc[0] and ad.skipped == 0


def test_skips_zero_value_contract_creation_and_malformed():
    ad = make([item(1), item(2, value="0"), item(3, to=False), {"junk": True}, item(4, block=None)])
    res = ad.load()
    assert len(res.valid) == 1 and ad.skipped == 4


def test_limit_applies():
    assert len(make([item(i) for i in range(1, 6)], limit=2).load().valid) == 2


def test_requested_url_is_the_documented_endpoint():
    seen = []
    BlockscoutStyleAdapter(BASE, addr(1).upper().replace("0X", "0x"), fetcher=lambda u: seen.append(u) or {"items": [item(1)]}).load()
    assert seen == [f"{BASE}/api/v2/addresses/{addr(1)}/transactions"]


@pytest.mark.parametrize("payload", [{}, {"items": "x"}, [], {"items": []}])
def test_unexpected_or_empty_payloads_raise_provider_error(payload):
    with pytest.raises(ProviderError):
        BlockscoutStyleAdapter(BASE, addr(1), fetcher=lambda u: payload).load()


@pytest.mark.parametrize("kw", [dict(base_url="http://insecure.example"), dict(address="0x123"), dict(limit=0)])
def test_constructor_validation(kw):
    args = dict(base_url=BASE, address=addr(1))
    args.update(kw)
    with pytest.raises(ValueError):
        BlockscoutStyleAdapter(**args)


def test_default_fetcher_refuses_non_https():
    with pytest.raises(ProviderError):
        default_fetcher("http://explorer.example/x")


def test_default_fetcher_is_get_only_without_credentials(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return io.BytesIO(json.dumps({"items": []}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert default_fetcher(f"{BASE}/api") == {"items": []}
    req = captured["req"]
    assert req.get_method() == "GET" and req.data is None
    assert not {"authorization", "x-api-key"} & {k.lower() for k in req.headers}


def test_adapters_declare_read_only_and_expose_no_write_api():
    for cls in (CsvAdapter, BlockscoutStyleAdapter):
        assert cls.read_only is True
        assert not [m for m in dir(cls) if any(w in m.lower() for w in ("send", "sign", "broadcast", "private_key"))]
