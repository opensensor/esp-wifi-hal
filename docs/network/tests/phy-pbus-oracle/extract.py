#!/usr/bin/env python3
"""Extract bounded PBUS instructions/constants from the pinned private ELF.

Requires pyelftools and the chip's GNU objdump. Neither firmware nor live
calibration/network data is published. Addresses below are pinned ELF facts,
not a general binary discovery algorithm.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
from elftools.elf.elffile import ELFFile

NAMES = {
    'esp32c3': ['ram_pbus_force_mode', 'txcal_debuge_mode', 'txcal_work_mode',
                'save_pbus_reg', 'set_pbus_mem'],
    'esp32s3': ['txcal_debuge_mode', 'txcal_work_mode', 'save_pbus_reg', 'set_pbus_mem'],
}
REGIONS = {
    'esp32c3': [('jump_table', 0x3c00a174, 40), ('constant_words', 0x3c00a1a4, 60)],
    'esp32s3': [('jump_table', 0x3c00a85c, 40), ('constant_words', 0x3c00a80c, 80)],
}
CONDITIONAL = ('beq', 'beqi', 'bne', 'beqz', 'beqz.n', 'bnez', 'bnez.n', 'bltu')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def extract(chip, path, objdump, baseline):
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == baseline['elf_sha256'], 'ELF hash differs')
    elf = ELFFile(io.BytesIO(raw))
    symbols = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()}

    def read(address, size):
        for section in elf.iter_sections():
            start = section['sh_addr']
            if start <= address and address + size <= start + section['sh_size']:
                return section.data()[address-start:address-start+size]
        raise ValueError('Unmapped ELF read')

    regions = []
    for purpose, address, size in REGIONS[chip]:
        data = read(address, size)
        regions.append({'purpose': purpose, 'address': hex(address), 'size_bytes': size,
                        'sha256': hashlib.sha256(data).hexdigest(), 'data_hex': data.hex()})
    jump = bytes.fromhex(regions[0]['data_hex'])
    targets = [int.from_bytes(jump[i:i+4], 'little') for i in range(0, len(jump), 4)]
    functions, literals = [], {}
    for name in NAMES[chip]:
        symbol = symbols[name]
        start, size = symbol['st_value'], symbol['st_size']
        body = read(start, size)
        require(size > 0, 'Missing function body')
        pending, program = [start], {}
        while pending:
            address = pending.pop()
            if address in program:
                continue
            require(start <= address < start + size, 'Branch outside function')
            # In particular, the S3 jump table enters 0x4203ac52, following
            # padding at 0x4203ac51. Linear decoding invents a mul16u there.
            output = subprocess.check_output([objdump, '-d', f'--start-address={address}',
                                              f'--stop-address={start+size}', str(path)], text=True)
            match = re.search(r'^[ \t]*([0-9a-f]+):[ \t]+([0-9a-f]+)[ \t]+(\S+)(?:[ \t]+([^\n]*))?$', output, re.M)
            require(match is not None and int(match[1], 16) == address, 'Missing instruction')
            encoded, op = match[2], match[3]
            args = re.split(r'\s*[<#]', match[4] or '')[0].strip()
            width = len(encoded) // 2
            require(width in (2, 3, 4), 'Unsupported width')
            require(int(encoded, 16).to_bytes(width, 'little') == read(address, width), 'Byte mismatch')
            program[address] = f'{address:x}: {encoded} {op}' + (f' {args}' if args else '')
            if op == 'l32r':
                literal = int(args.split(',')[1], 16)
                literals[hex(literal)] = hex(int.from_bytes(read(literal, 4), 'little'))
            if op in ('ret', 'retw.n'):
                continue
            if op in ('jr', 'jx'):
                if name == 'set_pbus_mem':
                    require(op == ('jr' if chip == 'esp32c3' else 'jx'), 'Unexpected indirect jump')
                    pending.extend(targets)
                else:
                    require(chip == 'esp32c3' and name in ('txcal_debuge_mode', 'txcal_work_mode')
                            and args == 't1', 'Unknown indirect tail call')
                continue
            if op == 'j':
                target = int(args.split(',')[-1], 16)
                if start <= target < start + size:
                    pending.append(target)
                else:
                    require(name == 'set_pbus_mem' and target == symbols['save_pbus_reg']['st_value'],
                            'Unknown tail target')
                continue
            if op in CONDITIONAL or op == 'loop':
                pending.append(int(args.split(',')[-1], 16))
            pending.append(address + width)
        functions.append({'name': name, 'address': hex(start), 'size_bytes': size,
                          'body_sha256': hashlib.sha256(body).hexdigest(), 'code_hex': body.hex(),
                          'instructions': [program[a] for a in sorted(program)]})
    recorded = {name: {'address': hex(symbols[name]['st_value']), 'size_bytes': symbols[name]['st_size']}
                for name in ('phy_param', 'g_phyFuns', 'memcpy', 'ets_delay_us', 'stop_tx_tone')}
    return {'elf_sha256': baseline['elf_sha256'], 'map_sha256': baseline['map_sha256'],
            'functions': functions, 'symbols': recorded, 'literals': literals, 'regions': regions}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('chip', choices=NAMES)
    p.add_argument('elf', type=Path)
    p.add_argument('objdump')
    p.add_argument('output', type=Path)
    args = p.parse_args()
    baseline = json.loads(Path(__file__).parents[2].joinpath('phy-sensor-lifecycle-validation.json').read_text())
    result = extract(args.chip, args.elf, args.objdump, baseline['allocations'][args.chip+'/source-v2'])
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
