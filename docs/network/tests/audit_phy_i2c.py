#!/usr/bin/env python3
"""Audit staged I2C source replacement with all previous PHY source gates.

This is the full tracking/station profile. ``flash`` replaces four flash
helpers while retaining the original IRAM implementation; ``source`` requires
complete allocated phy_i2c.o removal. Hashes and addresses are public-safe;
the report does not expose paths, firmware strings, or callback table bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import audit_phy_allocations as allocations
import audit_phy_lifecycle as lifecycle
import audit_phy_pbus as pbus
import audit_phy_temperature as temperature


FLASH = {
    "phy_get_i2c_data": "__opensensor_i2c_get_data",
    "bias_reg_set": "__opensensor_i2c_bias",
    "i2c_bbpll_set": "__opensensor_i2c_bbpll",
    "phy_i2c_init2": "__opensensor_i2c_init2",
}
IRAM_COMMON = {
    "phy_i2c_enter_critical": "__opensensor_i2c_enter",
    "phy_i2c_exit_critical": "__opensensor_i2c_exit",
    "phy_i2c_bbtop_wakeup": "__opensensor_i2c_wakeup",
}
IRAM = {
    "esp32c3": {
        **IRAM_COMMON,
        "bias_dreg_i2c_set": "__opensensor_i2c_bias_dreg",
        "rom1_get_i2c_hostid": "__opensensor_i2c_hostid",
        "rom1_chip_i2c_readReg": "__opensensor_i2c_read",
        "rom1_chip_i2c_writeReg": "__opensensor_i2c_write",
        "rom1_phy_i2c_init1": "__opensensor_i2c_init1",
    },
    "esp32s3": {
        **IRAM_COMMON,
        "ram_set_txcap_reg": "__opensensor_i2c_txcap",
        "ram_get_i2c_hostid": "__opensensor_i2c_hostid",
        "ram_chip_i2c_readReg": "__opensensor_i2c_read",
        "ram_chip_i2c_writeReg": "__opensensor_i2c_write",
        "ram_phy_i2c_init1": "__opensensor_i2c_init1",
    },
}
LOCAL_PARTIAL = "bias_dreg_i2c_set.part.0"
PROGRAM = "__opensensor_i2c_program"
PROGRAM_BYTES = bytes([107] * 10 + [1, 2, 3, 4, 5, 6, 7, 8, 10, 11]
                      + [98, 98, 98, 98, 98, 98, 99, 100, 100, 103]
                      + [3, 8, 10, 9, 4, 0, 1, 8, 4, 2])
PROGRAM_HASH = hashlib.sha256(PROGRAM_BYTES).hexdigest()
ALL_SOURCE_NAMES = set(FLASH.values()) | set(IRAM["esp32c3"].values()) | set(IRAM["esp32s3"].values())
ROM_NAMES = (
    "rom_get_i2c_read_mask", "rom_get_i2c_mst0_mask", "rom_enter_critical_phy",
    "rom_exit_critical_phy", "rom_chip_i2c_readReg_org", "rom_i2c_paral_write_num",
    "rom_i2c_readReg", "rom_i2c_readReg_Mask", "rom_i2c_writeReg",
    "rom_i2c_writeReg_Mask", "rom_i2c_sar2_init_code", "rom_set_txcap_reg",
)
ROM_REFERENCES = {
    "esp32c3": dict(zip(ROM_NAMES, (
        0x40001948, 0x40001ac4, 0x40001acc, 0x40001ad0, 0x40001ad4, 0x40001ae8,
        0x40001954, 0x40001958, 0x4000195c, 0x40001960, 0x40001be0, 0x400019f4))),
    "esp32s3": dict(zip(ROM_NAMES, (
        0x40005d30, 0x40006144, 0x4000615c, 0x40006168, 0x40006174, 0x400061b0,
        0x40005d48, 0x40005d54, 0x40005d60, 0x40005d6c, 0x40006318, 0x40005f28))),
}
BASELINE = {
    "esp32c3": {
        "elf_sha256": "4b4d3fa5c45004c32e4222995d0cc0f7d5910602a45a1b83823e037582c7650c",
        "map_sha256": "7e00ced0b556ba5e32e1c21e590f0a663c6ddbf9d4a72261abb38c52c5a1ad48",
        "i2c_bytes": 2418, "iram_input_bytes": 1086, "flash_input_bytes": 1332,
    },
    "esp32s3": {
        "elf_sha256": "9aa521977d0c38a44b86aa3f35fd16543acd7757444d01318c6245e8bc5ee84f",
        "map_sha256": "c3e62ef53738f80086bf7da1d924f5690c2ac82df31827b8f7cc85184f52b641",
        "i2c_bytes": 1985, "iram_input_bytes": 970, "flash_input_bytes": 1015,
    },
}


def in_iram(body):
    start = int(body["address"], 0)
    return 0x40370000 <= start < start + body["symbol_size_bytes"] <= 0x403e0000


def check_i2c(base, symbols, expected, attribute_hash):
    if expected not in ("vendor", "flash", "source"):
        raise ValueError("Expected I2C vendor, flash, or source")
    pbus.check_pbus(base, symbols, "source", attribute_hash)
    chip = base["chip"]
    inputs = base["allocations"]["libphy.a"]["inputs"]
    member_inputs = [row for row in inputs if row["member"] == "phy_i2c.o"]
    selected = {**FLASH, **IRAM[chip]}
    source_selected = {} if expected == "vendor" else FLASH if expected == "flash" else selected
    allowed_source = set(source_selected.values())
    for name in ALL_SOURCE_NAMES - allowed_source:
        if symbols.get(name) is not None:
            raise ValueError(f"Unexpected I2C source symbol in {expected} stage: {name}")

    if expected == "source":
        if member_inputs:
            raise ValueError("I2C member phy_i2c.o still has allocated inputs")
        if any(row["member"] == "phy_i2c.o" and row["reported_input_bytes"]
               for row in base.get("excluded_mergeable_string_inputs", [])):
            raise ValueError("I2C member still has excluded mergeable string input")
        if symbols.get(LOCAL_PARTIAL) is not None:
            raise ValueError("Original I2C local partial still present")
        program = symbols.get(PROGRAM)
        if not (program and program.get("allocated") and not program.get("absolute")
                and not program.get("executable") and program.get("body_contained")
                and program.get("type") == "STT_OBJECT" and program.get("symbol_size_bytes") == 40):
            raise ValueError("Missing allocated 40-byte I2C source program table")
        address = int(program["address"], 0)
        if not 0x3fc80000 <= address < address + 40 <= 0x3fce0000:
            raise ValueError("I2C source program table must reside in internal DRAM")
        if program.get("body_sha256") != PROGRAM_HASH:
            raise ValueError("I2C source program table differs from pinned original program")
        if any(temperature.overlaps(row, program) for row in inputs):
            raise ValueError("I2C source program table overlaps vendor input")
    elif symbols.get(PROGRAM) is not None:
        raise ValueError("Unexpected I2C source program table before whole-member stage")

    for original, source in selected.items():
        if original in source_selected:
            new = temperature.require_body(symbols, source)
            if not lifecycle.alias_matches(symbols.get(original), new, executable=True):
                raise ValueError(f"Incorrect I2C source alias: {original}")
            if any(temperature.overlaps(row, new) for row in inputs):
                raise ValueError(f"I2C source body overlaps vendor input: {source}")
            if temperature.original_sections(inputs, original):
                raise ValueError(f"Original I2C function input still allocated: {original}")
            if original in IRAM[chip] and not in_iram(new):
                raise ValueError(f"Source I2C routine is outside IRAM: {source}")
        else:
            old = temperature.require_body(symbols, original)
            rows = (temperature.original_sections(member_inputs, original) if original in FLASH
                    else [row for row in member_inputs if row["section"] == ".iram1"])
            if not any(temperature.contains(row, old) for row in rows):
                raise ValueError(f"Original I2C body lacks member input allocation: {original}")
            if original in IRAM[chip] and not in_iram(old):
                raise ValueError(f"Original I2C routine is outside IRAM: {original}")

    if expected != "source" and chip == "esp32c3":
        local = temperature.require_body(symbols, LOCAL_PARTIAL)
        if not any(row["section"] == ".iram1" and temperature.contains(row, local)
                   for row in member_inputs):
            raise ValueError("Retained I2C local partial lacks member IRAM ownership")
    for name, address in ROM_REFERENCES[chip].items():
        value = symbols.get(name)
        if not (value and value.get("absolute") and int(value["address"], 0) == address):
            raise ValueError(f"Missing or changed I2C ROM reference: {name}")


def audit(elf_path, map_path, label, expected):
    from elftools.elf.elffile import ELFFile

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", label):
        raise ValueError("Label must be a simple artifact identifier")
    base = allocations.audit(elf_path, map_path, label, exclude_strings=True)
    chip = base["chip"]
    prior = lifecycle.source_names(chip)
    names = set(prior) | set(prior.values())
    names.update(temperature.RETAINED_FUNCTIONS[chip])
    names.update(temperature.ROM_REFERENCES[chip])
    names.update(("phy_param", "g_phyFuns", "phy_tsens_attribute", lifecycle.SOURCE_TABLE))
    names.update(pbus.SELECTED[chip])
    names.update(pbus.ALL_SOURCE_NAMES)
    names.update(pbus.RETAINED_FUNCTIONS)
    names.update(pbus.ROM_REFERENCES[chip])
    names.update(FLASH)
    names.update(IRAM[chip])
    names.update(ALL_SOURCE_NAMES)
    names.update(ROM_REFERENCES[chip])
    names.add(LOCAL_PARTIAL)
    names.add(PROGRAM)
    with elf_path.open("rb") as stream:
        symbols = temperature.inspect_symbols(ELFFile(stream), sorted(names))
    oracle = json.loads(lifecycle.ORACLE.read_text())["chips"][chip]
    attribute_hash = hashlib.sha256(bytes(oracle["attribute_bytes"])).hexdigest()
    check_i2c(base, symbols, expected, attribute_hash)
    phy = base["allocations"]["libphy.a"]
    member_inputs = [row for row in phy["inputs"] if row["member"] == "phy_i2c.o"]
    return {
        "schema": "phy-i2c-allocation-audit-v1", "label": label, "chip": chip,
        "expect_i2c": expected, "checks_passed": True, "profile": "full-tracking-station",
        "elf_sha256": base["elf_sha256"], "map_sha256": base["map_sha256"],
        "linker": base["linker"], "method": base["method"],
        "baseline": {"label": "pbus-source-v2-sta_smoke", **BASELINE[chip]},
        "previous_source_gates": {"printf": True, "wrappers": True, "dispatcher": True,
                                  "temperature": True, "sensor_lifecycle": True,
                                  "pbus": True, "no_allocated_libpp": True},
        "non_string_allocations": {
            "libphy_bytes": phy["bytes"], "libphy_member_count": phy["member_count"],
            "phy_i2c_member_bytes": phy["members"].get("phy_i2c.o", 0),
            "phy_i2c_iram_input_bytes": sum(row["size_bytes"] for row in member_inputs
                                            if row["section"] == ".iram1"),
            "phy_tsens_member_bytes": phy["members"].get("phy_tsens.o", 0),
            "phy_pbus_member_bytes": phy["members"].get("phy_pbus.o", 0),
        },
        "selected_symbols": {old: {"original_or_alias": symbols[old], "source_symbol": new,
                                    "source_body": symbols[new], "requires_iram": old in IRAM[chip]}
                             for old, new in {**FLASH, **IRAM[chip]}.items()},
        "original_local_partial": symbols[LOCAL_PARTIAL],
        "source_program_table": symbols[PROGRAM],
        "retained_i2c_rom_dependencies": {name: symbols[name] for name in ROM_REFERENCES[chip]},
        "input_archives_observed": base["input_archives_observed"],
        "allocated_phy_inputs": phy["inputs"],
        "limits": ["This is ownership evidence for this linked image, not every archive consumer.",
                   "Alias sizes may be stale; source body sizes are checked separately.",
                   "Flash stage retains the complete shared original I2C IRAM input.",
                   "C3 TXCAP remains ROM-bound; its unreferenced vendor body shares the old IRAM input.",
                   "Function placement checks do not establish literal or transitive callee placement.",
                   "ROM reference symbols do not prove live callback table contents.",
                   "This audit does not establish MMIO ordering, callback ABI, timing, or device behavior."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--expect-i2c", choices=("vendor", "flash", "source"), required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.elf, args.map, args.label, args.expect_i2c), indent=2))


if __name__ == "__main__":
    main()
