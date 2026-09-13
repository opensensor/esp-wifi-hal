#!/usr/bin/env python3
"""Bounded original-instruction PHY sensor lifecycle oracle."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

MASK = 0xffffffff
CONDITIONAL = ('beq', 'beqi', 'blt', 'bge', 'bne', 'beqz', 'beqz.n',
               'bnez', 'bnez.n', 'blez', 'bgtz', 'blti')


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
        # Reachability, not sequential decoding: literals/padding following
        # returns must not be interpreted as instructions.
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
            if op in CONDITIONAL:
                pending.append(int(args[-1], 16))
            pending.append(next_pc)
        require(reached == {a for a in program if start <= a < start+size}, 'Unreachable fixture instruction')
    require(len(starts) in (5, 6) and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts


class Oracle:
    def __init__(self, chip, evidence):
        require(chip in ('esp32c3', 'esp32s3'), 'Unknown chip')
        self.chip, self.e = chip, evidence
        self.program, self.starts = decode(evidence)
        require(len(self.starts) == (5 if chip == 'esp32c3' else 6), 'Unexpected chip function count')
        self.operations = (self.starts[:3] + [None] + self.starts[3:]) if chip == 'esp32c3' else self.starts
        self.param = int(evidence['symbols']['phy_param']['address'], 0)
        self.param_size = evidence['symbols']['phy_param']['size_bytes']
        require(self.param_size == (848 if chip == 'esp32c3' else 740), 'Unexpected parameter size')
        self.table_var = int(evidence['symbols']['g_phyFuns']['address'], 0)
        self.attr = int(evidence['symbols']['phy_tsens_attribute']['address'], 0)
        self.attr_bytes = bytes(evidence['attribute_bytes'])
        require(evidence['symbols']['phy_tsens_attribute']['size_bytes'] == len(self.attr_bytes) == 30,
                'Expected five attribute rows')
        self.measure = int(evidence['symbols']['__opensensor_tsens_outer']['address'], 0)

    def run(self, case):
        require(len(case) == 22 and all(0 <= x <= MASK for x in case), 'Invalid case words')
        (operation, arg0, arg1, arg2, flag, temperature, calibration, saved, second, xpd,
         reg0, reg1, reg2, reg3, read_xor, measurement, hooks, after_flag, after_calibration,
         after_saved, after_second, dac_xor) = case
        require(0 <= operation <= 5 and self.operations[operation] is not None and hooks < 128, 'Invalid case')
        s3 = self.chip == 'esp32s3'
        mem = bytearray([0xa5])*self.param_size
        cal_offset, saved_offset = (0x206, 0x20a) if s3 else (0x20c, 0x210)
        xpd_offset = 0x2a2 if s3 else 0x31f
        mem[0x204], mem[xpd_offset] = flag & 255, xpd & 255
        for offset, value in [(0x92,temperature), (cal_offset,calibration), (saved_offset,saved), (0x212,second)]:
            mem[offset:offset+2] = (value & 65535).to_bytes(2,'little')
        generation, read_count = 0, 0
        trace, stack = [], {}
        slots = [0x258] if s3 else [0x1bc]
        addresses = [0x60008850,0x60008034,0x60008904] if s3 else [0x60040058,0x600c0014,0x600c001c,0x6004005c]
        mmio = dict(zip(addresses,[reg0,reg1,reg2,reg3]))

        def event(kind, *args):
            require(len(args) <= 8, 'Oversized event')
            trace.extend((kind, *(a & MASK for a in args), *([0]*(8-len(args)))))

        def read(address, width):
            nonlocal read_count
            if self.param <= address and address+width <= self.param+self.param_size:
                offset = address-self.param
                require((width == 1 and offset in (0x204,xpd_offset)) or
                        (width == 2 and offset in (0x92,cal_offset,saved_offset,0x212)), 'Unexpected parameter read')
                value = int.from_bytes(mem[offset:offset+width], 'little')
                event(1, width, offset, value)
                return value
            if self.attr <= address < self.attr+0x1000:
                offset = address-self.attr
                require(width == 1 and offset+width <= 30, 'Attribute index outside five-row domain')
                value = int.from_bytes(self.attr_bytes[offset:offset+width], 'little')
                event(3, width, offset, value)
                return value
            if address in mmio:
                require(width == 4, 'Unexpected MMIO read width')
                shift = read_count % 32
                perturbation = ((read_xor << shift) | (read_xor >> ((32-shift)%32))) & MASK
                value = mmio[address] ^ perturbation
                read_count += 1
                event(7,address,value)
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
                allowed = ((width == 1 and offset == xpd_offset) or
                           (width == 2 and offset in (saved_offset,0x212,0x94,0x96,0x214,0x2c4,0x2c6)))
                require(allowed, 'Unexpected parameter write')
                mem[offset:offset+width] = value.to_bytes(width, 'little')
                event(2, width, offset, value)
            elif address in mmio:
                require(width == 4, 'Unexpected MMIO write width')
                mmio[address] = value
                event(8,address,value)
            else:
                require(width == 4 and 0x100000 <= address < 0x100100, 'Non-stack store')
                stack[address] = value

        def opaque(target, regs):
            nonlocal generation
            if not s3 and target == self.measure:
                event(9)
                helper = 'measure'
            else:
                require(0x71000000 <= target < 0x71010000, 'Unknown callback target')
                active, slot = divmod(target-0x71000000, 0x1000)
                require(active <= generation and slot in slots, 'Unknown callback slot')
                helper = 'measure' if s3 else 'dac'
                count = 0 if s3 else 6
                arguments = [regs[f'a{i+(10 if s3 else 0)}'] & MASK for i in range(count)]
                event(6,slot,active,*arguments,*([0]*(6-count)))
                if not s3:
                    require(arguments[:5] == [105,0,6,3,0], 'DAC write arguments differ')
            if helper == 'measure':
                mem[0x92:0x94] = (measurement & 65535).to_bytes(2,'little')
                if hooks & 1: mem[0x204] = after_flag & 255
                for mask,offset,value in [(2,cal_offset,after_calibration), (4,saved_offset,after_saved),
                                          (8,0x212,after_second)]:
                    if hooks & mask: mem[offset:offset+2] = (value & 65535).to_bytes(2,'little')
                if hooks & 16: generation += 1
                return measurement
            if hooks & 32: generation += 1
            if hooks & 64: mmio[addresses[0]] ^= dac_xor
            return 0xabcdef01

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
                elif op in ('addi','addi.n','addmi'):
                    regs[args[0]] = (regs[args[1]] + int(args[2], 0)) & MASK
                elif op == 'auipc':
                    regs[args[0]] = (pc + (int(args[1],0) << 12)) & MASK
                elif op in ('add', 'mul', 'addx2', 'sub', 'or', 'and', 'mulsh', 'div'):
                    left, right = regs[args[1]], regs[args[2]]
                    if op == 'mul': value = left*right
                    elif op == 'mulsh': value = (signed(left)*signed(right)) >> 32
                    elif op == 'addx2': value = 2*left+right
                    elif op == 'sub': value = left-right
                    elif op == 'or': value = left|right
                    elif op == 'and': value = left&right
                    elif op == 'div':
                        require(right != 0, 'Unexpected divide by zero')
                        left,right = signed(left),signed(right)
                        value = (abs(left)//abs(right)) * (-1 if (left<0)!=(right<0) else 1)
                    else: value = left+right
                    regs[args[0]] = value & MASK
                elif op in ('andi','ori'):
                    left,right = regs[args[1]],int(args[2],0)&MASK
                    regs[args[0]] = left&right if op=='andi' else left|right
                elif op in ('slli','srai'):
                    value = regs[args[1]]
                    shift = int(args[2],0)
                    regs[args[0]] = ((value << shift) if op=='slli' else (signed(value) >> shift)) & MASK
                elif op == 'extui':
                    regs[args[0]] = (regs[args[1]] >> int(args[2])) & ((1 << int(args[3]))-1)
                elif op == 'sext':
                    regs[args[0]] = signed(regs[args[1]], int(args[2])+1) & MASK
                elif op in ('movnez','movltz'):
                    condition = (regs[args[2]] != 0) if op=='movnez' else (signed(regs[args[2]])<0)
                    if condition:
                        regs[args[0]] = regs[args[1]]
                elif op == 'l32r':
                    literal = hex(int(args[1], 16))
                    require(literal in self.e['literals'], 'Unrecorded literal')
                    regs[args[0]] = int(self.e['literals'][literal], 0)
                elif op in ('lw', 'lbu', 'lb', 'lh', 'lhu', 'sw', 'sb', 'sh'):
                    match = re.fullmatch(r'(-?\d+)\((\w+)\)', args[1])
                    require(match is not None, 'Bad memory operand')
                    address = (regs[match[2]] + int(match[1])) & MASK
                    width = {'lw':4, 'lbu':1, 'lb':1, 'lh':2, 'lhu':2, 'sw':4, 'sb':1, 'sh':2}[op]
                    if op in ('sw', 'sb', 'sh'):
                        write(address, width, regs[args[0]])
                    else:
                        value = read(address, width)
                        regs[args[0]] = (signed(value, width*8) if op in ('lb', 'lh') else value) & MASK
                elif op in ('l32i', 'l32i.n', 'l8ui', 'l16si', 'l16ui', 's8i', 's16i','s32i','s32i.n'):
                    address = (regs[args[1]] + int(args[2], 0)) & MASK
                    width = {'l32i':4, 'l32i.n':4, 'l8ui':1, 'l16si':2,'l16ui':2,
                             's8i':1, 's16i':2,'s32i':4,'s32i.n':4}[op]
                    if op in ('s8i', 's16i','s32i','s32i.n'):
                        write(address, width, regs[args[0]])
                    else:
                        value = read(address, width)
                        regs[args[0]] = (signed(value, 16) if op == 'l16si' else value) & MASK
                elif op in CONDITIONAL:
                    left = regs[args[0]]
                    if op in ('beqz','beqz.n'): taken = left==0
                    elif op in ('bnez','bnez.n'): taken = left!=0
                    elif op == 'blez': taken = signed(left)<=0
                    elif op == 'bgtz': taken = signed(left)>0
                    else:
                        right = int(args[1],0) if op in ('beqi','blti') else regs[args[1]]
                        if op in ('beq','beqi'): taken = left==right
                        elif op == 'bne': taken = left!=right
                        elif op in ('blt','blti'): taken = signed(left)<signed(right)
                        else: taken = signed(left)>=signed(right)
                    if taken:
                        next_pc = int(args[-1], 16)
                elif op == 'j':
                    next_pc = int(args[0], 16)
                elif op in ('jal', 'call8', 'callx8', 'jalr'):
                    if op in ('jal','call8'): target = int(args[0],16)
                    elif '(' in args[0]:
                        m = re.fullmatch(r'(-?\d+)\((\w+)\)',args[0]);require(m is not None,'Bad call operand')
                        target = (regs[m[2]] + int(m[1])) & MASK
                    else: target = regs[args[0]]
                    if target in self.starts:
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
                elif op == 'memw':
                    require(s3 and not args,'Unexpected memory barrier')
                elif op in ('ret', 'retw.n'):
                    require((op == 'retw.n') == s3, 'Wrong return ABI')
                    return regs['a2' if s3 else 'a0'] & MASK
                else:
                    raise ValueError(f'Unsupported instruction {op}')
                pc = next_pc
            raise ValueError('Instruction budget exhausted')

        registers = new_registers()
        registers.update({'a2': arg0, 'a3': arg1,'a4':arg2} if s3 else
                         {'a0': arg0, 'a1': arg1,'a2':arg2})
        result = execute(self.operations[operation], registers)
        return (result if operation in (3,4) else 0), trace


def default_case(operation):
    return [operation,0,0,0, 0x22,0x123,0x4567,0x89ab,0xcdef,0,
            0xa5a55a5a,0x5a5aa5a5,0x80000001,0x40000000,0,0x8000fedc,0,
            17,0x8000,0xffff,0x7fff,0xfedcba98]


def cases(chip):
    # Exhaust every signed16 wrapping difference for both mode classes and
    # noncanonical full-register flags. Repeat all differences with raw32 bases.
    for mode in (0,1,256,MASK):
        for delta in range(65536):
            case = default_case(4)
            case[1],case[3] = delta,mode
            yield case
    for base in (0xffff0000,0x7fff8000,0x80000000,0x12345678):
        for delta in range(65536):
            case = default_case(4)
            case[1],case[2],case[3] = (base+delta)&MASK,base,delta&1
            yield case
    patterns = (0,MASK,0x400000,0x800000,0xc00000,0x1000000,0x80000000,0x5a5aa5a5)
    xors = (0,0x80000001,0x5a5aa5a5)
    flags = (0,1,255,256,0x80000000,MASK)
    for argument in (*range(256),256,257,0x7fff0000,0x80000001,MASK):
        for pattern in patterns:
            case = default_case(0)
            case[1],case[10] = argument,pattern
            yield case
    for flag in range(256):
        for pattern in patterns:
            for perturbation in xors:
                case = default_case(2)
                case[9],case[10],case[14] = flag,pattern,perturbation
                yield case
    for first in flags:
        for second in (range(5) if chip=='esp32c3' and first else (*range(5),5,255,MASK)):
            for pattern in patterns:
                for perturbation in xors:
                    for hooks in (0,32,64,96):
                        case = default_case(1)
                        case[1],case[2] = first,second
                        case[10:14] = [pattern,pattern^MASK,pattern,pattern^0x80000000]
                        case[14],case[16] = perturbation,hooks
                        yield case
    if chip=='esp32s3':
        for low in range(256):
            for pattern in patterns:
                for perturbation in xors:
                    case = default_case(3)
                    case[10],case[14] = (pattern&0xffffff00)|low,perturbation
                    yield case
    for flag in range(256):
        for first in flags:
            for second in flags:
                case = default_case(5)
                case[1],case[2],case[4] = first,second,flag
                yield case
    for hooks in range(32):
        for first in flags:
            for second in flags:
                for flag in (0,17,255):
                    for value in (0,1,0x7fff,0x8000,0xffff):
                        case = default_case(5)
                        case[1],case[2],case[16],case[17] = first,second,hooks,flag
                        case[15] = 0x80000000|value
                        case[18],case[19],case[20] = value,value^0x5555,value^0xaaaa
                        yield case

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
