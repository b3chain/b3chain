#!/usr/bin/env python3
# Copyright (c) 2023 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test validateaddress for main chain"""

from test_framework.test_framework import BitcoinTestFramework

from test_framework.util import assert_equal

INVALID_DATA = [
    # Bad Bech32 checksum
    ("b31qw508d6qejxtdg4y5r3zarvary0c5xw7kee03jq", "Invalid Bech32 checksum", [41]),
    # Version 1 with wrong encoding (Bech32 instead of Bech32m)
    (
        "b31p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqklm3ux",
        "Version 1+ witness address must use Bech32m checksum",
        [],
    ),
    # Version 0 with wrong encoding (Bech32m instead of Bech32)
    (
        "b31qw508d6qejxtdg4y5r3zarvary0c5xw7kv9lah5",
        "Version 0 witness address must use Bech32 checksum",
        [],
    ),
    # Invalid v0 program size (16 bytes)
    (
        "B31QW508D6QEJXTDG4Y5R3ZARVARYVH4DKCG",
        "Invalid Bech32 v0 address program size (16 bytes), per BIP141",
        [],
    ),
    # Invalid v1 program size (1 byte)
    ("b31pqqffguvn", "Invalid Bech32 address program size (1 byte)", []),
    # Invalid v1 program size (41 bytes)
    (
        "b31pqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq3swa09",
        "Invalid Bech32 address program size (41 bytes)",
        [],
    ),
    # Empty Bech32 data section
    ("b31kzmq84", "Empty Bech32 data section", []),
    # Invalid witness version (17)
    (
        "b3130xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqlh3lvg",
        "Invalid Bech32 address witness version",
        [],
    ),
    # Mixed case
    (
        "b31qw508d6qejxtdg4y5r3zarvary0c5xw7kee03jK",
        "Invalid character or mixed case",
        [41],
    ),
    # Wrong HRP (bc1)
    (
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        "Invalid or unsupported Segwit (Bech32) or Base58 encoding.",
        [],
    ),
    # Wrong HRP (tb1)
    (
        "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7",
        "Invalid or unsupported Segwit (Bech32) or Base58 encoding.",
        [],
    ),
    # Wrong HRP (tc1)
    (
        "tc1qw508d6qejxtdg4y5r3zarvary0c5xw7kg3g4ty",
        "Invalid or unsupported Segwit (Bech32) or Base58 encoding.",
        [],
    ),
    # Invalid Base 32 character
    (
        "b31p0xlxvliemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqrrtaey",
        "Invalid Base 32 character",
        [10],
    ),
]
VALID_DATA = [
    (
        "B31QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KEE03JK",
        "0014751e76e8199196d454941c45d1b3a323f1433bd6",
    ),
    (
        "b31qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qedk586",
        "00201863143c14c5166804bd19203356da136c985678cd4d27a1b8c6329604903262",
    ),
    (
        "b31pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7kyf923p",
        "5128751e76e8199196d454941c45d1b3a323f1433bd6751e76e8199196d454941c45d1b3a323f1433bd6",
    ),
    ("b31sw50qjqxddq", "6002751e"),
    ("b31zw508d6qejxtdg4y5r3zarvaryvcrt7ha", "5210751e76e8199196d454941c45d1b3a323"),
    (
        "b31qqqqqp399et2xygdj5xreqhjjvcmzhxw4aywxecjdzew6hylgvses4m76xq",
        "0020000000c4a5cad46221b2a187905e5266362b99d5e91c6ce24d165dab93e86433",
    ),
    (
        "b31pqqqqp399et2xygdj5xreqhjjvcmzhxw4aywxecjdzew6hylgvseslv7n7u",
        "5120000000c4a5cad46221b2a187905e5266362b99d5e91c6ce24d165dab93e86433",
    ),
    (
        "b31p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqrrtaey",
        "512079be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798",
    ),
    # PayToAnchor (P2A)
    (
        "b31pfees2wef3m",
        "51024e73",
    ),
]


class ValidateAddressMainTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.chain = ""  # main
        self.num_nodes = 1
        self.extra_args = [["-prune=899"]] * self.num_nodes

    def check_valid(self, addr, spk):
        info = self.nodes[0].validateaddress(addr)
        assert_equal(info["isvalid"], True)
        assert_equal(info["scriptPubKey"], spk)
        assert "error" not in info
        assert "error_locations" not in info

    def check_invalid(self, addr, error_str, error_locations):
        res = self.nodes[0].validateaddress(addr)
        assert_equal(res["isvalid"], False)
        assert_equal(res["error"], error_str)
        assert_equal(res["error_locations"], error_locations)

    def test_validateaddress(self):
        for (addr, error, locs) in INVALID_DATA:
            self.check_invalid(addr, error, locs)
        for (addr, spk) in VALID_DATA:
            self.check_valid(addr, spk)

    def run_test(self):
        self.test_validateaddress()


if __name__ == "__main__":
    ValidateAddressMainTest(__file__).main()
