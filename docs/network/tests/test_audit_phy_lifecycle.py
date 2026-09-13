#!/usr/bin/env python3
"""Regressions for staged sensor ownership, aliases and complete-member removal."""
import hashlib
import json
import unittest

import audit_phy_lifecycle as lifecycle
import audit_phy_temperature as temperature
from test_audit_phy_temperature import fixture as temperature_fixture, symbol


TABLE_HASH = hashlib.sha256(bytes(json.loads(lifecycle.ORACLE.read_text())
                                 ["chips"]["esp32c3"]["attribute_bytes"])).hexdigest()


def fixture(chip, stage="lifecycle"):
    """Extend the GNU/LLD-parsed prior-stage fixture with independent ownership.

    Keep a shared phy_api.o .iram1 input containing the old xpd body. Strong
    aliasing changes calls, but does not justify removing this allocated input.
    """
    base, symbols = temperature_fixture(chip)
    if stage == "temperature":
        return base, symbols
    retained = set(lifecycle.RETAINED_FUNCTIONS) | {"phy_param", "g_phyFuns"}
    rows = []
    for row in base["allocations"]["libphy.a"]["inputs"]:
        name = row["section"].split(".", 2)[-1]
        if name in retained:
            row["member"] = "phy_init.o"
            rows.append(row)
        elif name == "phy_xpd_tsens":
            row.update(member="phy_api.o", section=".iram1", address="0x40381000")
            rows.append(row)
    base["allocations"]["libphy.a"]["inputs"] = rows
    base["allocations"]["libphy.a"]["bytes"] = sum(row["size_bytes"] for row in rows)
    for i, (old, new) in enumerate(lifecycle.LIFECYCLE[chip].items()):
        address = 0x40380000 if old == "phy_xpd_tsens" else 0x42008000 + i * 32
        symbols[new] = symbol(address, size=24)
        symbols[old] = symbol(address, size=0 if chip == "esp32c3" else 120)
    symbols[lifecycle.SOURCE_TABLE] = symbol(0x3c000100, size=30, function=False)
    symbols[lifecycle.SOURCE_TABLE]["body_sha256"] = TABLE_HASH
    symbols["phy_tsens_attribute"] = symbol(0x3c000100, size=0, function=False)
    return base, symbols


def check(base, symbols, stage="lifecycle"):
    lifecycle.check_lifecycle(base, symbols, stage, TABLE_HASH)


def append_input(base, member, section, address=0x42018000, size=16):
    base["allocations"]["libphy.a"]["inputs"].append(
        {"member": member, "section": section, "address": hex(address), "size_bytes": size})


class LifecycleAuditTests(unittest.TestCase):
    def test_both_stages_and_map_formats(self):
        for chip in lifecycle.LIFECYCLE:
            for stage in ("temperature", "lifecycle"):
                with self.subTest(chip=chip, stage=stage):
                    base, symbols = fixture(chip, stage)
                    check(base, symbols, stage)
                    self.assertNotIn("/private/", str(base))

    def test_temperature_stage_rejects_any_lifecycle_source_symbol(self):
        for name in (*lifecycle.LIFECYCLE["esp32s3"].values(), lifecycle.SOURCE_TABLE):
            with self.subTest(name=name):
                base, symbols = fixture("esp32s3", "temperature")
                symbols[name] = symbol(0x42008000)
                with self.assertRaisesRegex(ValueError, "Lifecycle source symbol present"):
                    check(base, symbols, "temperature")

    def test_temperature_stage_does_not_weaken_original_helper_gate(self):
        base, symbols = fixture("esp32c3", "temperature")
        symbols["rom2_tsens_read_init1"] = None
        with self.assertRaisesRegex(ValueError, "Missing allocated function body"):
            check(base, symbols, "temperature")

    def test_whole_member_means_text_literal_table_and_unknown_sections(self):
        for section in (".text.phy_set_tsens_power", ".literal.tsens_read_init_new",
                        ".rodata.phy_tsens_attribute", ".data.local_anchor", "COMMON"):
            with self.subTest(section=section):
                base, symbols = fixture("esp32s3")
                append_input(base, "phy_tsens.o", section)
                with self.assertRaisesRegex(ValueError, "phy_tsens.o still has allocated inputs"):
                    check(base, symbols)

    def test_member_removal_cannot_hide_in_excluded_strings(self):
        base, symbols = fixture("esp32c3")
        base["excluded_mergeable_string_inputs"] = [
            {"member": "phy_tsens.o", "section": ".rodata.str1.1", "reported_input_bytes": 4}]
        with self.assertRaisesRegex(ValueError, "excluded mergeable string input"):
            check(base, symbols)

    def test_selected_original_sections_rejected_even_under_another_member(self):
        base, symbols = fixture("esp32s3")
        append_input(base, "renamed_sensor.o", ".literal.tsens_read_init_new")
        with self.assertRaisesRegex(ValueError, "Original sensor function input still allocated"):
            check(base, symbols)

    def test_each_function_alias_must_resolve_its_source_body(self):
        for chip in lifecycle.LIFECYCLE:
            for name in lifecycle.source_names(chip):
                with self.subTest(chip=chip, name=name):
                    base, symbols = fixture(chip)
                    symbols[name]["address"] = "0x42019000"
                    with self.assertRaisesRegex(ValueError, "Incorrect lifecycle source alias"):
                        check(base, symbols)

    def test_alias_sizes_and_absolute_linker_symbols_are_not_body_sizes(self):
        base, symbols = fixture("esp32s3")
        for old in (*lifecycle.source_names("esp32s3"), "phy_tsens_attribute"):
            symbols[old].update(symbol_size_bytes=0xffffffff, body_contained=False,
                                allocated=False, executable=False, absolute=True, type="STT_NOTYPE")
        base["selected_allocated_symbols"]["ram_tsens_temp_read"] = None
        check(base, symbols)

    def test_missing_or_nonfunction_source_body_rejected(self):
        for field, value in (("allocated", False), ("executable", False),
                             ("body_contained", False), ("symbol_size_bytes", 0),
                             ("type", "STT_OBJECT")):
            base, symbols = fixture("esp32c3")
            symbols["__opensensor_tsens_init"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Missing allocated function body"):
                check(base, symbols)

    def test_source_body_cannot_overlap_even_part_of_vendor_input(self):
        base, symbols = fixture("esp32c3")
        helper_address = int(symbols["phy_get_romfunc_addr"]["address"], 0)
        symbols["__opensensor_tsens_init"]["address"] = hex(helper_address - 8)
        symbols["rom2_tsens_read_init1"]["address"] = hex(helper_address - 8)
        with self.assertRaisesRegex(ValueError, "Source body overlaps vendor input"):
            check(base, symbols)

    def test_source_xpd_requires_iram_but_shared_vendor_iram_remains_valid(self):
        for chip in lifecycle.LIFECYCLE:
            base, symbols = fixture(chip)
            self.assertTrue(any(row["member"] == "phy_api.o" and row["section"] == ".iram1"
                                for row in base["allocations"]["libphy.a"]["inputs"]))
            check(base, symbols)
            symbols["__opensensor_tsens_xpd"]["address"] = "0x42009000"
            symbols["phy_xpd_tsens"]["address"] = "0x42009000"
            with self.subTest(chip=chip), self.assertRaisesRegex(ValueError, "instruction RAM"):
                check(base, symbols)

    def test_missing_retained_helper_or_input_rejected(self):
        for name in lifecycle.RETAINED_FUNCTIONS:
            for failure in ("symbol", "input"):
                base, symbols = fixture("esp32s3")
                if failure == "symbol":
                    symbols[name] = None
                    message = "Missing allocated function body"
                else:
                    symbols[name]["address"] = "0x42019000"
                    message = "Missing retained vendor helper input"
                with self.subTest(name=name, failure=failure), self.assertRaisesRegex(ValueError, message):
                    check(base, symbols)

    def test_state_layout_alignment_and_ownership_remain_required(self):
        for name in ("phy_param", "g_phyFuns"):
            for field, value in (("symbol_size_bytes", 1), ("address", "0x3fc80001"),
                                 ("address", "0x3fc90000"), ("allocated", False),
                                 ("body_contained", False), ("type", "STT_NOTYPE")):
                base, symbols = fixture("esp32c3")
                symbols[name][field] = value
                with self.subTest(name=name, field=field, value=value), self.assertRaisesRegex(
                        ValueError, "changed retained vendor state"):
                    check(base, symbols)

    def test_source_table_requires_exact_size_allocation_and_object_type(self):
        for field, value in (("symbol_size_bytes", 36), ("allocated", False),
                             ("body_contained", False), ("type", "STT_NOTYPE")):
            base, symbols = fixture("esp32s3")
            symbols[lifecycle.SOURCE_TABLE][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "invalid source attribute table"):
                check(base, symbols)

    def test_source_table_cannot_be_unaligned_or_differ_from_pinned_rows(self):
        for field, value, message in (("address", "0x3c000101", "Unaligned source attribute"),
                                      ("body_sha256", "0" * 64, "differs from pinned")):
            base, symbols = fixture("esp32c3")
            symbols[lifecycle.SOURCE_TABLE][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                check(base, symbols)

    def test_source_table_alias_and_ownership_checked_separately(self):
        base, symbols = fixture("esp32c3")
        symbols["phy_tsens_attribute"]["address"] = "0x3c000200"
        with self.assertRaisesRegex(ValueError, "Incorrect attribute table source alias"):
            check(base, symbols)
        symbols["phy_tsens_attribute"]["address"] = symbols[lifecycle.SOURCE_TABLE]["address"]
        append_input(base, "different_vendor_member.o", ".rodata.table", 0x3c000110, 4)
        with self.assertRaisesRegex(ValueError, "attribute table overlaps retained vendor"):
            check(base, symbols)

    def test_rom_dependencies_must_remain_at_the_pinned_addresses(self):
        for chip in lifecycle.LIFECYCLE:
            for name in temperature.ROM_REFERENCES[chip]:
                base, symbols = fixture(chip)
                symbols[name]["address"] = "0x40000000"
                with self.subTest(chip=chip, name=name), self.assertRaisesRegex(ValueError, "changed ROM dependency"):
                    check(base, symbols)

    def test_previous_source_milestone_gates_remain_strict(self):
        for regression, message in (("libpp", "no allocated libpp"),
                                    ("printf", "Unexpected printf"),
                                    ("dispatcher", "dispatcher still allocated"),
                                    ("wrapper", "wrapper still allocated"),
                                    ("tracking", "Missing retained tracking")):
            base, symbols = fixture("esp32s3")
            if regression == "libpp":
                base["allocations"]["libpp.a"]["bytes"] = 4
            elif regression == "printf":
                base["allocations"]["prebuilt_printf"]["bytes"] = 4
            elif regression == "dispatcher":
                base["selected_allocated_symbols"]["ram_tx_pwctrl_background"] = {"size_bytes": 122}
            elif regression == "wrapper":
                base["selected_allocated_symbols"]["phy_bbpll_en_usb"] = {"size_bytes": 14}
            else:
                base["selected_allocated_symbols"]["rfpll_cap_track"] = None
            with self.subTest(regression=regression), self.assertRaisesRegex(ValueError, message):
                check(base, symbols)

    def test_unknown_stage_is_not_silently_treated_as_lifecycle(self):
        base, symbols = fixture("esp32c3")
        with self.assertRaisesRegex(ValueError, "Expected stage"):
            check(base, symbols, "vendor")


if __name__ == "__main__":
    unittest.main()
