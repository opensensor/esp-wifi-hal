#!/usr/bin/env python3
"""Map-parser regressions require only the Python standard library."""
import unittest

from audit_phy_allocations import allocate, check_expectations, parse_map


ALLOCATED = [(".text", 0x42000000, 0x42001000), (".bss", 0x3fc80000, 0x3fc80100)]


class AllocationAuditTests(unittest.TestCase):
    def test_gnu_excludes_discarded_and_debug_but_counts_common(self):
        text = """Discarded input sections
 .text.old 0x42000000 0x10 /private/libphy.a(phy_api.o)
Linker script and memory map
 .text.keep
                0x42000010 0x10 /private/libphy.a(phy_api.o)
 COMMON         0x3fc80000 0x2a /private/libphy.a(phy_init.o)
 .debug_info
                0x01000000 0x7fff /private/libphy.a(phy_init.o)
 *fill*         0x42000020 0x10
"""
        linker, rows = parse_map(text)
        result = allocate(rows, ALLOCATED)
        self.assertEqual(linker, "GNU ld")
        self.assertEqual(sum(row["size_bytes"] for row in result["libphy.a"]), 0x3a)
        self.assertEqual([row["section"] for row in result["libphy.a"]], [".text.keep", "COMMON"])
        self.assertNotIn("private", str(result))

    def test_lld_distinguishes_prebuilt_and_bundled_source_printf(self):
        text = """     VMA      LMA     Size Align Out     In      Symbol
42000000 42000000       10     2         /private/libphy.a(phy_api.o):(.text.keep)
42000010 42000010       20     2         /private/libprintf.a(printf.c.obj):(.text.vsnprintf)
42000030 42000030       30     2         /private/libesp_wifi_sys_esp32c3-abcdef.rlib(012345-printf.o):(.text._vsnprintf)
       0        0      800     1         /private/libprintf.a(printf.c.obj):(.debug_info)
42000030 42000030       30     1                 _vsnprintf
"""
        linker, rows = parse_map(text)
        result = allocate(rows, ALLOCATED)
        self.assertEqual(linker, "LLD")
        self.assertEqual(result["prebuilt_printf"][0]["size_bytes"], 0x20)
        self.assertEqual(result["source_printf"][0]["size_bytes"], 0x30)
        self.assertEqual(len(result["source_printf"]), 1)
        self.assertFalse(result["libpp.a"])

    def test_gnu_distinguishes_source_from_prebuilt_even_with_same_archive_name(self):
        text = """Linker script and memory map
 .text.original 0x42000000 0x10 /private/baseline/libprintf.a(printf.c.obj)
 .text.source   0x42000010 0x20 /private/source/libprintf.a(012345-printf.o)
 .text.unknown  0x42000030 0x10 /private/unknown/libprintf.a(other.o)
"""
        _, rows = parse_map(text)
        result = allocate(rows, ALLOCATED)
        self.assertEqual(result["prebuilt_printf"][0]["size_bytes"], 0x10)
        self.assertEqual(result["source_printf"][0]["size_bytes"], 0x20)
        self.assertEqual(result["unknown_printf"][0]["size_bytes"], 0x10)

    def test_partial_output_section_overlap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "partially overlaps"):
            allocate([("libphy.a", "phy_api.o", ".text.keep", 0x42000ff0, 0x20)], ALLOCATED)

    def test_duplicate_input_is_rejected(self):
        row = ("libphy.a", "phy_api.o", ".text.keep", 0x42000000, 0x20)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            allocate([row, row], ALLOCATED)

    def test_overlapping_inputs_are_rejected(self):
        rows = [("libphy.a", "phy_api.o", ".text.a", 0x42000000, 0x20),
                ("libphy.a", "phy_api.o", ".text.b", 0x42000010, 0x20)]
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            allocate(rows, ALLOCATED)

    def test_unknown_map_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Expected an LLD or GNU ld"):
            parse_map("not a map")

    def test_selected_gnu_input_without_section_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no section name"):
            parse_map("Linker script and memory map\n 0x42000000 0x10 /private/libphy.a(phy_api.o)\n")

    def test_expectations_reject_prebuilt_printf_in_source_image(self):
        result = {"allocations": {
            "libphy.a": {"bytes": 1, "inputs": []}, "libpp.a": {"bytes": 0},
            "prebuilt_printf": {"bytes": 1}, "source_printf": {"bytes": 1},
        }, "selected_allocated_symbols": {
            "ram_tx_pwctrl_background": {"size_bytes": 122},
            "phy_param": {"size_bytes": 848}, "register_chipv7_phy": {"size_bytes": 1},
            "tx_pwctrl_background": None, "phy_bbpll_en_usb": None,
        }}
        with self.assertRaisesRegex(ValueError, "Unexpected printf"):
            check_expectations(result, "source", "source")


if __name__ == "__main__":
    unittest.main()
