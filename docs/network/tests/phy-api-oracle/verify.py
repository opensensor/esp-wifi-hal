#!/usr/bin/env python3
"""Execute the original linked PHY API instructions with observable boundaries."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

MASK = 0xffffffff
SUPPORTED = {'addi','andi','auipc','bnez','jal','jalr','lbu','li','lui','lw','ori','ret','sb','sw',
             'addmi','and','bany','call8','callx8','entry','extui','l32i','l32i.n','l32r','l8ui',
             'memw','movi','movi.n','or','retw.n','s32i','s32i.n'}
CONDITIONAL = ('beq', 'beqi', 'blt', 'bge', 'bne', 'beqz', 'beqz.n',
               'bnez', 'bnez.n', 'blez', 'bgtz', 'blti', 'bany')

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
    require(len(starts) in (3, 4) and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts


class Oracle:
    def __init__(self, chip, evidence):
        require(chip in ('esp32c3','esp32s3'), 'Unknown chip')
        self.chip,self.e=chip,evidence
        self.program,self.starts=decode(evidence)
        require(len(self.starts)==(3 if chip=='esp32c3' else 4), 'Wrong chip function count')
        self.param=int(evidence['symbols']['phy_param']['address'],0)
        self.param_size=evidence['symbols']['phy_param']['size_bytes']
        require(self.param_size==(848 if chip=='esp32c3' else 740),'Unexpected parameter size')
        self.table_var=int(evidence['symbols']['g_phyFuns']['address'],0)
        names=(['ram1_phy_wakeup_init','get_rf_freq_init',None,'rom1_tsens_temp_read','ram1_phy_close_rf']
               if chip=='esp32c3' else ['ram_phy_wakeup_init','get_rf_freq_init',None,None,'ram_phy_close_rf'])
        self.helpers={int(evidence['symbols'][name]['address'],0):kind for kind,name in enumerate(names) if name}
        require(len(self.helpers)==sum(n is not None for n in names),'Aliased opaque helper')

    def run(self, case):
        require(len(case)==16 and all(0<=x<=MASK for x in case),'Invalid case words')
        operation,arg,flags,channel,off,closed,register,mutations,table_mask,*_=case
        require(operation<len(self.starts) and mutations<32 and table_mask<32,'Invalid operation or hooks')
        s3=self.chip=='esp32s3';slot=0xcc if s3 else 0xd8
        mem=bytearray([0xa5])*self.param_size
        mem[0x120:0x124]=flags.to_bytes(4,'little');mem[0x1f2]=channel&255
        if not s3:mem[0x31f],mem[0x320]=off&255,closed&255
        generation=0;trace=[];stack={};mmio=register
        def event(kind,*args):
            require(len(args)<=4,'Oversized event')
            trace.extend((kind,*(a&MASK for a in args),*([0]*(4-len(args)))))
        def read(address,width):
            if self.param<=address and address+width<=self.param+self.param_size:
                offset=address-self.param
                require((width==4 and offset==0x120) or (width==1 and offset in (0x1f2,0x31f)), 'Unexpected parameter read')
                value=int.from_bytes(mem[offset:offset+width],'little');event(1,width,offset,value);return value
            if address==self.table_var and width==4:
                event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=address<0x70010000 and width==4:
                active,offset=divmod(address-0x70000000,0x1000)
                require(active<=generation and offset==slot,'Unknown table slot')
                event(5,offset,active);return 0x71000000+active*0x1000+offset
            if s3 and address==0x6001c400 and width==4:
                event(7,address,mmio);return mmio
            if address in stack and width==4:return stack[address]
            raise ValueError(f'Unmapped read {address:x}/{width}')
        def write(address,width,value):
            nonlocal mmio
            value&=(1<<(width*8))-1
            if self.param<=address and address+width<=self.param+self.param_size:
                offset=address-self.param
                require((width==4 and offset==0x120) or (not s3 and width==1 and offset==0x320),'Unexpected parameter write')
                mem[offset:offset+width]=value.to_bytes(width,'little');event(2,width,offset,value)
            elif s3 and address==0x6001c400 and width==4:
                mmio=value;event(8,address,value)
            else:
                require(width==4 and address%4==0 and 0x100000<=address<0x100100,'Non-stack store')
                stack[address]=value
        def opaque(target,regs):
            nonlocal generation
            if target in self.helpers:
                kind=self.helpers[target];event(9,kind)
            else:
                require(0x71000000<=target<0x71010000,'Unknown helper')
                active,offset=divmod(target-0x71000000,0x1000)
                require(active<=generation and offset==slot,'Unknown callback')
                event(6,slot,active,regs['a10' if s3 else 'a0']);kind=2
            if mutations&(1<<kind):
                if kind<3:mem[0x120:0x124]=case[9+kind].to_bytes(4,'little')
                if kind<2:mem[0x1f2]=case[12+kind]&255
                if not s3 and kind==3:mem[0x31f]=case[14]&255
                if not s3 and kind==4:mem[0x320]=case[15]&255
            if table_mask&(1<<kind):generation+=1
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
                    if op == 'bany': taken = bool(left & regs[args[1]])
                    elif op in ('beqz','beqz.n'): taken = left==0
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
        registers.update({'a2': arg} if s3 else {'a0': arg})
        result = execute(self.starts[operation], registers)
        return (result if operation == 2 else 0), trace


def default_case(operation):
    return [operation,0,0,7,0,0xa5,0x5a5aa5a5,0,0,
            0x80000020,0x12345678,0xdeadbe8f,0xe1,0x12,0x81,0x7e]


def cases(chip):
    patterns=(0,0x20,0x80000000,0x80000020,0xffffffdf,MASK,0x5a5a5a5a,0xa5a5a5a5)
    for channel in range(256):
        for flags in patterns:
            for mutations in range(8):
                for table in (0,1,2,3,7):
                    c=default_case(0);c[2:4]=flags,channel;c[7:9]=mutations,table
                    c[9:12]=flags^0x20,flags^0x80010001,flags^0xfedcba98
                    c[12:14]=channel^255,channel^0x55
                    yield c
    for bit in range(32):
        for flags in (1<<bit,MASK^(1<<bit)):
            for mutations in range(8):
                c=default_case(0);c[2]=flags;c[7]=mutations;c[9:12]=flags^0x20,flags^0x20,flags
                yield c
    for off in range(256):
        for mutations in (0,8,16,24):
            for closed in (0,1,255):
                for table in (0,8,16,24):
                    c=default_case(1);c[4:6]=off,closed;c[7:9]=mutations,table
                    yield c
    yield default_case(2)
    if chip=='esp32s3':
        for argument in (*range(512),0x80000000,0x8000007f,0xffffff80,MASK):
            for previous in (*patterns,*(1<<b for b in range(32)),*(MASK^(1<<b) for b in range(32))):
                c=default_case(3);c[1]=argument;c[6]=previous;yield c


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
