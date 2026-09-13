#!/usr/bin/env python3
"""Audit PBUS source replacement while retaining the previous PHY milestones.

This is the full tracking/station profile, not a lifetime-only image profile.
Requires pyelftools and the existing allocation/lifecycle audit dependencies.
The source gate requires complete allocated phy_pbus.o removal, including its
constants and jump tables. Reports contain hashes and addresses, not paths or
firmware bytes. ROM symbol checks do not prove live callback table contents.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import audit_phy_allocations as allocations
import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature


COMMON = {
    "txcal_debuge_mode": "__opensensor_pbus_debug_mode",
    "txcal_work_mode": "__opensensor_pbus_work_mode",
    "save_pbus_reg": "__opensensor_pbus_save",
    "set_pbus_mem": "__opensensor_pbus_mem",
}
SELECTED = {
    "esp32c3": {"ram_pbus_force_mode": "__opensensor_pbus_force_mode", **COMMON},
    "esp32s3": COMMON,
}
ALL_SOURCE_NAMES = set(SELECTED["esp32c3"].values())
RETAINED_FUNCTIONS = ("stop_tx_tone", "bb_init")
ROM_NAMES = ("rom_set_txclk_en", "rom_pbus_debugmode", "rom_pbus_xpd_tx_on",
             "rom_txbbgain_to_index", "rom_pbus_set_dco", "rom_en_pwdet",
             "rom_pbus_xpd_rx_on", "rom_pbus_workmode", "rom_pbus_force_mode",
             "ets_delay_us")
ROM_REFERENCES = {
    "esp32c3": dict(zip(ROM_NAMES, (0x400019f8, 0x40001980, 0x400019b0, 0x40001a0c,
                                   0x40001998, 0x40001938, 0x400019a8, 0x400019a0,
                                   0x40001984, 0x40000050))),
    "esp32s3": dict(zip(ROM_NAMES, (0x40005f34, 0x40005dcc, 0x40005e5c, 0x40005f70,
                                   0x40005e14, 0x40005d00, 0x40005e44, 0x40005e2c,
                                   0x40005dd8, 0x40000600))),
}
BASELINE = {
    "esp32c3": {
        "elf_sha256": "94d293f3f92198d713ee78317aaa11ced2857abe04d2a9a6f3ef51b96da1ddf5",
        "map_sha256": "b4162bc67f3308dceee25aae8dae99330259abe3f5aa59b303d5f1bd100052d6",
        "pbus_bytes": 1090,
    },
    "esp32s3": {
        "elf_sha256": "31803a8df90fefc3e6d24f33bb8a55f20eb13b062e0444127e94abd31a51c309",
        "map_sha256": "4828fdb66528a83048e442b7a2687667f255274164973982fef3ef0598d95aec",
        "pbus_bytes": 972,
    },
}


def check_pbus(base, symbols, expected, attribute_hash):
    if expected not in ("source", "vendor"):
        raise ValueError("Expected PBUS source or vendor")
    lifecycle.check_lifecycle(base, symbols, "lifecycle", attribute_hash)
    chip = base["chip"]
    inputs = base["allocations"]["libphy.a"]["inputs"]
    pbus_inputs = [row for row in inputs if row["member"] == "phy_pbus.o"]
    if expected == "source":
        if pbus_inputs:
            raise ValueError("PBUS member phy_pbus.o still has allocated inputs")
        if any(row["member"] == "phy_pbus.o" and row["reported_input_bytes"]
               for row in base.get("excluded_mergeable_string_inputs", [])):
            raise ValueError("PBUS member still has excluded mergeable string input")
        for original, source in SELECTED[chip].items():
            new = temperature.require_body(symbols, source)
            if not lifecycle.alias_matches(symbols.get(original), new, executable=True):
                raise ValueError(f"Incorrect PBUS source alias: {original}")
            if any(temperature.overlaps(row, new) for row in inputs):
                raise ValueError(f"PBUS source body overlaps vendor input: {source}")
            if temperature.original_sections(inputs, original):
                raise ValueError(f"Original PBUS function input still allocated: {original}")
        if chip == "esp32s3" and symbols.get("__opensensor_pbus_force_mode") is not None:
            raise ValueError("S3 force mode must remain a ROM dependency")
    else:
        if any(symbols.get(name) is not None for name in ALL_SOURCE_NAMES):
            raise ValueError("Source PBUS symbol present in vendor PBUS image")
        for original in SELECTED[chip]:
            old = temperature.require_body(symbols, original)
            rows = temperature.original_sections(pbus_inputs, original)
            if not any(temperature.contains(row, old) for row in rows):
                raise ValueError(f"Original PBUS body lacks member input allocation: {original}")
        for section, size in ((".rodata", 68 if chip == "esp32c3" else 88),
                              (".rodata.set_pbus_mem", 40)):
            rows = [row for row in pbus_inputs if row["section"] == section]
            if len(rows) != 1 or rows[0]["size_bytes"] != size:
                raise ValueError(f"Missing or changed vendor PBUS table input: {section}")
    for name in RETAINED_FUNCTIONS:
        symbol = temperature.require_body(symbols, name)
        if not any(temperature.contains(row, symbol) for row in inputs):
            raise ValueError(f"Retained PBUS helper lacks vendor input: {name}")
    for name, address in ROM_REFERENCES[chip].items():
        symbol = symbols.get(name)
        if not (symbol and symbol.get("absolute") and int(symbol["address"], 0) == address):
            raise ValueError(f"Missing or changed PBUS ROM reference: {name}")


def audit(elf_path, map_path, label, expected):
    from elftools.elf.elffile import ELFFile

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", label):
        raise ValueError("Label must be a simple artifact identifier")
    base = allocations.audit(elf_path, map_path, label, exclude_strings=True)
    chip = base["chip"]
    prior_names = lifecycle.source_names(chip)
    names = set(prior_names) | set(prior_names.values())
    names.update(temperature.RETAINED_FUNCTIONS[chip])
    names.update(temperature.ROM_REFERENCES[chip])
    names.update(("phy_param", "g_phyFuns", "phy_tsens_attribute", lifecycle.SOURCE_TABLE))
    names.update(SELECTED[chip])
    names.update(ALL_SOURCE_NAMES)
    names.update(RETAINED_FUNCTIONS)
    names.update(ROM_REFERENCES[chip])
    with elf_path.open("rb") as stream:
        symbols = temperature.inspect_symbols(ELFFile(stream), sorted(names))
    oracle = json.loads(lifecycle.ORACLE.read_text())["chips"][chip]
    attribute_hash = hashlib.sha256(bytes(oracle["attribute_bytes"])).hexdigest()
    check_pbus(base, symbols, expected, attribute_hash)
    phy = base["allocations"]["libphy.a"]
    return {
        "schema": "phy-pbus-allocation-audit-v1", "label": label, "chip": chip,
        "expect_pbus": expected, "checks_passed": True, "profile": "full-tracking-station",
        "elf_sha256": base["elf_sha256"], "map_sha256": base["map_sha256"],
        "linker": base["linker"], "method": base["method"],
        "baseline": {"label": "source-v2-sta_smoke", **BASELINE[chip]},
        "previous_source_gates": {"printf": True, "wrappers": True, "dispatcher": True,
                                  "temperature": True, "sensor_lifecycle": True,
                                  "no_allocated_libpp": True},
        "non_string_allocations": {"libphy_bytes": phy["bytes"],
                                   "phy_pbus_member_bytes": phy["members"].get("phy_pbus.o", 0),
                                   "phy_tsens_member_bytes": phy["members"].get("phy_tsens.o", 0),
                                   "libphy_member_count": phy["member_count"]},
        "selected_symbols": {old: {"original_or_alias": symbols[old],
                                    "source_symbol": new, "source_body": symbols[new]}
                             for old, new in SELECTED[chip].items()},
        "retained_pbus_dependencies": {name: symbols[name] for name in
                                       (*RETAINED_FUNCTIONS, *ROM_REFERENCES[chip])},
        "input_archives_observed": base["input_archives_observed"],
        "allocated_phy_inputs": phy["inputs"],
        "limits": ["This is ownership evidence for this linked image, not every archive consumer.",
                   "Alias symbol sizes may be stale; source bodies are checked separately.",
                   "ROM reference symbols do not prove the initialized callback table contents.",
                   "S3 force-mode behavior remains in ROM; it is not part of this source replacement.",
                   "The source gate does not establish MMIO semantics, timing or device behavior."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--expect-pbus", choices=("source", "vendor"), required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.elf, args.map, args.label, args.expect_pbus), indent=2))


if __name__ == "__main__":
    main()
