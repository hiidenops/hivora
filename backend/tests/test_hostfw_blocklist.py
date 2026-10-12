import ast
from pathlib import Path

import pytest

import hivora.hostfw.blocklist as blocklist
from hivora.core.errors import ValidationError
from hivora.hostfw.blocklist import InvalidAddressError, restore_text, split, valid_address


def test_the_chain_is_emptied_then_refilled_with_one_drop_per_address() -> None:
    addresses = ["203.0.113.24", "2001:db8::7", "198.51.100.3", "203.0.113.24"]
    assert restore_text(addresses, 4) == (
        "*filter\n"
        ":HIVORA-BLOCK - [0:0]\n"
        "-A HIVORA-BLOCK -s 198.51.100.3/32 -j DROP\n"
        "-A HIVORA-BLOCK -s 203.0.113.24/32 -j DROP\n"
        "COMMIT\n"
    )
    assert restore_text(addresses, 6) == (
        "*filter\n:HIVORA-BLOCK - [0:0]\n-A HIVORA-BLOCK -s 2001:db8::7/128 -j DROP\nCOMMIT\n"
    )
    # Nothing blocked: the chain is only emptied (the last unblock).
    assert restore_text([], 4) == "*filter\n:HIVORA-BLOCK - [0:0]\nCOMMIT\n"


def test_addresses_are_split_sorted_and_canonical() -> None:
    assert split(["10.0.0.20", "10.0.0.3", "2001:DB8:0:0::1", "::ffff:192.0.2.9", "10.0.0.3"]) == {
        4: ["10.0.0.3", "10.0.0.20", "192.0.2.9"],  # numeric order; IPv4 seen through IPv6
        6: ["2001:db8::1"],
    }
    assert valid_address("2001:0DB8::0001") == "2001:db8::1"
    assert valid_address("192.168.1.20") == "192.168.1.20"  # the local network: allowed here


@pytest.mark.parametrize("text", [
    "", " ", "1.2.3", "1.2.3.4.5", "256.1.1.1", "01.2.3.4", "203.0.113.0/24", "2001:db8::/64",
    "1.2.3.4 -j ACCEPT", "1.2.3.4\n-A INPUT -j ACCEPT", " 1.2.3.4", "1.2.3.4;", "fe80::1%eth0",
    "0.0.0.0", "::", "127.0.0.1", "127.8.9.1", "::1", "224.0.0.1", "ff02::1", "exemple.fr",
])  # fmt: skip
def test_anything_but_one_blockable_ip_is_refused(text: str) -> None:
    with pytest.raises(InvalidAddressError) as caught:
        valid_address(text)
    assert caught.value.code == "invalid_address"
    assert isinstance(caught.value, ValidationError)
    with pytest.raises(InvalidAddressError):  # and never rendered
        restore_text(["203.0.113.24", text], 4)


def test_the_renderer_does_no_io() -> None:
    tree = ast.parse(Path(blocklist.__file__).read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported == {"ipaddress", "collections.abc", "typing", "hivora.core.errors"}
