#!/usr/bin/env python3
"""Interpret only the five pinned temperature routines; analog calls stay opaque."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

MASK = 0xffffffff


def require(ok, message):
    if not ok:
        raise ValueError(message)


def signed(value, width=32):
    value &= (1 << width) - 1
    return value - (1 << width) if value >> (width-1) else value


def decode(evidence):
    program, starts = {}, []
    for function in evidence['functions']:
        start, size = int(function['address'], 0), function['size_bytes']
        body = bytes.fromhex(function['code_hex'])
        require(len(body) == size, 'Code size differs')
        require(hashlib.sha256(body).hexdigest() == function['body_sha256'], 'Code hash differs')
        starts.append(start)
        covered = set()
        for line in function['instructions']:
            match = re.fullmatch(r'([0-9a-f]+): ([0-9a-f]+) (\S+)(?: (.*))?', line)
            require(match is not None, 'Malformed instruction')
            address, raw, op, args = match.groups()
            address, width = int(address, 16), len(raw)//2
            require(width in (2, 3, 4) and start <= address and address+width <= start+size,
                    'Instruction out of range')
            offsets = set(range(address-start, address-start+width))
            require(not covered.intersection(offsets) and address not in program, 'Overlapping instruction')
            covered.update(offsets)
            require(int(raw, 16).to_bytes(width, 'little') == body[address-start:address-start+width],
                    'Instruction bytes differ')
            program[address] = (address+width, op, [a.strip() for a in (args or '').split(',') if a.strip()])
        # Reachability, not sequential decoding: the two zero padding bytes
        # following S3's first selector return are intentionally not executed.
        require(all(body[i] == 0 for i in set(range(size))-covered), 'Unrecorded nonzero code')
        pending, reached = [start], set()
        while pending:
            address = pending.pop()
            if address in reached:
                continue
            require(address in program, 'Unknown branch target')
            reached.add(address)
            next_pc, op, args = program[address]
            if op in ('ret', 'retw.n'):
                continue
            if op == 'j':
                target = int(args[0], 16)
                if start <= target < start+size:
                    pending.append(target)
                continue
            if op in ('beq', 'beqi', 'blt', 'bge'):
                pending.append(int(args[-1], 16))
            pending.append(next_pc)
        require(reached == {a for a in program if start <= a < start+size}, 'Unreachable fixture instruction')
    require(len(starts) == 5 and len(set(starts)) == 5, 'Expected five functions')
    return program, starts


class Oracle:
    def __init__(self, chip, evidence):
        require(chip in ('esp32c3', 'esp32s3'), 'Unknown chip')
        self.chip, self.e = chip, evidence
        self.program, self.starts = decode(evidence)
        self.param = int(evidence['symbols']['phy_param']['address'], 0)
        self.param_size = evidence['symbols']['phy_param']['size_bytes']
        require(self.param_size == (848 if chip == 'esp32c3' else 740), 'Unexpected parameter size')
        self.table_var = int(evidence['symbols']['g_phyFuns']['address'], 0)
        self.attr = int(evidence['symbols']['phy_tsens_attribute']['address'], 0)
        self.attr_bytes = bytes(evidence['attribute_bytes'])
        require(evidence['symbols']['phy_tsens_attribute']['size_bytes'] == len(self.attr_bytes) == 30,
                'Expected five attribute rows')

    def run(self, case):
        operation, arg0, arg1, dac, code, temperature, initial, hooks, after_code, after_conversion = case
        require(0 <= operation <= 4 and hooks < 64, 'Invalid case')
        s3 = self.chip == 'esp32s3'
        mem = bytearray(self.param_size)
        mem[0xaa] = initial & 255
        generation = 0
        trace, stack = [], {}
        slots = [0x188, 0x1e4, 0x1f4, 0x198] if s3 else [0x1ac, 0x208, 0x218, 0x1bc]

        def event(kind, *args):
            require(len(args) <= 8, 'Oversized event')
            trace.extend((kind, *(a & MASK for a in args), *([0]*(8-len(args)))))

        def read(address, width):
            if self.param <= address and address+width <= self.param+self.param_size:
                offset = address-self.param
                require(width == 1 and offset == 0xaa, 'Unexpected parameter read')
                value = int.from_bytes(mem[offset:offset+width], 'little')
                event(1, width, offset, value)
                return value
            if self.attr <= address < self.attr+0x1000:
                offset = address-self.attr
                require(width in (1, 2) and offset+width <= 30, 'Attribute index outside five-row domain')
                value = int.from_bytes(self.attr_bytes[offset:offset+width], 'little')
                event(3, width, offset, value)
                return value
            if address == self.table_var and width == 4:
                event(4, generation)
                return 0x70000000 + generation*0x1000
            if 0x70000000 <= address < 0x70010000 and width == 4:
                active, offset = divmod(address-0x70000000, 0x1000)
                require(active <= generation and offset in slots, 'Unknown callback slot')
                event(5, offset, active)
                return 0x71000000 + active*0x1000 + offset
            if address in stack and width == 4:
                return stack[address]
            raise ValueError(f'Unmapped read {address:x}/{width}')

        def write(address, width, value):
            value &= (1 << (width*8))-1
            if self.param <= address and address+width <= self.param+self.param_size:
                offset = address-self.param
                require((width, offset) in ((1, 0xaa), (2, 0x92)), 'Unexpected parameter write')
                mem[offset:offset+width] = value.to_bytes(width, 'little')
                event(2, width, offset, value)
            else:
                require(width == 4 and 0x100000 <= address < 0x100100, 'Non-stack store')
                stack[address] = value

        def opaque(target, regs):
            nonlocal generation
            require(0x71000000 <= target < 0x71010000, 'Unknown callback target')
            active, slot = divmod(target-0x71000000, 0x1000)
            require(active <= generation and slot in slots, 'Unknown callback slot')
            helper = slots.index(slot)
            count = (3, 0, 2, 6)[helper]
            arguments = [regs[f'a{i+(10 if s3 else 0)}'] & MASK for i in range(count)]
            event(6, slot, active, *arguments, *([0]*(6-count)))
            if helper == 0:
                require(arguments == [105, 0, 6], 'DAC read arguments differ')
            elif helper == 3:
                require(arguments[:5] == [105, 0, 6, 3, 0], 'DAC write arguments differ')
            if hooks & (1 << helper):
                generation += 1
            if helper == 1 and hooks & 16:
                mem[0xaa] = after_code & 255
            if helper == 2 and hooks & 32:
                mem[0xaa] = after_conversion & 255
            return (dac, code, temperature, 0xabcdef01)[helper] & MASK

        def new_registers():
            regs = {f'a{i}': 0 for i in range(16)}
            regs.update(sp=0x100100, ra=0, s0=0, s1=0, s2=0, s3=0, t0=0, t1=0, t2=0)
            return regs

        def clobber(regs, value):
            for name in ([f'a{i}' for i in range(8, 16)] if s3 else
                         [f'a{i}' for i in range(8)] + ['t0', 't1', 't2']):
                regs[name] = 0xdeadbeef
            regs['a10' if s3 else 'a0'] = value & MASK

        def execute(pc, regs, depth=0):
            require(depth < 6, 'Call nesting budget exhausted')
            for step in range(200):
                require(pc in self.program, 'Unknown branch target')
                next_pc, op, args = self.program[pc]
                if op == 'entry':
                    require(s3 and step == 0 and args == ['a1', '32'], 'Unexpected entry')
                elif op in ('mv', 'mov.n'):
                    regs[args[0]] = regs[args[1]]
                elif op in ('li', 'movi', 'movi.n'):
                    regs[args[0]] = int(args[1], 0) & MASK
                elif op == 'lui':
                    regs[args[0]] = (int(args[1], 0) << 12) & MASK
                elif op == 'addi':
                    regs[args[0]] = (regs[args[1]] + int(args[2], 0)) & MASK
                elif op in ('add', 'mul', 'addx2'):
                    left, right = regs[args[1]], regs[args[2]]
                    regs[args[0]] = (left*right if op == 'mul' else
                                     2*left+right if op == 'addx2' else left+right) & MASK
                elif op == 'andi':
                    regs[args[0]] = regs[args[1]] & (int(args[2], 0) & MASK)
                elif op == 'extui':
                    regs[args[0]] = (regs[args[1]] >> int(args[2])) & ((1 << int(args[3]))-1)
                elif op == 'sext':
                    regs[args[0]] = signed(regs[args[1]], int(args[2])+1) & MASK
                elif op == 'movnez':
                    if regs[args[2]] != 0:
                        regs[args[0]] = regs[args[1]]
                elif op == 'l32r':
                    literal = hex(int(args[1], 16))
                    require(literal in self.e['literals'], 'Unrecorded literal')
                    regs[args[0]] = int(self.e['literals'][literal], 0)
                elif op in ('lw', 'lbu', 'lb', 'lh', 'sw', 'sb', 'sh'):
                    match = re.fullmatch(r'(-?\d+)\((\w+)\)', args[1])
                    require(match is not None, 'Bad memory operand')
                    address = (regs[match[2]] + int(match[1])) & MASK
                    width = {'lw':4, 'lbu':1, 'lb':1, 'lh':2, 'sw':4, 'sb':1, 'sh':2}[op]
                    if op in ('sw', 'sb', 'sh'):
                        write(address, width, regs[args[0]])
                    else:
                        value = read(address, width)
                        regs[args[0]] = (signed(value, width*8) if op in ('lb', 'lh') else value) & MASK
                elif op in ('l32i', 'l32i.n', 'l8ui', 'l16si', 's8i', 's16i'):
                    address = (regs[args[1]] + int(args[2], 0)) & MASK
                    width = {'l32i':4, 'l32i.n':4, 'l8ui':1, 'l16si':2, 's8i':1, 's16i':2}[op]
                    if op in ('s8i', 's16i'):
                        write(address, width, regs[args[0]])
                    else:
                        value = read(address, width)
                        regs[args[0]] = (signed(value, 16) if op == 'l16si' else value) & MASK
                elif op in ('beq', 'beqi', 'blt', 'bge'):
                    left = regs[args[0]]
                    right = int(args[1], 0) if op == 'beqi' else regs[args[1]]
                    taken = (left == right if op in ('beq', 'beqi') else
                             signed(left) < signed(right) if op == 'blt' else signed(left) >= signed(right))
                    if taken:
                        next_pc = int(args[-1], 16)
                elif op == 'j':
                    next_pc = int(args[0], 16)
                elif op in ('jal', 'call8', 'callx8', 'jalr'):
                    target = int(args[0], 16) if op in ('jal', 'call8') else regs[args[0]]
                    if op in ('jal', 'call8'):
                        require(target in self.starts, 'Unknown direct helper')
                        if s3:
                            child = new_registers()
                            child.update({f'a{i+2}': regs[f'a{i+10}'] for i in range(6)})
                            result = execute(target, child, depth+1)
                            clobber(regs, result)
                        else:
                            regs['ra'] = next_pc
                            execute(target, regs, depth+1)
                    else:
                        result = opaque(target, regs)
                        clobber(regs, result)
                elif op in ('ret', 'retw.n'):
                    require((op == 'retw.n') == s3, 'Wrong return ABI')
                    return regs['a2' if s3 else 'a0'] & MASK
                else:
                    raise ValueError(f'Unsupported instruction {op}')
                pc = next_pc
            raise ValueError('Instruction budget exhausted')

        registers = new_registers()
        registers.update({'a2': arg0 & MASK, 'a3': arg1 & MASK} if s3 else
                         {'a0': arg0 & MASK, 'a1': arg1 & MASK})
        result = execute(self.starts[operation], registers)
        return result, trace


def cases(chip):
    # Decoder has a documented sentinel result, but no fabricated sixth row.
    for dac in range(256):
        yield (0, dac, 0, 5, 0, 0, 0, 0, 0, 0)
    for dac in (0x105, 0x107, 0x10f, 0x10b, 0x10a, MASK, 0x80000005):
        yield (0, dac, 0, 5, 0, 0, 0, 0, 0, 0)
    for index in range(5):
        for temperature in range(-32768, 32768):
            yield (1, temperature & MASK, index, 5, 0, 0, 0, 0, 0, 0)
        for temperature in (0x10000, 0x10050, 0xffff7fff, 0x7fffffff, 0x80000000):
            yield (1, temperature, index, 5, 0, 0, 0, 0, 0, 0)
            if chip == 'esp32s3':
                yield (1, temperature, index | 0xabcdef00, 5, 0, 0, 0, 0, 0, 0)
    temperatures = (-32768, -31, -30, -29, -10, -9, 0, 20, 50, 79, 80, 99, 100, 125, 126, 32767,
                    0x80010005, 0xffff7fff)
    for operation in (2, 3, 4):
        for dac in range(256):
            if dac & 15 not in (5, 7, 15, 11, 10):
                continue
            for temperature in temperatures:
                yield (operation, 0, 0, dac, 0x8000abcd, temperature & MASK, 255, 0, 0, 0)
        # A decoder sentinel is stored before the code helper runs. If that
        # opaque helper supplies a valid index, no out-of-bounds read occurs.
        for dac in range(16):
            if dac in (5, 7, 15, 11, 10):
                continue
            for index in range(5):
                yield (operation, 0, 0, dac, 0x8000abcd, 35, 255, 16, index, 0)
        for hooks in range(64):
            for code_index in range(5):
                for conversion_index in range(5):
                    for temperature in (-32768, -30, -9, 0, 80, 100, 32767):
                        yield (operation, 0, 0, 0xab, 0xffffffff, temperature & MASK,
                               255, hooks, code_index, conversion_index)
        for code in (0, 1, 255, 256, 65535, 0x80000000, MASK):
            yield (operation, 0, 0, 0xf5, code, 0x80010005, 0, 63, 4, 1)


def main():
    chip, destination = sys.argv[1:]
    fixture = json.loads(Path(__file__).with_name('original-instructions.json').read_text())
    oracle = Oracle(chip, fixture['chips'][chip])
    digest, count = hashlib.sha256(), 0
    with open(destination, 'wb') as stream:
        for case in cases(chip):
            result, trace = oracle.run(case)
            words = (*case, result, len(trace)//9, *trace)
            encoded = struct.pack('<'+'I'*len(words), *words)
            stream.write(encoded)
            digest.update(encoded)
            count += 1
    report = {'chip': chip, 'cases': count, 'oracle_sha256': digest.hexdigest()}
    expected = json.loads(Path(__file__).with_name('expected-results.json').read_text())[chip]
    require(report == expected, 'Original instruction trace digest changed')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
