#!/usr/bin/env python3
"""Audit the temperature-only or complete sensor-member replacement stage.

The temperature stage preserves the previous strict tracking/station gates.
The lifecycle stage additionally requires every allocated phy_tsens.o input,
including its table, to disappear. Source routing of phy_xpd_tsens is checked
separately: its original shared phy_api.o .iram1 input can remain allocated.
Reports contain addresses and hashes, never input paths or firmware bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import audit_phy_allocations as allocations
import audit_phy_temperature as temperature
import phy_init_ownership as init_ownership


LIFECYCLE = {
    "esp32c3": {
        "phy_set_tsens_power": "__opensensor_tsens_power",
        "rom2_tsens_read_init1": "__opensensor_tsens_init",
        "rom2_temp_to_power1": "__opensensor_tsens_temp_to_power",
        "get_temp_init": "__opensensor_tsens_get_init",
        "phy_xpd_tsens": "__opensensor_tsens_xpd",
    },
    "esp32s3": {
        "phy_set_tsens_power": "__opensensor_tsens_power",
        "tsens_read_init_new": "__opensensor_tsens_init",
        "ram_tsens_code_read": "__opensensor_tsens_code",
        "ram_temp_to_power": "__opensensor_tsens_temp_to_power",
        "get_temp_init": "__opensensor_tsens_get_init",
        "phy_xpd_tsens": "__opensensor_tsens_xpd",
    },
}
SOURCE_TABLE = "__opensensor_tsens_attribute"
RETAINED_FUNCTIONS = ("phy_get_romfunc_addr", "register_chipv7_phy", "phy_wakeup_init",
                      "phy_close_rf", "phy_dig_reg_backup")
ORACLE = Path(__file__).resolve().parent / "phy-temperature-oracle" / "original-instructions.json"
BASELINE_HASHES = {
    "esp32c3": {
        "elf_sha256": "a0c62d67f74850d183dcb61a430fd2843307d210a8a4836b44cffa31a864424a",
        "map_sha256": "68d727cff45f81dead925d358c596864370aef300378102e4402d631f7c4eb23",
    },
    "esp32s3": {
        "elf_sha256": "b817a8e019f7a9e300c604d37d69cb83510f125a8aaa23af9d925faa028e159a",
        "map_sha256": "3adfe16eb7ab3209385869c315d08c82ad2b346fbe5584bdef80dd7af93bd769",
    },
}


def source_names(chip):
    return {**temperature.source_names(chip), **LIFECYCLE[chip]}


def alias_matches(alias, source, executable):
    return bool(alias and source and alias["address"] == source["address"]
                and (alias.get("absolute") or alias["allocated"]
                     and (not executable or alias["executable"])))


def check_aliases(base, symbols, names):
    inputs = base["allocations"]["libphy.a"]["inputs"]
    for original, source in names.items():
        new = temperature.require_body(symbols, source)
        if not alias_matches(symbols.get(original), new, executable=True):
            raise ValueError(f"Incorrect lifecycle source alias: {original}")
        if any(temperature.overlaps(row, new) for row in inputs):
            raise ValueError(f"Source body overlaps vendor input: {source}")
        # xpd shares phy_api.o .iram1 with unrelated retained functions. It
        # cannot be claimed absent solely from alias routing or section GC.
        if original != "phy_xpd_tsens" and temperature.original_sections(inputs, original):
            raise ValueError(f"Original sensor function input still allocated: {original}")


API_REPLACEMENTS = {"phy_wakeup_init": "__opensensor_api_wakeup",
                    "phy_close_rf": "__opensensor_api_close"}
FEATURE_REPLACEMENTS = {"phy_dig_reg_backup": "__opensensor_feature_dig"}


def check_lifecycle(base, symbols, stage, table_sha256, *, api_source=False, feature_source=False, init_source=False):
    if stage not in ("temperature", "lifecycle"):
        raise ValueError("Expected stage temperature or lifecycle")
    if feature_source and not api_source:
        raise ValueError("Feature replacement requires complete API source")
    if init_source and (stage!="lifecycle" or not api_source or not feature_source):
        raise ValueError("Initialization replacement requires full lifecycle/API/feature source")
    chip = base["chip"]
    if stage == "temperature":
        if api_source:
            raise ValueError("API replacement requires complete sensor lifecycle source")
        temperature.check_temperature(base, symbols, "source")
        if any(symbols.get(name) is not None for name in (*LIFECYCLE[chip].values(), SOURCE_TABLE)):
            raise ValueError("Lifecycle source symbol present in temperature-only stage")
        return

    inputs = base["allocations"]["libphy.a"]["inputs"]
    if any(row["member"] == "phy_tsens.o" for row in inputs):
        raise ValueError("Sensor member phy_tsens.o still has allocated inputs")
    if any(row["member"] == "phy_tsens.o" and row["reported_input_bytes"]
           for row in base.get("excluded_mergeable_string_inputs", [])):
        raise ValueError("Sensor member still has excluded mergeable string input")
    check_aliases(base, symbols, source_names(chip))
    # Both supported chips execute internal instruction RAM in the 0x403...
    # window. This is a placement gate, not proof that callees or literal
    # loads are also safe with the flash cache disabled.
    xpd = symbols["__opensensor_tsens_xpd"]
    xpd_address = int(xpd["address"], 0)
    if not (0x40300000 <= xpd_address
            and xpd_address + xpd["symbol_size_bytes"] <= 0x40400000):
        raise ValueError("Source xpd body is not contained in instruction RAM")

    # The older tracking audit recognizes section-relative symbols only.
    # Supply the independently checked source destination for its outer alias
    # if the new linker represents that alias as SHN_ABS instead.
    gate_base = dict(base)
    gate_base["selected_allocated_symbols"] = dict(base["selected_allocated_symbols"])
    outer = temperature.SELECTED[chip][-1]
    new_outer = symbols[temperature.source_names(chip)[outer]]
    gate_base["selected_allocated_symbols"][outer] = {
        "address": new_outer["address"], "size_bytes": new_outer["symbol_size_bytes"]}
    if init_source:
        for old in ("phy_get_romfunc_addr","register_chipv7_phy"):
            body=init_ownership.function(base,symbols,old)
            gate_base["selected_allocated_symbols"][old]={"address":body["address"],"size_bytes":body["symbol_size_bytes"]}
        for old in init_ownership.DATA:
            body=init_ownership.state(base,symbols,old)
            gate_base["selected_allocated_symbols"][old]={"address":body["address"],"size_bytes":body["symbol_size_bytes"]}
    allocations.check_expectations(gate_base, "source", "source", "source")

    # Later API and feature stages replace explicitly named vendor helpers.
    # Verify real source bodies and aliases before exempting those helpers
    # from vendor ownership; standalone earlier-stage checks remain strict.
    replacements = dict(API_REPLACEMENTS) if api_source else {}
    if feature_source:
        replacements.update(FEATURE_REPLACEMENTS)
    if replacements:
        check_aliases(base, symbols, replacements)
        for source in replacements.values():
            body = symbols[source]
            address = int(body["address"], 0)
            if not 0x40370000 <= address < address + body["symbol_size_bytes"] <= 0x403e0000:
                raise ValueError("API/feature source entry is outside IRAM")
    for name in RETAINED_FUNCTIONS:
        if init_source and name in init_ownership.FUNCTIONS[chip]:
            init_ownership.function(base,symbols,name);continue
        if name in replacements:
            continue
        symbol = temperature.require_body(symbols, name)
        if not any(temperature.contains(row, symbol) for row in inputs):
            raise ValueError(f"Missing retained vendor helper input: {name}")
    for name, size in (("phy_param", temperature.STATE_SIZES[chip]), ("g_phyFuns", 4)):
        if init_source:
            init_ownership.state(base,symbols,name);continue
        symbol = symbols.get(name)
        if not (symbol and symbol["allocated"] and symbol["body_contained"]
                and symbol["type"] == "STT_OBJECT" and symbol["symbol_size_bytes"] == size
                and int(symbol["address"], 0) % 4 == 0
                and any(temperature.contains(row, symbol) for row in inputs)):
            raise ValueError(f"Missing or changed retained vendor state: {name}")
    for name, address in temperature.ROM_REFERENCES[chip].items():
        symbol = symbols.get(name)
        if not (symbol and symbol.get("absolute") and int(symbol["address"], 0) == address):
            raise ValueError(f"Missing or changed ROM dependency: {name}")

    table = symbols.get(SOURCE_TABLE)
    if not (table and table["allocated"] and table["body_contained"]
            and table["type"] == "STT_OBJECT" and table["symbol_size_bytes"] == 30):
        raise ValueError("Missing or invalid source attribute table")
    if int(table["address"], 0) % 2:
        raise ValueError("Unaligned source attribute table")
    if table["body_sha256"] != table_sha256:
        raise ValueError("Source attribute table differs from pinned five-row table")
    if not alias_matches(symbols.get("phy_tsens_attribute"), table, executable=False):
        raise ValueError("Incorrect attribute table source alias")
    if any(temperature.overlaps(row, table) for row in inputs):
        raise ValueError("Source attribute table overlaps retained vendor input")


def audit(elf_path, map_path, label, stage):
    from elftools.elf.elffile import ELFFile

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", label):
        raise ValueError("Label must be a simple artifact identifier")
    base = allocations.audit(elf_path, map_path, label, exclude_strings=True)
    chip = base["chip"]
    names = set(source_names(chip)) | set(source_names(chip).values())
    names.update(temperature.RETAINED_FUNCTIONS[chip])
    names.update(("phy_param", "g_phyFuns", "phy_tsens_attribute", SOURCE_TABLE))
    names.update(temperature.ROM_REFERENCES[chip])
    with elf_path.open("rb") as stream:
        symbols = temperature.inspect_symbols(ELFFile(stream), sorted(names))
    oracle = json.loads(ORACLE.read_text())["chips"][chip]
    table_hash = hashlib.sha256(bytes(oracle["attribute_bytes"])).hexdigest()
    check_lifecycle(base, symbols, stage, table_hash)
    phy = base["allocations"]["libphy.a"]
    aliases = temperature.source_names(chip) if stage == "temperature" else source_names(chip)
    if stage == "lifecycle":
        aliases = {**aliases, "phy_tsens_attribute": SOURCE_TABLE}
    shared_api = [row for row in phy["inputs"]
                  if row["member"] == "phy_api.o" and row["section"].startswith(".iram")]
    return {
        "schema": "phy-sensor-lifecycle-allocation-audit-v1", "label": label,
        "chip": chip, "stage": stage, "checks_passed": True,
        "profile": "full-tracking-station", "linker": base["linker"],
        "elf_sha256": base["elf_sha256"], "map_sha256": base["map_sha256"],
        "baseline": {"label": "source-v4-sta_smoke", **BASELINE_HASHES[chip]},
        "method": base["method"], "attribute_table_sha256": table_hash,
        "previous_source_gates": {"printf": True, "wrappers": True, "dispatcher": True,
                                  "temperature": True, "no_allocated_libpp": True},
        "non_string_allocations": {"libphy_bytes": phy["bytes"],
                                   "phy_tsens_member_bytes": phy["members"].get("phy_tsens.o", 0),
                                   "libphy_member_count": phy["member_count"]},
        "source_aliases": {old: {"address": symbols[old]["address"],
                                  "alias_symbol_size_bytes": symbols[old]["symbol_size_bytes"],
                                  "source_symbol": new, "source_body": symbols[new]}
                           for old, new in aliases.items()},
        "retained_symbols": {name: symbols[name] for name in sorted(names)
                             if name not in aliases and name not in aliases.values()},
        "xpd_routing": {"implementation": "source" if stage == "lifecycle" else "vendor",
                        "vendor_body_bytes_proven_removed": False,
                        "remaining_shared_phy_api_inputs": shared_api},
        "input_archives_observed": base["input_archives_observed"],
        "allocated_phy_inputs": phy["inputs"],
        "limits": ["All-member removal is a property of this linked image, not every archive consumer.",
                   "Strong xpd alias routing does not remove its bytes from a retained shared phy_api.o input.",
                   "Alias symbol sizes may be stale; actual source sizes and ownership are checked separately.",
                   "ROM reference symbols do not establish live callback table contents.",
                   "The xpd address gate does not prove IRAM placement of its callees or literal loads.",
                   "This audit does not prove source semantics, MMIO ordering or device behavior."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--stage", choices=("temperature", "lifecycle"), required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.elf, args.map, args.label, args.stage), indent=2))


if __name__ == "__main__":
    main()
