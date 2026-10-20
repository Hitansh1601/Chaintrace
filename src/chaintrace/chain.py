"""Blockchain network registry for ChainTrace.

ChainTrace is chain-agnostic but EVM-account-model only: every transfer row is
``one sender -> one recipient`` with ``0x``-prefixed addresses and hashes.
This module records *which* real blockchains that format fits, so analysts,
reports and the demo can name the chain instead of saying "some blockchain".

* The bundled synthetic dataset simulates **Ethereum mainnet** semantics
  (chain id 1, ~12s blocks starting at block ~19M, ``ETH`` 18 decimals,
  ``USDC`` 6 decimals). See ``synthetic.CHAIN_ID``.
* Live data comes only from the optional ``BlockscoutStyleAdapter``, which
  speaks the Blockscout v2 API used by Ethereum, Sepolia, Polygon, BNB Chain,
  Arbitrum, Base and other EVM explorers. No RPC node, no signing, no keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ChainInfo:
    """Static description of one EVM-compatible network."""

    name: str  # canonical short name, e.g. "ethereum"
    chain_id: int  # EIP-155 chain id
    display_name: str  # human label, e.g. "Ethereum mainnet"
    native_asset: str  # e.g. "ETH"
    native_decimals: int  # e.g. 18
    block_time_secs: int  # nominal block time, for context only
    address_format: str  # always EVM-style for this tool
    explorer_api_example: str  # example Blockscout-style base URL
    notes: str = ""


SUPPORTED_CHAINS: dict[str, ChainInfo] = {
    "ethereum": ChainInfo(
        name="ethereum",
        chain_id=1,
        display_name="Ethereum mainnet",
        native_asset="ETH",
        native_decimals=18,
        block_time_secs=12,
        address_format="EVM account (0x + 40 hex)",
        explorer_api_example="https://eth.blockscout.com",
        notes="Primary reference chain. Synthetic demo mimics this chain.",
    ),
    "sepolia": ChainInfo(
        name="sepolia",
        chain_id=11155111,
        display_name="Sepolia testnet",
        native_asset="ETH",
        native_decimals=18,
        block_time_secs=12,
        address_format="EVM account (0x + 40 hex)",
        explorer_api_example="https://eth-sepolia.blockscout.com",
        notes="Good free source of real EVM data for classroom demos.",
    ),
    "polygon": ChainInfo(
        name="polygon",
        chain_id=137,
        display_name="Polygon PoS",
        native_asset="MATIC",
        native_decimals=18,
        block_time_secs=2,
        address_format="EVM account (0x + 40 hex)",
        explorer_api_example="https://polygon.blockscout.com",
        notes="Same address format; native asset label differs.",
    ),
    "bsc": ChainInfo(
        name="bsc",
        chain_id=56,
        display_name="BNB Smart Chain",
        native_asset="BNB",
        native_decimals=18,
        block_time_secs=3,
        address_format="EVM account (0x + 40 hex)",
        explorer_api_example="https://bsc.blockscout.com",
        notes="EVM-compatible; works with the same adapter.",
    ),
    "arbitrum": ChainInfo(
        name="arbitrum",
        chain_id=42161,
        display_name="Arbitrum One",
        native_asset="ETH",
        native_decimals=18,
        block_time_secs=1,
        address_format="EVM account (0x + 40 hex)",
        explorer_api_example="https://arbitrum.blockscout.com",
        notes="L2; explorer API shape is the same Blockscout v2.",
    ),
    "base": ChainInfo(
        name="base",
        chain_id=8453,
        display_name="Base",
        native_asset="ETH",
        native_decimals=18,
        block_time_secs=2,
        address_format="EVM account (0x + 40 hex)",
        explorer_api_example="https://base.blockscout.com",
        notes="L2; explorer API shape is the same Blockscout v2.",
    ),
}

DEFAULT_CHAIN = "ethereum"

# Display-unit decimals per asset label. Native EVM assets use 18;
# fiat-backed stablecoins such as USDC/USDT use 6. Unknown assets fall back to 18.
ASSET_DECIMALS: dict[str, int] = {
    "ETH": 18,
    "WETH": 18,
    "MATIC": 18,
    "BNB": 18,
    "AVAX": 18,
    "DAI": 18,
    "USDC": 6,
    "USDT": 6,
}

# What the synthetic demo pretends to be. Kept in one place so reports,
# docs and the UI all say the same thing.
SYNTHETIC_CHAIN = {
    "name": "ethereum",
    "chain_id": 1,
    "note": (
        "Synthetic demo data simulates Ethereum-mainnet semantics "
        "(chain id 1, ~12s blocks from ~19M, ETH 18 decimals / USDC 6 decimals). "
        "Addresses and transfers are invented and resolve to no real chain."
    ),
}


def list_chains() -> list[ChainInfo]:
    """All known chains, sorted by chain id for stable UI ordering."""
    return sorted(SUPPORTED_CHAINS.values(), key=lambda c: c.chain_id)


def get_chain(name_or_id: str | int) -> ChainInfo:
    """Look up a chain by short name (``"ethereum"``) or EIP-155 id (``1``).

    Raises ``KeyError`` with the valid names when unknown.
    """
    if isinstance(name_or_id, int):
        for chain in SUPPORTED_CHAINS.values():
            if chain.chain_id == name_or_id:
                return chain
        raise KeyError(f"unknown chain_id {name_or_id}; known: {sorted(SUPPORTED_CHAINS)}")
    key = str(name_or_id).strip().lower()
    # Accept "chain id 1" style input too.
    for chain in SUPPORTED_CHAINS.values():
        if key == chain.name or key == str(chain.chain_id):
            return chain
    raise KeyError(f"unknown chain {name_or_id!r}; known: {sorted(SUPPORTED_CHAINS)}")


def normalize_chain_label(label: str) -> str:
    """Return the canonical chain name when known, else the cleaned label.

    Never raises: custom/private Blockscout instances stay usable.
    """
    key = str(label or "").strip().lower() or DEFAULT_CHAIN
    return SUPPORTED_CHAINS[key].name if key in SUPPORTED_CHAINS else key


def decimals_for_asset(asset: str, override: int | None = None) -> int:
    """Decimals used to convert base units for ``asset``.

    ``override`` wins when given; otherwise the per-asset table; else 18.
    """
    if override is not None:
        if not isinstance(override, int) or override < 0 or override > 36:
            raise ValueError("decimals must be an integer in 0..36")
        return override
    return ASSET_DECIMALS.get(str(asset or "").strip().upper(), 18)


def from_base_units(value_base_units: str | int, decimals: int) -> Decimal:
    """Convert an integer base-unit value (wei, sun, ...) to display units."""
    return Decimal(str(value_base_units)) / (Decimal(10) ** decimals)


def describe_chain(name_or_id: str | int) -> str:
    """One-line human summary, e.g. ``"Ethereum mainnet (chain id 1)"``."""
    chain = get_chain(name_or_id)
    return f"{chain.display_name} (chain id {chain.chain_id})"
