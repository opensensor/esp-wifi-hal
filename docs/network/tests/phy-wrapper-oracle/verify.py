#!/usr/bin/env python3
"""Replay the four audited wrapper instruction ranges, stopping at call boundaries.

This is a deliberately bounded instruction interpreter, not a PHY emulator.
The immutable fixture contains only selected instructions and one address
literal, never firmware, calibration contents, network data or credentials.
"""
import hashlib
import json
from pathlib import Path
import re
import unittest


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(function):
    start = int(function["address"], 0)
    expected = start
    code = bytearray()
    decoded = []
    for line in function["instructions"]:
        match = re.fullmatch(r"([0-9a-f]+): ([0-9a-f]+) (\S+) (.*)|([0-9a-f]+): ([0-9a-f]+) (\S+)", line)
        require(match is not None, "Malformed instruction")
        if match[1] is not None:
            address, raw, op, args = match.group(1, 2, 3, 4)
        else:
            address, raw, op = match.group(5, 6, 7)
            args = ""
        require(len(raw) in (4, 6, 8), "Unexpected instruction width")
        width = len(raw) // 2
        require(int(address, 16) == expected, "Instruction coverage gap")
        expected += width
        code.extend(int(raw, 16).to_bytes(width, "little"))
        decoded.append((op, [arg.strip() for arg in args.split(",") if arg.strip()]))
    require(len(code) == function["size_bytes"], "Function size differs")
    require(code.hex() == function["code_hex"], "Decoded bytes differ")
    require(hashlib.sha256(code).hexdigest() == function["instruction_bytes_sha256"], "Code hash differs")
    return decoded


def replay(chip, evidence, name, first, second=0, seed=0):
    """Return only externally visible byte writes and outbound call arguments.

    ENTRY/RETW register-window housekeeping is abstracted. CALL8's outgoing
    a10/a11 become the callee's a2/a3. The RAM callee is never executed: the
    result establishes the wrapper boundary, not the callee's behavior.
    """
    functions = evidence["functions"]
    parameter = functions["phy_param"]
    base = int(parameter["address"], 0)
    size = parameter["size_bytes"]
    memory = bytearray((seed + index * 37) & 255 for index in range(size + 32))
    before = bytes(memory)
    registers = {f"a{i}": 0 for i in range(16)}
    if chip == "esp32c3":
        registers.update(a0=first, a1=second, a5=0)
    elif chip == "esp32s3":
        registers.update(a2=first, a3=second)
    else:
        raise ValueError("Unsupported chip")
    trace = []
    instructions = decode(functions[name])
    returned = False
    for index, (op, args) in enumerate(instructions):
        require(not returned, "Instruction after return")
        if op == "entry":
            require(chip == "esp32s3" and index == 0 and args == ["a1", "32"], "Unexpected register window")
        elif op == "lui":
            require(chip == "esp32c3" and len(args) == 2, "Unexpected LUI")
            registers[args[0]] = (int(args[1], 0) << 12) & 0xffffffff
        elif op == "l32r":
            require(chip == "esp32s3" and len(args) == 2, "Unexpected literal read")
            address = int(args[1], 16)
            require(hex(address) in evidence["literals"], "Unrecorded literal")
            registers[args[0]] = int(evidence["literals"][hex(address)], 0)
        elif op == "addmi":
            require(chip == "esp32s3" and len(args) == 3, "Unexpected ADDMI")
            registers[args[0]] = (registers[args[1]] + int(args[2], 0)) & 0xffffffff
        elif op == "extui":
            require(chip == "esp32s3" and len(args) == 4, "Unexpected EXTUI")
            shift, bits = int(args[2], 0), int(args[3], 0)
            require(0 <= shift < 32 and 1 <= bits <= 16, "Invalid bit extraction")
            registers[args[0]] = (registers[args[1]] >> shift) & ((1 << bits) - 1)
        elif op in ("sb", "s8i"):
            if op == "sb":
                require(chip == "esp32c3" and len(args) == 2, "Unexpected SB")
                match = re.fullmatch(r"(-?\d+)\((a\d+)\)", args[1])
                require(match is not None, "Invalid store address")
                address = registers[match[2]] + int(match[1])
            else:
                require(chip == "esp32s3" and len(args) == 3, "Unexpected S8I")
                address = registers[args[1]] + int(args[2], 0)
            require(base <= address < base + size, "Store outside phy_param")
            value = registers[args[0]] & 255
            memory[address - base + 16] = value
            trace.append(("write8", address - base, value))
        elif op in ("j", "call8"):
            require(len(args) == 1 and int(args[0], 16) == int(functions["ram_tx_pwctrl_background"]["address"], 0), "Unexpected call boundary")
            require((chip == "esp32c3" and op == "j") or (chip == "esp32s3" and op == "call8"), "Wrong call ABI")
            pair = (registers["a0"], registers["a1"]) if op == "j" else (registers["a10"], registers["a11"])
            trace.append(("call", *pair))
            returned = op == "j"
        elif op in ("ret", "retw.n"):
            require(not args and ((chip == "esp32c3" and op == "ret") or (chip == "esp32s3" and op == "retw.n")), "Wrong return ABI")
            returned = True
        else:
            raise ValueError(f"Unsupported instruction: {op}")
    require(returned, "No return/call boundary")
    writes = [item for item in trace if item[0] == "write8"]
    changed = {index for index, pair in enumerate(zip(before, memory)) if pair[0] != pair[1]}
    require(changed <= {offset + 16 for _, offset, _ in writes}, "Unexpected memory mutation")
    require(memory[:16] == before[:16] and memory[-16:] == before[-16:], "Neighbor guard changed")
    return trace


def verify(fixture):
    report = {}
    for chip, evidence in fixture["chips"].items():
        tx_digest, usb_digest = hashlib.sha256(), hashlib.sha256()
        for first in range(256):
            for second in range(256):
                trace = replay(chip, evidence, "tx_pwctrl_background", first, second)
                require(trace == [("call", first, second)], "TX contract mismatch")
                tx_digest.update(bytes(trace[0][1:]))
        offset = {"esp32c3": 0x323, "esp32s3": 0x2a6}[chip]
        for seed in (0, 0x55, 0xaa, 0xff):
            for enabled in range(256):
                trace = replay(chip, evidence, "phy_bbpll_en_usb", enabled, seed=seed)
                require(trace == [("write8", offset, enabled)], "USB contract mismatch")
                usb_digest.update(offset.to_bytes(2, "little") + bytes([enabled]))
        report[chip] = {
            "tx_valid_u8_pairs": 65536,
            "tx_argument_trace_sha256": tx_digest.hexdigest(),
            "usb_instruction_byte_cases": 1024,
            "usb_write_trace_sha256": usb_digest.hexdigest(),
            "usb_source_bool_domain": [0, 1],
            "usb_store_offset": hex(offset),
            "parameter_size": evidence["functions"]["phy_param"]["size_bytes"],
        }
    return report


class RejectMalformedEvidence(unittest.TestCase):
    def setUp(self):
        self.evidence = json.loads(Path(__file__).with_name("original-instructions.json").read_text())["chips"]["esp32s3"]

    def test_missing_literal(self):
        self.evidence["literals"] = {}
        with self.assertRaisesRegex(ValueError, "Unrecorded literal"):
            replay("esp32s3", self.evidence, "phy_bbpll_en_usb", 1)

    def test_store_out_of_bounds(self):
        self.evidence["functions"]["phy_param"]["size_bytes"] = 0x2a6
        with self.assertRaisesRegex(ValueError, "outside phy_param"):
            replay("esp32s3", self.evidence, "phy_bbpll_en_usb", 1)

    def test_wrong_call(self):
        self.evidence["functions"]["ram_tx_pwctrl_background"]["address"] = "0x42000000"
        with self.assertRaisesRegex(ValueError, "Unexpected call boundary"):
            replay("esp32s3", self.evidence, "tx_pwctrl_background", 1)

    def test_corrupt_bytes(self):
        self.evidence["functions"]["tx_pwctrl_background"]["code_hex"] = "00"
        with self.assertRaisesRegex(ValueError, "Decoded bytes differ"):
            replay("esp32s3", self.evidence, "tx_pwctrl_background", 1)

    def test_s3_narrows_registers_but_c3_valid_domain_is_u8(self):
        self.assertEqual(replay("esp32s3", self.evidence, "tx_pwctrl_background", 0xffffffff, 0x100), [("call", 255, 0)])


if __name__ == "__main__":
    root = Path(__file__).parent
    fixture = json.loads((root / "original-instructions.json").read_text())
    result = verify(fixture)
    expected = json.loads((root / "expected-results.json").read_text())
    require(result == expected, "Exhaustive trace summary changed")
    print(json.dumps(result, indent=2))
    unittest.main(argv=[__file__])
