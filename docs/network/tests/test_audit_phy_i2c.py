#!/usr/bin/env python3
"""Regressions for staged I2C ownership, aliases, IRAM and retained ROM gates."""
import unittest

import audit_phy_i2c as i2c
from test_audit_phy_pbus import fixture as pbus_fixture
from test_audit_phy_lifecycle import append_input, TABLE_HASH
from test_audit_phy_temperature import symbol


def fixture(chip, expected="source"):
    base, symbols = pbus_fixture(chip)
    for name, address in i2c.ROM_REFERENCES[chip].items():
        symbols[name] = symbol(address, size=0)
        symbols[name].update(absolute=True, allocated=False, executable=False, type="STT_NOTYPE")
    for index, (old, new) in enumerate(i2c.FLASH.items()):
        address = 0x4200b000 + 32 * index
        symbols[old] = symbol(address)
        symbols[new] = None if expected == "vendor" else symbol(address)
        if expected == "vendor":
            append_input(base, "phy_i2c.o", ".text." + old, address)
    for index, (old, new) in enumerate(i2c.IRAM[chip].items()):
        address = (0x4038a000 if expected == "source" else 0x40390000) + 32 * index
        symbols[old] = symbol(address)
        symbols[new] = symbol(address) if expected == "source" else None
    if expected != "source":
        append_input(base, "phy_i2c.o", ".iram1", 0x40390000, 0x400)
        if chip == "esp32c3":
            symbols[i2c.LOCAL_PARTIAL] = symbol(0x40390300, size=60)
    else:
        symbols[i2c.PROGRAM] = symbol(0x3fc8a000, size=40, function=False)
        symbols[i2c.PROGRAM]["body_sha256"] = i2c.PROGRAM_HASH
    return base, symbols


def check(base, symbols, expected="source"):
    i2c.check_i2c(base, symbols, expected, TABLE_HASH)


class I2cAuditTests(unittest.TestCase):
    def test_three_distinct_stages_on_both_chips(self):
        for chip in i2c.IRAM:
            for stage in ("vendor", "flash", "source"):
                with self.subTest(chip=chip, stage=stage):
                    check(*fixture(chip, stage), stage)

    def test_unknown_stage_cannot_bypass_checks(self):
        with self.assertRaisesRegex(ValueError, "Expected I2C"):
            check(*fixture("esp32c3"), "auto")

    def test_whole_member_gate_includes_iram_local_data_and_literals(self):
        for section in (".iram1", ".text.phy_i2c_init2", ".literal.phy_i2c_init2",
                        ".rodata", ".rodata.jump_table", ".data.local_anchor", "COMMON"):
            base, symbols = fixture("esp32s3")
            append_input(base, "phy_i2c.o", section)
            with self.subTest(section=section), self.assertRaisesRegex(ValueError, "phy_i2c.o still"):
                check(base, symbols)

    def test_whole_member_cannot_hide_as_excluded_strings(self):
        base, symbols = fixture("esp32c3")
        base["excluded_mergeable_string_inputs"] = [
            {"member": "phy_i2c.o", "section": ".rodata.str1.1", "reported_input_bytes": 4}]
        with self.assertRaisesRegex(ValueError, "excluded mergeable string"):
            check(base, symbols)

    def test_flash_stage_rejects_every_old_selected_text_or_literal_input(self):
        for old in i2c.FLASH:
            for prefix in (".text.", ".literal."):
                base, symbols = fixture("esp32s3", "flash")
                append_input(base, "phy_i2c.o", prefix + old)
                with self.subTest(name=old, prefix=prefix), self.assertRaisesRegex(ValueError, "Original I2C function input"):
                    check(base, symbols, "flash")

    def test_correct_alias_does_not_hide_an_old_section_under_another_member(self):
        base, symbols = fixture("esp32c3")
        append_input(base, "renamed.o", ".text.phy_get_i2c_data")
        with self.assertRaisesRegex(ValueError, "Original I2C function input"):
            check(base, symbols)

    def test_every_source_alias_must_route_to_correct_body(self):
        for chip in i2c.IRAM:
            for old in {**i2c.FLASH, **i2c.IRAM[chip]}:
                base, symbols = fixture(chip)
                symbols[old]["address"] = "0x4038b000"
                with self.subTest(chip=chip, name=old), self.assertRaisesRegex(ValueError, "Incorrect I2C source alias"):
                    check(base, symbols)

    def test_stale_alias_size_and_absolute_assignment_are_supported(self):
        base, symbols = fixture("esp32s3")
        for old in {**i2c.FLASH, **i2c.IRAM["esp32s3"]}:
            symbols[old].update(symbol_size_bytes=0xffffffff, absolute=True,
                                allocated=False, executable=False, type="STT_NOTYPE")
        check(base, symbols)

    def test_source_requires_real_allocated_nonempty_contained_function(self):
        for field, value in (("allocated", False), ("executable", False), ("body_contained", False),
                             ("symbol_size_bytes", 0), ("type", "STT_OBJECT")):
            base, symbols = fixture("esp32c3")
            symbols["__opensensor_i2c_read"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Missing allocated function body"):
                check(base, symbols)

    def test_empty_critical_helpers_still_need_externally_callable_bodies(self):
        for name in ("__opensensor_i2c_enter", "__opensensor_i2c_exit"):
            base, symbols = fixture("esp32s3")
            symbols[name] = None
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Missing allocated function body"):
                check(base, symbols)

    def test_all_source_iram_bodies_must_be_inside_iram_including_end_address(self):
        for old, new in i2c.IRAM["esp32s3"].items():
            for address in (0x42008000, 0x4036fff0, 0x403dfff8):
                base, symbols = fixture("esp32s3")
                symbols[old]["address"] = symbols[new]["address"] = hex(address)
                with self.subTest(name=old, address=address), self.assertRaisesRegex(ValueError, "outside IRAM"):
                    check(base, symbols)

    def test_source_body_cannot_overlap_any_retained_vendor_input(self):
        base, symbols = fixture("esp32c3")
        address = int(symbols["stop_tx_tone"]["address"], 0) - 8
        symbols["phy_i2c_init2"]["address"] = hex(address)
        symbols["__opensensor_i2c_init2"]["address"] = hex(address)
        with self.assertRaisesRegex(ValueError, "I2C source body overlaps vendor"):
            check(base, symbols)

    def test_flash_stage_preserves_each_original_iram_body(self):
        for chip in i2c.IRAM:
            for old in i2c.IRAM[chip]:
                base, symbols = fixture(chip, "flash")
                symbols[old]["address"] = "0x40392000"
                with self.subTest(chip=chip, name=old), self.assertRaisesRegex(ValueError, "lacks member input"):
                    check(base, symbols, "flash")

    def test_original_iram_requires_original_member_and_section_ownership(self):
        for member, section in (("renamed.o", ".iram1"), ("phy_i2c.o", ".text.fake")):
            base, symbols = fixture("esp32s3", "flash")
            row = next(r for r in base["allocations"]["libphy.a"]["inputs"] if r["member"] == "phy_i2c.o")
            row.update(member=member, section=section)
            with self.subTest(member=member, section=section), self.assertRaisesRegex(ValueError, "lacks member input"):
                check(base, symbols, "flash")

    def test_c3_local_partial_is_retained_until_complete_member_stage(self):
        for stage in ("vendor", "flash"):
            base, symbols = fixture("esp32c3", stage)
            symbols[i2c.LOCAL_PARTIAL] = None
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, "Missing allocated function body"):
                check(base, symbols, stage)
        base, symbols = fixture("esp32c3")
        symbols[i2c.LOCAL_PARTIAL] = symbol(0x40391000)
        with self.assertRaisesRegex(ValueError, "local partial still present"):
            check(base, symbols)

    def test_c3_local_partial_cannot_claim_unrelated_iram_bytes(self):
        base, symbols = fixture("esp32c3", "flash")
        symbols[i2c.LOCAL_PARTIAL]["address"] = "0x40392000"
        with self.assertRaisesRegex(ValueError, "local partial lacks member IRAM"):
            check(base, symbols, "flash")

    def test_stage_boundary_rejects_unexpected_or_undefined_source_symbols(self):
        for chip in i2c.IRAM:
            for stage in ("vendor", "flash", "source"):
                allowed = set() if stage == "vendor" else set(i2c.FLASH.values())
                if stage == "source":
                    allowed.update(i2c.IRAM[chip].values())
                for name in i2c.ALL_SOURCE_NAMES - allowed:
                    base, symbols = fixture(chip, stage)
                    symbols[name] = symbol(0, size=0)
                    symbols[name].update(allocated=False, executable=False)
                    with self.subTest(chip=chip, stage=stage, name=name), self.assertRaisesRegex(ValueError, "Unexpected I2C source symbol"):
                        check(base, symbols, stage)

    def test_vendor_selected_flash_functions_require_specific_input_sections(self):
        for old in i2c.FLASH:
            base, symbols = fixture("esp32s3", "vendor")
            row = next(r for r in base["allocations"]["libphy.a"]["inputs"] if r["section"] == ".text." + old)
            row["section"] = ".text.other"
            with self.subTest(name=old), self.assertRaisesRegex(ValueError, "lacks member input"):
                check(base, symbols, "vendor")

    def test_retained_rom_refs_include_c3_rom_bound_txcap(self):
        for chip in i2c.IRAM:
            for name in i2c.ROM_REFERENCES[chip]:
                for field, value in (("address", "0x40000000"), ("absolute", False)):
                    base, symbols = fixture(chip)
                    symbols[name][field] = value
                    with self.subTest(chip=chip, name=name, field=field), self.assertRaisesRegex(ValueError, "changed I2C ROM reference"):
                        check(base, symbols)

    def test_previous_pbus_and_sensor_milestones_remain_required(self):
        for member in ("phy_pbus.o", "phy_tsens.o"):
            base, symbols = fixture("esp32c3")
            append_input(base, member, ".rodata")
            with self.subTest(member=member), self.assertRaisesRegex(ValueError, "still has allocated"):
                check(base, symbols)
        base, symbols = fixture("esp32s3")
        symbols["set_pbus_mem"]["address"] = "0x4200c000"
        with self.assertRaisesRegex(ValueError, "Incorrect PBUS source alias"):
            check(base, symbols)

    def test_program_table_requires_exact_object_size_and_internal_dram(self):
        for field, value, message in (("allocated", False, "Missing allocated 40-byte"),
                                      ("absolute", True, "Missing allocated 40-byte"),
                                      ("executable", True, "Missing allocated 40-byte"),
                                      ("body_contained", False, "Missing allocated 40-byte"),
                                      ("type", "STT_FUNC", "Missing allocated 40-byte"),
                                      ("symbol_size_bytes", 39, "Missing allocated 40-byte"),
                                      ("address", "0x3c000100", "internal DRAM"),
                                      ("address", "0x3fcdfff0", "internal DRAM")):
            base, symbols = fixture("esp32s3")
            symbols[i2c.PROGRAM][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, message):
                check(base, symbols)

    def test_program_table_contents_must_match_original_four_arrays(self):
        base, symbols = fixture("esp32c3")
        symbols[i2c.PROGRAM]["body_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "differs from pinned original program"):
            check(base, symbols)

    def test_program_table_cannot_be_backed_by_retained_vendor_bytes(self):
        base, symbols = fixture("esp32c3")
        append_input(base, "other.o", ".data.program", 0x3fc8a020)
        with self.assertRaisesRegex(ValueError, "program table overlaps vendor"):
            check(base, symbols)

    def test_program_table_is_absent_before_whole_member_stage(self):
        for stage in ("vendor", "flash"):
            base, symbols = fixture("esp32s3", stage)
            symbols[i2c.PROGRAM] = symbol(0, size=0, function=False)
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, "before whole-member stage"):
                check(base, symbols, stage)


if __name__ == "__main__":
    unittest.main()
