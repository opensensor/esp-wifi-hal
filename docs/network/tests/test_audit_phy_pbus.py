#!/usr/bin/env python3
"""Synthetic PBUS source/vendor ownership and previous-milestone regressions."""
import unittest

import audit_phy_pbus as pbus
from test_audit_phy_lifecycle import fixture as lifecycle_fixture, append_input, TABLE_HASH
from test_audit_phy_temperature import symbol


def fixture(chip, expected="source"):
    base, symbols = lifecycle_fixture(chip)
    for i, name in enumerate(pbus.RETAINED_FUNCTIONS):
        address = 0x42019000 + 32 * i
        symbols[name] = symbol(address)
        append_input(base, "phy_tx.o" if i == 0 else "phy_chip_v7.o", ".text." + name, address)
    for name, address in pbus.ROM_REFERENCES[chip].items():
        symbols[name] = symbol(address, size=0)
        symbols[name].update(allocated=False, executable=False, absolute=True, type="STT_NOTYPE")
    for i, (old, new) in enumerate(pbus.SELECTED[chip].items()):
        if expected == "source":
            address = 0x4200a000 + 32 * i
            symbols[new] = symbol(address, size=24)
            symbols[old] = symbol(address, size=0 if chip == "esp32c3" else 120)
        else:
            address = 0x4201a000 + 32 * i
            symbols[old] = symbol(address)
            symbols[new] = None
            append_input(base, "phy_pbus.o", ".text." + old, address)
    if expected == "vendor":
        append_input(base, "phy_pbus.o", ".rodata", 0x3c000300, 68 if chip == "esp32c3" else 88)
        append_input(base, "phy_pbus.o", ".rodata.set_pbus_mem", 0x3c000400, 40)
    return base, symbols


def check(base, symbols, expected="source"):
    pbus.check_pbus(base, symbols, expected, TABLE_HASH)


class PbusAuditTests(unittest.TestCase):
    def test_source_and_vendor_on_both_prior_map_formats(self):
        for chip in pbus.SELECTED:
            for expected in ("source", "vendor"):
                with self.subTest(chip=chip, expected=expected):
                    base, symbols = fixture(chip, expected)
                    check(base, symbols, expected)
                    self.assertNotIn("/private/", str(base))

    def test_complete_member_includes_text_literals_local_data_and_jump_table(self):
        for section in (".text.save_pbus_reg", ".literal.set_pbus_mem", ".rodata",
                        ".rodata.set_pbus_mem", ".data.local_anchor", "COMMON"):
            base, symbols = fixture("esp32c3")
            append_input(base, "phy_pbus.o", section)
            with self.subTest(section=section), self.assertRaisesRegex(ValueError, "phy_pbus.o still has allocated"):
                check(base, symbols)

    def test_member_removal_cannot_hide_in_excluded_strings(self):
        base, symbols = fixture("esp32s3")
        base["excluded_mergeable_string_inputs"] = [
            {"member": "phy_pbus.o", "section": ".rodata.str1.1", "reported_input_bytes": 4}]
        with self.assertRaisesRegex(ValueError, "excluded mergeable string"):
            check(base, symbols)

    def test_every_alias_must_route_to_its_actual_source_body(self):
        for chip in pbus.SELECTED:
            for old in pbus.SELECTED[chip]:
                base, symbols = fixture(chip)
                symbols[old]["address"] = "0x4200c000"
                with self.subTest(chip=chip, name=old), self.assertRaisesRegex(ValueError, "Incorrect PBUS source alias"):
                    check(base, symbols)

    def test_alias_size_and_absolute_symbol_metadata_are_not_source_body_sizes(self):
        base, symbols = fixture("esp32s3")
        for old in pbus.SELECTED["esp32s3"]:
            symbols[old].update(symbol_size_bytes=0xffffffff, allocated=False, executable=False,
                                absolute=True, body_contained=False, type="STT_NOTYPE")
        check(base, symbols)

    def test_source_requires_allocated_nonempty_contained_function_bodies(self):
        for field, value in (("allocated", False), ("executable", False),
                             ("body_contained", False), ("symbol_size_bytes", 0),
                             ("type", "STT_OBJECT")):
            base, symbols = fixture("esp32c3")
            symbols["__opensensor_pbus_save"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Missing allocated function body"):
                check(base, symbols)

    def test_inlined_save_still_requires_exported_save_body(self):
        base, symbols = fixture("esp32s3")
        symbols["__opensensor_pbus_save"] = None
        with self.assertRaisesRegex(ValueError, "Missing allocated function body"):
            check(base, symbols)

    def test_source_cannot_alias_retained_vendor_bytes(self):
        base, symbols = fixture("esp32c3")
        address = int(symbols["stop_tx_tone"]["address"], 0) - 8
        symbols["__opensensor_pbus_work_mode"]["address"] = hex(address)
        symbols["txcal_work_mode"]["address"] = hex(address)
        with self.assertRaisesRegex(ValueError, "PBUS source body overlaps vendor"):
            check(base, symbols)

    def test_renaming_original_member_does_not_bypass_selected_section_gate(self):
        base, symbols = fixture("esp32s3")
        append_input(base, "other.o", ".text.set_pbus_mem")
        with self.assertRaisesRegex(ValueError, "Original PBUS function input"):
            check(base, symbols)

    def test_s3_does_not_claim_source_force_mode(self):
        base, symbols = fixture("esp32s3")
        symbols["__opensensor_pbus_force_mode"] = symbol(0x4200c000)
        with self.assertRaisesRegex(ValueError, "S3 force mode must remain"):
            check(base, symbols)

    def test_vendor_rejects_any_source_symbol_including_undefined_presence(self):
        for name in pbus.ALL_SOURCE_NAMES:
            base, symbols = fixture("esp32s3", "vendor")
            symbols[name] = symbol(0, size=0)
            symbols[name].update(allocated=False, executable=False)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Source PBUS symbol present"):
                check(base, symbols, "vendor")

    def test_vendor_body_must_belong_to_original_member_and_function_input(self):
        for member, section in (("other.o", ".text.set_pbus_mem"),
                                ("phy_pbus.o", ".text.different_function")):
            base, symbols = fixture("esp32c3", "vendor")
            for row in base["allocations"]["libphy.a"]["inputs"]:
                if row["section"] == ".text.set_pbus_mem":
                    row.update(member=member, section=section)
            with self.subTest(member=member, section=section), self.assertRaisesRegex(ValueError, "lacks member input"):
                check(base, symbols, "vendor")

    def test_vendor_constant_and_jump_tables_remain_required(self):
        for chip in pbus.SELECTED:
            for section in (".rodata", ".rodata.set_pbus_mem"):
                for failure in ("missing", "size"):
                    base, symbols = fixture(chip, "vendor")
                    rows = base["allocations"]["libphy.a"]["inputs"]
                    row = next(r for r in rows if r["member"] == "phy_pbus.o" and r["section"] == section)
                    if failure == "missing":
                        rows.remove(row)
                    else:
                        row["size_bytes"] += 4
                    with self.subTest(chip=chip, section=section, failure=failure), self.assertRaisesRegex(
                            ValueError, "vendor PBUS table input"):
                        check(base, symbols, "vendor")

    def test_retained_caller_and_tone_helper_need_vendor_ownership(self):
        for name in pbus.RETAINED_FUNCTIONS:
            base, symbols = fixture("esp32s3")
            symbols[name]["address"] = "0x4200c000"
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Retained PBUS helper lacks vendor"):
                check(base, symbols)

    def test_rom_references_cannot_silently_move_or_become_allocated_replacements(self):
        for chip in pbus.SELECTED:
            for name in pbus.ROM_REFERENCES[chip]:
                for field, value in (("address", "0x40000000"), ("absolute", False)):
                    base, symbols = fixture(chip)
                    symbols[name][field] = value
                    with self.subTest(chip=chip, name=name, field=field), self.assertRaisesRegex(
                            ValueError, "changed PBUS ROM reference"):
                        check(base, symbols)

    def test_previous_source_milestones_remain_required(self):
        for failure, message in (("sensor_member", "phy_tsens.o still has allocated"),
                                  ("sensor_alias", "Incorrect lifecycle source alias"),
                                  ("sensor_table", "differs from pinned"),
                                  ("libpp", "no allocated libpp"),
                                  ("printf", "Unexpected printf"),
                                  ("dispatcher", "dispatcher still allocated"),
                                  ("wrapper", "wrapper still allocated"),
                                  ("tracking", "Missing retained tracking")):
            base, symbols = fixture("esp32s3")
            if failure == "sensor_member":
                append_input(base, "phy_tsens.o", ".rodata.phy_tsens_attribute")
            elif failure == "sensor_alias":
                symbols["phy_xpd_tsens"]["address"] = "0x40382000"
            elif failure == "sensor_table":
                symbols["__opensensor_tsens_attribute"]["body_sha256"] = "0" * 64
            elif failure == "libpp":
                base["allocations"]["libpp.a"]["bytes"] = 4
            elif failure == "printf":
                base["allocations"]["prebuilt_printf"]["bytes"] = 4
            elif failure == "dispatcher":
                base["selected_allocated_symbols"]["ram_tx_pwctrl_background"] = {"size_bytes": 122}
            elif failure == "wrapper":
                base["selected_allocated_symbols"]["phy_bbpll_en_usb"] = {"size_bytes": 14}
            else:
                base["selected_allocated_symbols"]["rfpll_cap_track"] = None
            with self.subTest(failure=failure), self.assertRaisesRegex(ValueError, message):
                check(base, symbols)

    def test_unknown_expectation_fails(self):
        base, symbols = fixture("esp32c3")
        with self.assertRaisesRegex(ValueError, "Expected PBUS"):
            check(base, symbols, "auto")


if __name__ == "__main__":
    unittest.main()
