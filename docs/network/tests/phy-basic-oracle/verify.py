#!/usr/bin/env python3
"""Execute the original linked PHY basic instructions with observable boundaries."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

MASK = 0xffffffff
SUPPORTED = {'addi','addi.n','sw','jal','lui','lw','slli','bltz','bgez','j','li','bne','and','or','lb','jr',
             'entry','call8','callx8','l32r','memw','l32i.n','s32i.n','bbsi','bany','retw.n','extui','bnei','l8ui',
             'sext','bgeui','sub','mull','mulsh','srai','add.n','bltu','mov.n','movi.n'}
CONDITIONAL = ('bltz','bgez','bne','bbsi','bany','bnei','bgeui','bltu')

def require(ok, message):
    if not ok:
        raise ValueError(message)

def signed(value, width=32):
    value &= (1 << width)-1
    return value-(1 << width) if value >> (width-1) else value

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
            require(op in SUPPORTED, 'Unsupported instruction')
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
            if op in ('ret', 'retw.n', 'jr'):
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
    require(len(starts) in (2, 3) and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts


class Oracle:
    def __init__(self,chip,evidence):
        require(chip in ('esp32c3','esp32s3'),'Unknown chip')
        self.chip,self.e=chip,evidence
        self.program,self.starts=decode(evidence)
        require(len(self.starts)==(2 if chip=='esp32c3' else 3),'Wrong function count')
        self.param=int(evidence['symbols']['phy_param']['address'],0)
        self.critical=int(evidence['symbols']['phy_i2c_enter_critical']['address'],0)
        require(self.critical==int(evidence['symbols']['phy_i2c_exit_critical']['address'],0),'Expected coalesced critical no-ops')
        self.power=int(evidence['symbols']['phy_set_most_tpw']['address'],0)
        require(self.critical!=self.power,'Aliased distinct helpers')

    def run(self,case):
        require(len(case)==16 and all(0<=x<=MASK for x in case),'Invalid case words')
        operation,arg,h0,h1,n0,n1,after0,after1,mmio,p14,pother,enter_xor,c0,c1,c2,reserved=case
        require(operation<len(self.starts) and max(n0,n1)<=8 and reserved==0,'Invalid case domain')
        s3=self.chip=='esp32s3';trace=[];stack={};critical_calls=0
        hosts=[h0,h1];remaining=[n0,n1];reset=[False,False];after=[after0,after1]
        def event(kind,*args):
            require(len(args)<=4,'Oversized event')
            trace.extend((kind,*(x&MASK for x in args),*([0]*(4-len(args)))))
        def read(address,width):
            if width==4 and address in (0x6000e000,0x6000e004):
                index=(address-0x6000e000)//4
                if not reset[index]:value=hosts[index]
                else:
                    value=after[index]&~(1<<25)
                    if remaining[index]:value|=1<<25;remaining[index]-=1
                event(7,address,value);return value
            if width==4 and address==0x6001c400:event(7,address,mmio);return mmio
            if width==1 and address-self.param in (0xe4,0x98):
                offset=address-self.param;value=(p14 if offset==0xe4 else pother)&255
                event(1,1,offset,value);return value
            if s3 and width==1 and 0x71000000<=address<0x71000003:
                offset=address-0x71000000;value=case[12+offset]&255;event(3,1,offset,value);return value
            if address in stack and width==4:return stack[address]
            raise ValueError('Unknown read address/width')
        def write(address,width,value):
            nonlocal mmio
            if width==4 and address in (0x6000e000,0x6000e004):
                index=(address-0x6000e000)//4;require(value==1<<26 and not reset[index],'Unexpected reset command')
                reset[index]=True;event(8,address,value)
            elif width==4 and address==0x6001c400:mmio=value;event(8,address,value)
            else:
                require(width==4 and address%4==0 and 0x100000<=address<0x100100,'Non-stack store');stack[address]=value
        def opaque(target,regs):
            nonlocal critical_calls
            if target==self.critical:
                event(9,0);critical_calls+=1;require(critical_calls<=2,'Extra critical call')
                if critical_calls==1:hosts[0]^=enter_xor;hosts[1]^=enter_xor
            elif target==self.power:event(9,1,regs['a10' if s3 else 'a0'])
            else:raise ValueError('Unknown helper')
            return 0xdeadbeef

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
            for step in range(1000):
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
                elif op in ('add', 'add.n', 'mul', 'mull', 'addx2', 'sub', 'or', 'and', 'mulsh', 'div'):
                    left, right = regs[args[1]], regs[args[2]]
                    if op in ('mul','mull'): value = left*right
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
                    left=regs[args[0]]
                    if op=='bltz':taken=signed(left)<0
                    elif op=='bgez':taken=signed(left)>=0
                    elif op=='bne':taken=left!=regs[args[1]]
                    elif op=='bnei':taken=left!=(int(args[1],0)&MASK)
                    elif op=='bbsi':taken=bool(left&(1<<int(args[1],0)))
                    elif op=='bany':taken=bool(left&regs[args[1]])
                    elif op=='bgeui':taken=left>=int(args[1],0)
                    elif op=='bltu':taken=left<regs[args[1]]
                    else:raise ValueError('Unknown conditional')
                    if taken:next_pc=int(args[-1],16)
                elif op in ('j','jr'):
                    target=int(args[0],16) if op=='j' else regs[args[0]]
                    if target not in self.program:return opaque(target,regs)
                    next_pc=target
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
        registers.update(({'a2':0x71000000,'a3':arg} if operation==2 else {'a2':arg}) if s3 else {'a0':arg})
        result = execute(self.starts[operation], registers)
        return (result if operation == 2 else 0), trace


def default_case(operation):
    return [operation,0,0,0,0,0,0x80100001,0x40200002,0xa5a5a5a5,0x81,0x7e,0,0x80,0x7f,0xfe,0]

def cases(chip):
    patterns=(0,1,1<<25,1<<26,0x80000000,MASK,0xaaaaaaaa,0x55555555)
    for h0 in patterns:
        for h1 in patterns:
            for n0 in (0,1,2,5):
                for n1 in (0,1,2,5):
                    for mutation in (0,1<<25,0x80000000,MASK):
                        c=default_case(0);c[2:6]=h0,h1,n0,n1;c[11]=mutation;yield c
    arguments=(0,1,2,255,256,257,511,65537,0x80000001,0xffffff01,MASK)
    for argument in arguments:
        for power in range(256):
            for previous in patterns:
                c=default_case(1);c[1]=argument;c[8:11]=previous,power,power^255;yield c
    for argument in range(256):
        c=default_case(1);c[1]=argument;yield c
    for bit in range(32):
        for previous in (1<<bit,MASK^(1<<bit)):
            for argument in (0,1,257):
                c=default_case(1);c[1]=argument;c[8]=previous;yield c
    if chip=='esp32s3':
        # Every signed-byte pair and every interpolation coefficient in both segments.
        for channel in range(1,12):
            for left in range(256):
                for right in range(256):
                    c=default_case(2);c[1]=channel
                    if channel<=6:c[12:14]=left,right
                    else:c[13:15]=left,right
                    yield c
        for channel in (*range(256),256,257,0x80000001,0xffffff06,MASK):
            for value in range(256):
                c=default_case(2);c[1]=channel;c[12:15]=value,value^0x80,value^0xff;yield c

def stream(chip, output):
    data=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
    oracle=Oracle(chip,data[chip]);digest=hashlib.sha256();count=0;coverage=[0]*len(oracle.starts)
    for case in cases(chip):
        result,trace=oracle.run(case)
        require(len(trace)%5==0,'Invalid trace shape')
        words=case+[result,len(trace)//5]+trace
        packed=struct.pack('<'+'I'*len(words),*words)
        output.write(packed);digest.update(packed);count+=1;coverage[case[0]]+=1
    require(all(coverage),'Uncovered function')
    return {'cases':count,'operations':coverage,'case_stream_sha256':digest.hexdigest(),
            'fixture_sha256':hashlib.sha256(json.dumps(data[chip],sort_keys=True).encode()).hexdigest()}


def main():
    require(len(sys.argv)==3,'Usage: verify.py esp32c3|esp32s3 output.bin')
    chip=sys.argv[1];require(chip in ('esp32c3','esp32s3'),'Unknown chip')
    with Path(sys.argv[2]).open('wb') as output: result=stream(chip,output)
    expected=json.loads(Path(__file__).with_name('expected-results.json').read_text())[chip]
    require(result==expected,'Oracle results differ from reviewed fixture')
    print(json.dumps({chip:result}))


if __name__=='__main__':main()
