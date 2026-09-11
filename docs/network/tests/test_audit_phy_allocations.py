#!/usr/bin/env python3
"""Map-parser regressions require only the Python standard library."""
import unittest
from unittest.mock import patch
import sys
import types

from audit_phy_allocations import allocate, check_expectations, exclude_mergeable_strings, parse_map


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

    def test_string_exclusion_requires_object_flags_and_leaves_nonstring_overlap_checks(self):
        # Keep this regression standard-library-only: mock the archive reader's
        # metadata boundary, including GNU's per-function string-section names.
        rows = [("libphy.a", "a.o", ".rodata.str1.1", 0x42000000, 0x100, "a.a"),
                ("source_printf", "b.o", ".rodata._ftoa.str1.1", 0x42000000, 0x100, "b.a"),
                ("libphy.a", "a.o", ".text.keep", 0x42000000, 0x10, "a.a")]
        class Section(dict):
            def __init__(self, name, flags):
                super().__init__(sh_flags=flags)
                self.name=name
        class Object:
            flags=0x32
            def __init__(self, stream): pass
            def iter_sections(self):
                return [Section(".rodata.str1.1",self.flags), Section(".rodata._ftoa.str1.1",self.flags)]
        module=types.ModuleType('elftools.elf.elffile'); module.ELFFile=Object
        with patch.dict(sys.modules, {'elftools.elf.elffile':module}), patch('audit_phy_allocations.subprocess.check_output',return_value=b'object'):
            kept, excluded=exclude_mergeable_strings(rows)
            self.assertEqual(kept,rows[2:])
            self.assertEqual(len(excluded),2)
            self.assertEqual(allocate(kept,ALLOCATED)['libphy.a'][0]['size_bytes'],0x10)
            Object.flags=2
            with self.assertRaisesRegex(ValueError,'SHF_MERGE'):
                exclude_mergeable_strings(rows)

    def test_source_dispatcher_requires_old_body_absent_and_analog_helpers_present(self):
        names=['g_phyFuns','rom1_tsens_temp_read','ram2_rfpll_cap_track','rfcal_track','phy_param','register_chipv7_phy']
        symbols={n:{'size_bytes':4} for n in names}
        symbols.update(ram_tx_pwctrl_background=None,tx_pwctrl_background=None,phy_bbpll_en_usb=None)
        result={'chip':'esp32c3','selected_allocated_symbols':symbols,'allocations':{
            'libphy.a':{'bytes':100,'inputs':[]},'libpp.a':{'bytes':0}}}
        check_expectations(result,None,'source','source')
        symbols['ram_tx_pwctrl_background']={'size_bytes':122}
        with self.assertRaisesRegex(ValueError,'dispatcher still allocated'):
            check_expectations(result,None,'source','source')
        symbols['ram_tx_pwctrl_background']=None
        symbols['rfcal_track']=None
        with self.assertRaisesRegex(ValueError,'Missing retained'):
            check_expectations(result,None,'source','source')


if __name__ == "__main__":
    unittest.main()
