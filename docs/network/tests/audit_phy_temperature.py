#!/usr/bin/env python3
"""Audit the pinned C3/S3 temperature replacement in a linked ELF and map.

Requires pyelftools. Reuses the PHY allocation auditor's GNU/LLD parsing,
object-verified mergeable-string exclusion, and earlier source-milestone gates.
Reports addresses and hashes, never input paths or firmware bytes. This checks
link ownership and aliases; it does not establish callback behavior on a device.
This is the full tracking/station profile. Lifetime-only images legitimately
discard tracking helpers and therefore do not satisfy its previous-milestone gate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import audit_phy_allocations as allocations


SUFFIXES = ("decode", "range", "inner", "forward", "outer")
SELECTED = {
    "esp32c3": ("tsens_dac_to_index", "tsens_dac_cal1", "tsens_temp_read1",
                "phy_get_tsens_value", "rom1_tsens_temp_read"),
    "esp32s3": ("tsens_dac_to_index", "tsens_dac_cal_new", "ram_tsens_temp_read_new",
                "phy_get_tsens_value", "ram_tsens_temp_read"),
}
COMMON_FUNCTIONS = ("phy_get_romfunc_addr", "register_chipv7_phy", "phy_wakeup_init",
                    "phy_close_rf", "phy_dig_reg_backup", "phy_xpd_tsens",
                    "phy_set_tsens_power", "get_temp_init")
RETAINED_FUNCTIONS = {
    "esp32c3": COMMON_FUNCTIONS + ("rom2_tsens_read_init1", "rom2_temp_to_power1"),
    "esp32s3": COMMON_FUNCTIONS + ("tsens_read_init_new", "ram_tsens_code_read",
                                 "ram_temp_to_power"),
}
STATE_SIZES = {"esp32c3": 848, "esp32s3": 740}
ROM_REFERENCES = {
    "esp32c3": {"rom_tsens_code_read": 0x40001b04, "rom_code_to_temp": 0x40001b14},
    "esp32s3": {"rom_code_to_temp": 0x40006234},
}
BASELINE = Path(__file__).resolve().parents[1] / "phy-temperature-baseline.json"


def source_names(chip):
    return dict(zip(SELECTED[chip], ("__opensensor_tsens_" + s for s in SUFFIXES)))


def inspect_symbols(elf, names):
    """Keep aliases' symbol sizes separate from actual source-function sizes."""
    table = elf.get_section_by_name(".symtab")
    if table is None:
        raise ValueError("Temperature audit requires .symtab")
    result = {}
    for name in names:
        present = table.get_symbol_by_name(name) or []
        candidates = [s for s in present if s["st_shndx"] != "SHN_UNDEF"]
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous defined symbol {name}")
        if not present:
            result[name] = None
            continue
        # An undefined source symbol still violates the vendor-image gate.
        symbol = candidates[0] if candidates else present[0]
        section = (elf.get_section(symbol["st_shndx"])
                   if isinstance(symbol["st_shndx"], int) else None)
        address, size = symbol["st_value"], symbol["st_size"]
        allocated = bool(section is not None and section["sh_flags"] & 2
                         and section["sh_addr"] <= address
                         < section["sh_addr"] + section["sh_size"])
        contained = bool(allocated and address + size <= section["sh_addr"] + section["sh_size"])
        entry = {"address": hex(address), "symbol_size_bytes": size,
                 "type": symbol["st_info"]["type"], "allocated": allocated,
                 "absolute": symbol["st_shndx"] == "SHN_ABS",
                 "executable": bool(allocated and section["sh_flags"] & 4),
                 "body_contained": contained, "body_sha256": None}
        if contained and size and section["sh_type"] != "SHT_NOBITS":
            offset = address - section["sh_addr"]
            entry["body_sha256"] = hashlib.sha256(section.data()[offset:offset + size]).hexdigest()
        result[name] = entry
    return result


def original_sections(inputs, name):
    # Xtensa may place literals inside .text.<name> or a separate .literal input.
    prefixes = (".text." + name, ".literal." + name)
    return [row for row in inputs if any(row["section"] == prefix
            or row["section"].startswith(prefix + ".") for prefix in prefixes)]


def contains(row, symbol):
    start, address = int(row["address"], 0), int(symbol["address"], 0)
    return start <= address and address + max(1, symbol["symbol_size_bytes"]) <= start + row["size_bytes"]


def overlaps(row, symbol):
    start, address = int(row["address"], 0), int(symbol["address"], 0)
    return start < address + symbol["symbol_size_bytes"] and address < start + row["size_bytes"]


def require_body(symbols, name):
    symbol = symbols.get(name)
    if not (symbol and symbol["allocated"] and symbol["executable"]
            and symbol["body_contained"] and symbol["symbol_size_bytes"] > 0
            and symbol["type"] == "STT_FUNC"):
        raise ValueError(f"Missing allocated function body {name}")
    return symbol


def check_temperature(base, symbols, expected):
    if expected not in ("source", "vendor"):
        raise ValueError("Expected temperature source or vendor")
    chip = base["chip"]
    gate_base = base
    if expected == "source":
        # A linker-script alias may be SHN_ABS even though its destination is
        # an allocated source function. The older auditor only recognizes
        # section-relative symbols; supply this one independently verified
        # destination to its retained-helper gate, preserving every other gate.
        original = SELECTED[chip][-1]
        old, new = symbols.get(original), symbols.get(source_names(chip)[original])
        if (old and old.get("absolute") and new and new["allocated"]
                and new["executable"] and old["address"] == new["address"]):
            gate_base = dict(base)
            gate_base["selected_allocated_symbols"] = dict(base["selected_allocated_symbols"])
            gate_base["selected_allocated_symbols"][original] = {
                "address": new["address"], "size_bytes": new["symbol_size_bytes"]}
    allocations.check_expectations(gate_base, "source", "source", "source")
    phy_inputs = base["allocations"]["libphy.a"]["inputs"]
    for name in RETAINED_FUNCTIONS[chip]:
        symbol = require_body(symbols, name)
        if not any(contains(row, symbol) for row in phy_inputs):
            raise ValueError(f"Retained helper lacks vendor input allocation: {name}")
    for name, size in (("phy_param", STATE_SIZES[chip]), ("g_phyFuns", 4),
                       ("phy_tsens_attribute", 30)):
        symbol = symbols.get(name)
        if not (symbol and symbol["allocated"] and symbol["body_contained"]
                and symbol["symbol_size_bytes"] == size
                and symbol["type"] == "STT_OBJECT"):
            raise ValueError(f"Missing or invalid retained data {name}")
        alignment = 2 if name == "phy_tsens_attribute" else 4
        if int(symbol["address"], 0) % alignment:
            raise ValueError(f"Unaligned retained data {name}")
        if not any(contains(row, symbol) for row in phy_inputs):
            raise ValueError(f"Retained data lacks vendor input allocation: {name}")
    for name, address in ROM_REFERENCES[chip].items():
        symbol = symbols.get(name)
        if not (symbol and symbol.get("absolute") and int(symbol["address"], 0) == address):
            raise ValueError(f"Missing or changed ROM reference symbol {name}")
    for original, source in source_names(chip).items():
        old_inputs = original_sections(phy_inputs, original)
        old, new = symbols.get(original), symbols.get(source)
        if expected == "source":
            if old_inputs:
                raise ValueError(f"Original temperature input still allocated: {original}")
            new = require_body(symbols, source)
            if any(overlaps(row, new) for row in phy_inputs):
                raise ValueError(f"Source body aliases retained vendor input: {source}")
            # GNU ld can retain the old ST_SIZE on these aliases; LLD can set
            # it to zero. Neither describes the replacement body's extent.
            if not (old and (old["allocated"] and old["executable"] or old.get("absolute"))
                    and old["address"] == new["address"]):
                raise ValueError(f"Incorrect temperature source alias: {original}")
        else:
            if new is not None:
                raise ValueError(f"Source temperature symbol in vendor image: {source}")
            old = require_body(symbols, original)
            if not any(contains(row, old) for row in old_inputs):
                raise ValueError(f"Original temperature body lacks input allocation: {original}")


def audit(elf_path, map_path, label, expected):
    from elftools.elf.elffile import ELFFile

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", label):
        raise ValueError("Label must be a simple artifact identifier")
    base = allocations.audit(elf_path, map_path, label, exclude_strings=True)
    chip = base["chip"]
    names = (tuple(source_names(chip)) + tuple(source_names(chip).values())
             + RETAINED_FUNCTIONS[chip] + ("phy_param", "g_phyFuns", "phy_tsens_attribute")
             + tuple(ROM_REFERENCES[chip]))
    with elf_path.open("rb") as stream:
        symbols = inspect_symbols(ELFFile(stream), names)
    check_temperature(base, symbols, expected)
    baseline = json.loads(BASELINE.read_text())["chips"][chip]
    aliases = {}
    for original, source in source_names(chip).items():
        aliases[original] = {
            "address": symbols[original]["address"],
            "alias_symbol_size_bytes": symbols[original]["symbol_size_bytes"],
            "source_symbol": source if expected == "source" else None,
            "body": symbols[source if expected == "source" else original],
            "baseline_vendor_body": baseline["selected_functions"][original],
        }
    phy = base["allocations"]["libphy.a"]
    return {
        "schema": "phy-temperature-allocation-audit-v1", "label": label,
        "chip": chip, "expect_temperature": expected, "checks_passed": True,
        "profile": "full-tracking-station",
        "elf_sha256": base["elf_sha256"], "map_sha256": base["map_sha256"],
        "linker": base["linker"], "method": base["method"],
        "previous_source_gates": {"printf": True, "wrappers": True,
                                  "dispatcher": True, "no_allocated_libpp": True},
        "non_string_allocations": {"libphy_bytes": phy["bytes"],
                                   "phy_tsens_member_bytes": phy["members"].get("phy_tsens.o", 0),
                                   "libphy_member_count": phy["member_count"]},
        "temperature_aliases": aliases,
        "retained_symbols": {name: symbols[name] for name in names
                             if name not in source_names(chip)
                             and name not in source_names(chip).values()},
        "baseline": {"label": baseline["label"], "elf_sha256": baseline["elf_sha256"],
                     "map_sha256": baseline["map_sha256"],
                     "input_archives_observed": baseline["input_archives_observed"]},
        "input_archives_observed": base["input_archives_observed"],
        "allocated_phy_inputs": phy["inputs"],
        "limits": ["Alias ST_SIZE may be stale; body size/hash belong to the named source symbol.",
                   "Baseline hashes identify the reference image; relocated vendor bodies need not hash identically.",
                   "ROM reference symbols identify veneers, not measured live callback-table contents.",
                   "Input ownership and symbol routing do not prove source semantics, live callbacks or RF behavior."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--expect-temperature", choices=("source", "vendor"), required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.elf, args.map, args.label, args.expect_temperature), indent=2))


if __name__ == "__main__":
    main()
