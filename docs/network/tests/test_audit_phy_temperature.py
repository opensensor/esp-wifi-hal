#!/usr/bin/env python3
"""Synthetic GNU/LLD input-ownership and temperature-alias regressions."""
import copy
import unittest

import audit_phy_allocations as allocation
import audit_phy_temperature as temperature


def symbol(address, size=16, function=True):
    return {"address": hex(address), "symbol_size_bytes": size,
            "type": "STT_FUNC" if function else "STT_OBJECT",
            "absolute": False,
            "allocated": True, "executable": function, "body_contained": True,
            "body_sha256": None}


def fixture(chip, expected="source"):
    """Exercise the real map parser with separate source and vendor ranges."""
    symbols, records = {}, []
    for name, address in temperature.ROM_REFERENCES[chip].items():
        symbols[name] = symbol(address, size=0)
        symbols[name].update(allocated=False, executable=False, absolute=True)
    cursor = 0x42010000
    for name in temperature.RETAINED_FUNCTIONS[chip]:
        symbols[name] = symbol(cursor)
        records.append((cursor, 16, "libphy.a", "phy_tsens.o", ".text." + name))
        cursor += 16
    for name, address, size in (("phy_param", 0x3fc80000, temperature.STATE_SIZES[chip]),
                                ("g_phyFuns", 0x3fc81000, 4),
                                ("phy_tsens_attribute", 0x3c000000, 30)):
        symbols[name] = symbol(address, size, function=False)
        records.append((address, size, "libphy.a", "phy_tsens.o", ".data." + name))
    for i, (original, source) in enumerate(temperature.source_names(chip).items()):
        if expected == "source":
            address = 0x42000000 + i * 32
            symbols[source] = symbol(address, size=24)
            symbols[original] = symbol(address, size=0 if chip == "esp32c3" else 120)
        else:
            symbols[original] = symbol(cursor)
            symbols[source] = None
            records.append((cursor, 16, "libphy.a", "phy_tsens.o", ".text." + original))
            cursor += 16
    records.append((0x42020000, 16, "libprintf.a", "012345-printf.o", ".text.vsnprintf"))
    if chip == "esp32c3":
        text = "VMA LMA Size Align Out In Symbol\n" + "\n".join(
            f"{a:x} {a:x} {n:x} 1 /private/{archive}({member}):({section})"
            for a, n, archive, member, section in records)
    else:
        text = "Discarded input sections\n"
        for name in temperature.SELECTED[chip]:
            text += f" .text.{name} 0x42000000 0x10 /private/libphy.a(phy_tsens.o)\n"
        text += "Linker script and memory map\n" + "\n".join(
            f" {section} 0x{a:x} 0x{n:x} /private/{archive}({member})"
            for a, n, archive, member, section in records)
    _, rows = allocation.parse_map(text)
    groups = allocation.allocate(rows, [(".text", 0x42000000, 0x42030000),
                                        (".data", 0x3fc80000, 0x3fc82000),
                                        (".rodata", 0x3c000000, 0x3c001000)])
    groups = {name: {"bytes": sum(r["size_bytes"] for r in rows), "inputs": rows}
              for name, rows in groups.items()}
    prior = {name: {"address": "0x42010000", "size_bytes": 16}
             for name in allocation.RETAINED[1:] + allocation.DISPATCH_HELPERS[chip]}
    prior.update({name: None for name in allocation.WRAPPERS + ("ram_tx_pwctrl_background",)})
    return {"chip": chip, "allocations": groups, "selected_allocated_symbols": prior}, symbols


class TemperatureAuditTests(unittest.TestCase):
    def test_source_and_vendor_on_both_map_formats(self):
        for chip in temperature.SELECTED:
            for expected in ("source", "vendor"):
                with self.subTest(chip=chip, expected=expected):
                    base, symbols = fixture(chip, expected)
                    temperature.check_temperature(base, symbols, expected)
                    self.assertNotIn("/private/", str(base))

    def test_alias_stale_or_zero_size_does_not_describe_source_body(self):
        base, symbols = fixture("esp32s3")
        for original in temperature.SELECTED["esp32s3"]:
            symbols[original]["symbol_size_bytes"] = 0xffffffff
            symbols[original]["body_contained"] = False
        temperature.check_temperature(base, symbols, "source")

    def test_absolute_linker_alias_resolving_allocated_source_is_valid(self):
        base, symbols = fixture("esp32s3")
        for original in temperature.SELECTED["esp32s3"]:
            symbols[original].update(allocated=False, executable=False, absolute=True,
                                     body_contained=False, type="STT_NOTYPE")
        base["selected_allocated_symbols"]["ram_tsens_temp_read"] = None
        temperature.check_temperature(base, symbols, "source")

    def test_absolute_alias_does_not_bypass_remaining_tracking_helper_gate(self):
        base, symbols = fixture("esp32s3")
        symbols["ram_tsens_temp_read"].update(allocated=False, executable=False, absolute=True)
        base["selected_allocated_symbols"]["ram_tsens_temp_read"] = None
        base["selected_allocated_symbols"]["rfpll_cap_track"] = None
        with self.assertRaisesRegex(ValueError, "Missing retained tracking"):
            temperature.check_temperature(base, symbols, "source")

    def test_wrong_alias_address_rejected(self):
        for chip in temperature.SELECTED:
            base, symbols = fixture(chip)
            symbols[temperature.SELECTED[chip][0]]["address"] = "0x42001000"
            with self.assertRaisesRegex(ValueError, "Incorrect temperature source alias"):
                temperature.check_temperature(base, symbols, "source")

    def test_remaining_vendor_text_rejected_even_when_alias_is_correct(self):
        base, symbols = fixture("esp32c3")
        base["allocations"]["libphy.a"]["inputs"].append({
            "member": "phy_tsens.o", "section": ".text.tsens_dac_cal1",
            "address": "0x42011000", "size_bytes": 120})
        with self.assertRaisesRegex(ValueError, "Original temperature input still allocated"):
            temperature.check_temperature(base, symbols, "source")

    def test_remaining_vendor_literal_rejected_even_when_alias_is_correct(self):
        base, symbols = fixture("esp32s3")
        base["allocations"]["libphy.a"]["inputs"].append({
            "member": "phy_tsens.o", "section": ".literal.ram_tsens_temp_read_new",
            "address": "0x42011000", "size_bytes": 4})
        with self.assertRaisesRegex(ValueError, "Original temperature input still allocated"):
            temperature.check_temperature(base, symbols, "source")

    def test_missing_retained_helper_rejected(self):
        for chip in temperature.SELECTED:
            base, symbols = fixture(chip)
            name = temperature.RETAINED_FUNCTIONS[chip][-1]
            symbols[name] = None
            with self.assertRaisesRegex(ValueError, "Missing allocated function body"):
                temperature.check_temperature(base, symbols, "source")

    def test_retained_helper_symbol_without_vendor_input_rejected(self):
        base, symbols = fixture("esp32c3")
        symbols["get_temp_init"]["address"] = "0x42005000"
        with self.assertRaisesRegex(ValueError, "helper lacks vendor input"):
            temperature.check_temperature(base, symbols, "source")

    def test_attribute_unaligned_rejected_before_ownership_check(self):
        base, symbols = fixture("esp32c3")
        symbols["phy_tsens_attribute"]["address"] = "0x3c000001"
        with self.assertRaisesRegex(ValueError, "Unaligned retained data phy_tsens_attribute"):
            temperature.check_temperature(base, symbols, "source")

    def test_attribute_wrong_size_or_not_allocated_rejected(self):
        for field, value in (("symbol_size_bytes", 36), ("allocated", False),
                             ("body_contained", False)):
            base, symbols = fixture("esp32s3")
            symbols["phy_tsens_attribute"][field] = value
            with self.assertRaisesRegex(ValueError, "invalid retained data phy_tsens_attribute"):
                temperature.check_temperature(base, symbols, "source")

    def test_retained_state_layout_is_chip_specific(self):
        base, symbols = fixture("esp32c3")
        symbols["phy_param"]["symbol_size_bytes"] = 740
        with self.assertRaisesRegex(ValueError, "invalid retained data phy_param"):
            temperature.check_temperature(base, symbols, "source")

    def test_source_body_must_be_real_allocated_executable_function(self):
        for field, value in (("symbol_size_bytes", 0), ("executable", False),
                             ("allocated", False), ("body_contained", False),
                             ("type", "STT_OBJECT")):
            base, symbols = fixture("esp32c3")
            symbols["__opensensor_tsens_inner"][field] = value
            with self.assertRaisesRegex(ValueError, "Missing allocated function body"):
                temperature.check_temperature(base, symbols, "source")

    def test_source_symbol_cannot_name_retained_vendor_body(self):
        base, symbols = fixture("esp32c3")
        symbols["__opensensor_tsens_inner"] = copy.deepcopy(symbols["get_temp_init"])
        symbols["tsens_temp_read1"]["address"] = symbols["get_temp_init"]["address"]
        with self.assertRaisesRegex(ValueError, "Source body aliases retained vendor"):
            temperature.check_temperature(base, symbols, "source")

    def test_source_body_partially_overlapping_vendor_input_rejected(self):
        base, symbols = fixture("esp32s3")
        helper_address = int(symbols["get_temp_init"]["address"], 0)
        symbols["__opensensor_tsens_inner"]["address"] = hex(helper_address - 8)
        symbols["ram_tsens_temp_read_new"]["address"] = hex(helper_address - 8)
        with self.assertRaisesRegex(ValueError, "Source body aliases retained vendor"):
            temperature.check_temperature(base, symbols, "source")

    def test_c3_code_callback_rom_veneer_reference_retained(self):
        base, symbols = fixture("esp32c3")
        symbols["rom_tsens_code_read"]["address"] = "0x42001000"
        with self.assertRaisesRegex(ValueError, "changed ROM reference symbol"):
            temperature.check_temperature(base, symbols, "source")

    def test_vendor_image_rejects_source_symbol(self):
        base, symbols = fixture("esp32s3", "vendor")
        symbols["__opensensor_tsens_decode"] = symbol(0x42001000)
        with self.assertRaisesRegex(ValueError, "Source temperature symbol in vendor"):
            temperature.check_temperature(base, symbols, "vendor")

    def test_vendor_symbol_without_original_input_rejected(self):
        base, symbols = fixture("esp32s3", "vendor")
        base["allocations"]["libphy.a"]["inputs"] = [
            row for row in base["allocations"]["libphy.a"]["inputs"]
            if row["section"] != ".text.tsens_dac_to_index"]
        with self.assertRaisesRegex(ValueError, "Original temperature body lacks input"):
            temperature.check_temperature(base, symbols, "vendor")

    def test_previous_source_milestone_gates_remain_required(self):
        for regression, message in (("libpp", "no allocated libpp"),
                                    ("printf", "Unexpected printf"),
                                    ("dispatcher", "dispatcher still allocated"),
                                    ("wrapper", "wrapper still allocated")):
            base, symbols = fixture("esp32c3")
            if regression == "libpp":
                base["allocations"]["libpp.a"]["bytes"] = 4
            elif regression == "printf":
                base["allocations"]["prebuilt_printf"]["bytes"] = 4
            elif regression == "dispatcher":
                base["selected_allocated_symbols"]["ram_tx_pwctrl_background"] = {"size_bytes": 122}
            else:
                base["selected_allocated_symbols"]["phy_bbpll_en_usb"] = {"size_bytes": 14}
            with self.subTest(regression=regression), self.assertRaisesRegex(ValueError, message):
                temperature.check_temperature(base, symbols, "source")


if __name__ == "__main__":
    unittest.main()
