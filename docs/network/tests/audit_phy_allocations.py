#!/usr/bin/env python3
"""Audit C3/S3 linked PHY and printf input allocations without exporting paths.

Requires pyelftools for ELF inspection. Parses LLD or GNU ld maps, includes
COMMON allocations, and excludes discarded/non-SHF_ALLOC contributions.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


CATEGORIES = ("libphy.a", "libpp.a", "prebuilt_printf", "source_printf", "unknown_printf")
WRAPPERS = ("tx_pwctrl_background", "phy_bbpll_en_usb")
RETAINED = ("ram_tx_pwctrl_background", "phy_param", "register_chipv7_phy")


def classify(archive, member):
    name = Path(archive).name
    if name in ("libphy.a", "libpp.a"):
        return name
    if name == "libprintf.a":
        if member == "printf.c.obj":
            return "prebuilt_printf"
        if re.fullmatch(r"[0-9a-f]+-printf\.o", member):
            return "source_printf"
        return "unknown_printf"
    if (re.fullmatch(r"libesp_wifi_sys_esp32(?:c3|s3)-[0-9a-f]+\.rlib", name)
            and re.fullmatch(r"[0-9a-f]+-printf\.o", member)):
        return "source_printf"
    return None


def parse_map(text):
    """Yield selected archive input records; preserve no filesystem paths."""
    rows = []
    if not text.strip():
        raise ValueError("Expected an LLD or GNU ld map")
    if text.splitlines()[0].split() == ["VMA", "LMA", "Size", "Align", "Out", "In", "Symbol"]:
        linker = "LLD"
        for line in text.splitlines()[1:]:
            match = re.fullmatch(r"\s*([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)\s+\d+\s+(.+)\(([^()]+)\):\(([^()]+)\)", line)
            if not match:
                continue
            address, size, archive, member, section = match.groups()
            category = classify(archive, member)
            if category:
                rows.append((category, member, section, int(address, 16), int(size, 16), archive))
    elif text.count("Linker script and memory map") == 1:
        linker = "GNU ld"
        # Earlier archive resolution and discarded sections are not allocations.
        text = text.split("Linker script and memory map", 1)[1]
        pending = None
        for line in text.splitlines():
            section = re.fullmatch(r" ([.][^\s]+|COMMON)\s*", line)
            if section:
                pending = section[1]
                continue
            match = re.fullmatch(r"\s+(?:([.][^\s]+|COMMON)\s+)?(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(.+)\(([^()]+)\)\s*", line)
            if match:
                section, address, size, archive, member = match.groups()
                category = classify(archive, member)
                if category:
                    section = section or pending
                    if section is None:
                        raise ValueError("Selected GNU input has no section name")
                    rows.append((category, member, section, int(address, 16), int(size, 16), archive))
            pending = None
    else:
        raise ValueError("Expected an LLD or GNU ld map")
    if not rows:
        raise ValueError("No selected archive inputs found")
    return linker, rows


def allocate(rows, allocated_sections):
    """Count live input bytes only; never include padding or symbol duplicates."""
    groups = {name: [] for name in CATEGORIES}
    seen = set()
    for category, member, section, address, size, *_ in rows:
        if size == 0:
            continue
        matches = [name for name, start, end in allocated_sections
                   if start <= address and address + size <= end]
        if not matches:
            if any(address < end and start < address + size for _, start, end in allocated_sections):
                raise ValueError("Selected input partially overlaps an allocated output section")
            continue
        if len(matches) != 1:
            raise ValueError("Ambiguous allocated output section")
        key = (address, size)
        if key in seen:
            raise ValueError("Duplicate live input contribution")
        seen.add(key)
        groups[category].append({"member": member, "section": section,
                                 "address": hex(address), "size_bytes": size,
                                 "output_section": matches[0]})
    flattened = sorted((int(row["address"], 0), row["size_bytes"])
                       for rows in groups.values() for row in rows)
    for (start, size), (next_start, _) in zip(flattened, flattened[1:]):
        if start + size > next_start:
            raise ValueError("Overlapping live input contributions")
    return groups


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit(elf_path, map_path, label):
    from elftools.elf.elffile import ELFFile

    linker, rows = parse_map(map_path.read_text())
    archive_members = {}
    for _, member, _, _, _, archive in rows:
        archive_members.setdefault(archive, set()).add(member)
    observed_archives = [{
        "archive": Path(path).name,
        "sha256_observed_at_audit": sha256(Path(path)) if Path(path).is_file() else None,
        "members_referenced_in_selected_map_rows": sorted(members),
    } for path, members in sorted(archive_members.items())]
    with elf_path.open("rb") as stream:
        elf = ELFFile(stream)
        if (elf.elfclass != 32 or not elf.little_endian or elf["e_type"] != "ET_EXEC"
                or elf["e_machine"] not in ("EM_RISCV", "EM_XTENSA")):
            raise ValueError("Expected a linked little-endian C3/S3 ELF32 image")
        chip = {"EM_RISCV": "esp32c3", "EM_XTENSA": "esp32s3"}[elf["e_machine"]]
        if (chip == "esp32c3") != (linker == "LLD"):
            raise ValueError("Unexpected chip/linker pairing for this audit")
        sections = [(section.name, section["sh_addr"], section["sh_addr"] + section["sh_size"])
                    for section in elf.iter_sections() if section["sh_flags"] & 2 and section["sh_size"]]
        groups = allocate(rows, sections)
        table = elf.get_section_by_name(".symtab")
        if table is None:
            raise ValueError("Selected symbol audit requires .symtab")
        symbols = {}
        for name in WRAPPERS + RETAINED + ("vsnprintf",):
            candidates = [symbol for symbol in table.get_symbol_by_name(name) or []
                          if isinstance(symbol["st_shndx"], int)
                          and elf.get_section(symbol["st_shndx"])["sh_flags"] & 2]
            if len(candidates) > 1:
                raise ValueError(f"Ambiguous live symbol {name}")
            symbols[name] = None if not candidates else {
                "address": hex(candidates[0]["st_value"]),
                "size_bytes": candidates[0]["st_size"],
            }
    result = {
        "schema": "phy-source-allocation-audit-v1", "label": label, "chip": chip,
        "linker": linker, "elf_sha256": sha256(elf_path), "map_sha256": sha256(map_path),
        "method": "Live archive input ranges wholly inside one ELF SHF_ALLOC output section; includes COMMON, excludes discarded/debug/nonallocated inputs and linker padding.",
        "printf_source_attribution": "Known cc object name in libprintf.a or the patched sys rlib; pair with build/source provenance. Naming alone is not proof. Observed archive hashes describe files at audit time, not necessarily at historical link time; unavailable ephemeral archives have null hashes.",
        "input_archives_observed": observed_archives,
        "allocations": {}, "selected_allocated_symbols": symbols,
    }
    for name, inputs in groups.items():
        members = Counter()
        for row in inputs:
            members[row["member"]] += row["size_bytes"]
        result["allocations"][name] = {
            "bytes": sum(members.values()), "input_sections": len(inputs),
            "member_count": len(members), "members": dict(sorted(members.items())),
            "inputs": inputs,
        }
    return result


def check_expectations(result, printf, wrappers):
    allocated = result["allocations"]
    symbols = result["selected_allocated_symbols"]
    if not allocated["libphy.a"]["bytes"] or allocated["libpp.a"]["bytes"]:
        raise ValueError("Expected retained PHY and no allocated libpp")
    if any(symbols[name] is None for name in RETAINED):
        raise ValueError("Missing retained tracking, calibration or parameter symbol")
    if printf:
        live = "source_printf" if printf == "source" else "prebuilt_printf"
        absent = "prebuilt_printf" if printf == "source" else "source_printf"
        if (not allocated[live]["bytes"] or allocated[absent]["bytes"]
                or allocated.get("unknown_printf", {}).get("bytes", 0)):
            raise ValueError("Unexpected printf input allocation")
    if wrappers:
        found = [symbols[name] is not None for name in WRAPPERS]
        sections = {row["section"] for row in allocated["libphy.a"]["inputs"]}
        if wrappers == "source":
            if any(found) or any(f".text.{name}" in sections for name in WRAPPERS):
                raise ValueError("Original wrapper still allocated")
        elif not all(found):
            raise ValueError("Expected both original wrappers")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--expect-printf", choices=("prebuilt", "source"))
    parser.add_argument("--expect-phy-wrappers", choices=("vendor", "source"))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
        parser.error("Label must be a simple artifact identifier")
    result = audit(args.elf, args.map, args.label)
    check_expectations(result, args.expect_printf, args.expect_phy_wrappers)
    print(json.dumps(result, indent=2))
