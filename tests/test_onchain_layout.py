import hashlib
import struct

import pytest

from onchain_layout import ACCOUNT_SIZE, assert_devnet, decode_account, review_id_hash


def _account(status=6):
    h = lambda s: hashlib.sha256(s.encode()).digest()  # noqa: E731
    data = b"\x00" * 8 + h("rev-c-0001") + h("in") + h("an") + h("rv")
    data += b"iasx-wf-1.0.0".ljust(32, b"\0") + b"extract-rules-1.1.0+mock-jev".ljust(32, b"\0")
    data += bytes([status]) + b"\x01" * 32 + struct.pack("<q", 1_790_000_000) + b"\xff"
    return data


def test_account_size_matches_documented_layout():
    assert ACCOUNT_SIZE == 242 == len(_account())


def test_decode_roundtrip():
    d = decode_account(_account())
    assert d["review_id_hash"] == review_id_hash("rev-c-0001")
    assert d["input_hash"] == hashlib.sha256(b"in").hexdigest()
    assert (d["workflow_version"], d["model_version"]) == ("iasx-wf-1.0.0", "extract-rules-1.1.0+mock-jev")
    assert d["status"] == "ATTESTED" and d["attested_at"] == 1_790_000_000


def test_only_technical_fields_are_onchain():
    assert set(decode_account(_account())) == {
        "review_id_hash", "input_hash", "analysis_hash", "reviewed_hash",
        "workflow_version", "model_version", "status", "attested_at",
    }


def test_short_or_unknown_account():
    with pytest.raises(ValueError):
        decode_account(_account()[:100])
    assert decode_account(_account(status=9))["status"] == "UNKNOWN_9"


@pytest.mark.parametrize("url", ["https://api.devnet.solana.com", "https://devnet.helius-rpc.com/?api-key=x"])
def test_devnet_is_accepted(url):
    assert_devnet(url)


@pytest.mark.parametrize(
    "url",
    ["https://api.mainnet-beta.solana.com", "https://api.testnet.solana.com", "http://localhost:8899", "devnet"],
)
def test_other_clusters_are_refused(url):
    with pytest.raises(ValueError):
        assert_devnet(url)
