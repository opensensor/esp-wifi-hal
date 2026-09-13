#!/usr/bin/env python3
"""Execute the original linked PHY feature instructions with observable boundaries."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

MASK = 0xffffffff
SUPPORTED = {'retw.n', 'lw', 'l32i', 'l32i.n', 'andi', 'div', 'mov.n', 'j', 's32i.n', 'lui', 'mul', 'l32r', 'min', 'zext.b', 'bge', 'movi', 'ori', 'movnez', 'jr', 'sw', 'jalr', 'beqz', 'addx2', 'slli', 'sb', 'memw', 'sll', 'moveqz', 'mv', 'extui', 'add.n', 'lbu', 'ssl', 'l8ui', 'entry', 's8i', 'addi', 'callx8', 'li', 'or', 'and', 'quos', 'addmi', 'movi.n', 'auipc'}
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
    require(len(starts) == 4 and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts


class Oracle:
    def __init__(self, chip, evidence):
        require(chip in ('esp32c3','esp32s3'),'Unknown chip')
        self.chip,self.e=chip,evidence
        self.program,self.starts=decode(evidence)
        self.param=int(evidence['symbols']['phy_param']['address'],0)
        self.param_size=evidence['symbols']['phy_param']['size_bytes']
        require(self.param_size==(848 if chip=='esp32c3' else 740),'Unexpected parameter size')
        self.table_var=int(evidence['symbols']['g_phyFuns']['address'],0)
        names=['rom_phy_dig_reg_backup','rom_phy_freq_mem_backup']+(['ram1_wifi_set_tx_gain'] if chip=='esp32c3' else [])
        self.helpers={int(evidence['symbols'][name]['address'],0):kind for kind,name in enumerate(names)}
        require(len(self.helpers)==len(names),'Aliased opaque helper')

    def run(self, case):
        require(len(case)==16 and all(0<=x<=MASK for x in case),'Invalid case words')
        operation,arg,second,*_=case
        require(operation<4 and all(case[i]<256 for i in [3,4,5,6,9,10,13]) and case[11]<8 and case[14:]==[0,0],'Invalid case domain')
        s3=self.chip=='esp32s3';slot=0x190 if s3 else 0x1b4
        mem=bytearray([0xa5])*self.param_size
        mem[0x166:0x169]=bytes(case[3:6]);mem[0x1f2]=case[6]
        generation=0;trace=[];stack={};mmio={0x6002600c:case[7],0x6001c030:case[8]};call_count=0
        def event(kind,*args):
            require(len(args)<=7,'Oversized event')
            trace.extend((kind,*(a&MASK for a in args),*([0]*(7-len(args)))))
        def read(address,width):
            if self.param<=address and address+width<=self.param+self.param_size:
                offset=address-self.param
                require(width==1 and offset in (0x166,0x167,0x168,0x1f2),'Unexpected parameter read')
                value=mem[offset];event(1,width,offset,value);return value
            if address==self.table_var and width==4:
                event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=address<0x70020000 and width==4:
                active,offset=divmod(address-0x70000000,0x1000)
                require(active<=generation and offset==(0x264 if operation==2 and s3 else slot),'Unknown table slot')
                event(5,offset,active);return 0x71000000+active*0x1000+offset
            if address in mmio and width==4:
                event(7,address,mmio[address]);return mmio[address]
            if address in stack and width==4:return stack[address]
            raise ValueError(f'Unmapped read {address:x}/{width}')
        def write(address,width,value):
            nonlocal generation
            value&=(1<<(width*8))-1
            if self.param<=address and address+width<=self.param+self.param_size:
                offset=address-self.param
                require(width==1 and offset in (0x98,0xef,0xf0),'Unexpected parameter write')
                mem[offset]=value;event(2,width,offset,value)
                if offset in (0x98,0xef) and case[11]&1:
                    generation+=1;mem[0x1f2]^=case[13]
            elif address in mmio and width==4:
                mmio[address]=value;event(8,address,value)
                if case[11]&2:generation+=1
                if case[11]&4:mem[0x166]^=case[13]
            else:
                require(width==4 and address%4==0 and 0x100000<=address<0x100100,'Non-stack store')
                stack[address]=value
        def opaque(target,regs):
            nonlocal generation,call_count
            a=[regs['a'+str(i+(10 if s3 else 0))] for i in range(4)]
            if target in self.helpers:
                kind=self.helpers[target]
                require((operation==kind and kind<2) or (operation==2 and kind==2),'Unexpected direct helper')
                event(9,kind,a[0],a[1]);return case[12]
            require(0x71000000<=target<0x71020000,'Unknown helper')
            active,offset=divmod(target-0x71000000,0x1000)
            require(active<=generation and offset==(0x264 if operation==2 and s3 else slot),'Unknown callback')
            if operation==2:a[2:]=[0,0]
            event(6,target,*a)
            if case[9]&(1<<call_count):generation+=1
            if case[10]&(1<<call_count):
                mem[0x167]=(mem[0x167]+case[13])&255
                mem[0x168]^=case[13]
            call_count+=1
            return case[12]

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
            for step in range(500):
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
                elif op in ('add', 'add.n', 'mul', 'addx2', 'sub', 'or', 'and', 'mulsh', 'div', 'quos', 'min'):
                    left, right = regs[args[1]], regs[args[2]]
                    if op == 'mul': value = left*right
                    elif op == 'mulsh': value = (signed(left)*signed(right)) >> 32
                    elif op == 'addx2': value = 2*left+right
                    elif op == 'sub': value = left-right
                    elif op == 'or': value = left|right
                    elif op == 'and': value = left&right
                    elif op == 'min': value = min(signed(left),signed(right))
                    elif op in ('div','quos'):
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
                elif op in ('movnez','movltz','moveqz'):
                    condition = (regs[args[2]] != 0) if op=='movnez' else ((regs[args[2]]==0) if op=='moveqz' else (signed(regs[args[2]])<0))
                    if condition:
                        regs[args[0]] = regs[args[1]]
                elif op == 'zext.b':
                    regs[args[0]] = regs[args[1]] & 255
                elif op == 'ssl':
                    regs['left_shift'] = regs[args[0]] & 31
                elif op == 'sll':
                    require('left_shift' in regs,'Missing shift state')
                    regs[args[0]] = (regs[args[1]] << regs['left_shift']) & MASK
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
                elif op in ('j','jr'):
                    if op=='j':target=int(args[0],16)
                    elif '(' in args[0]:
                        m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[0]);require(m is not None,'Bad tail operand')
                        target=(regs[m[2]]+int(m[1]))&MASK
                    else:target=regs[args[0]]
                    if op=='jr':target &= ~1
                    if target in self.program:next_pc=target
                    else:return opaque(target,regs)

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
        registers.update({'a2': arg,'a3':second} if s3 else {'a0': arg,'a1':second})
        result = execute(self.starts[operation], registers)
        return (result if operation == 0 else 0), trace

def default_case(operation):
    return [operation,0,0,127,0x81,0x7e,7,0xa5a5a5a5,0x5a5a5a5a,0,0,0,0xdecafbad,0x5b,0,0]

def cases(chip):
    raw=(*range(256),256,257,0x80000000,0xffffff00,0xffffffff)
    for operation in (0,1):
        for argument in raw:
            for buffer in (0,4,0x3fc81234,0x3fc8fffc):
                for result in (0,1,21,255,0xdeadbeef):
                    c=default_case(operation);c[1:3]=argument,buffer;c[12]=result;yield c
    for argument in raw:
        for channel in range(256):
            for mutation in (0,1):
                c=default_case(2);c[1]=argument;c[6]=channel;c[11]=mutation;yield c
    patterns=(0,MASK,0x1c,0x20,0x80000000,0xa5a5a5a5)
    for enable in (0,1,2,255,256,257,0x80000000,MASK):
        for narrow in (0,1,255,256,257,MASK):
            for parameter in range(256):
                for writes in (0,1,2,4,7):
                    c=default_case(3);c[1:6]=enable,narrow,parameter,parameter^0xa5,parameter^0x5a
                    c[7]=patterns[parameter%len(patterns)];c[8]=patterns[(parameter+1)%len(patterns)]
                    c[9]=0xff;c[10]=0xff;c[11]=writes;yield c
    for mask in range(256):
        for enable,narrow in ((0,0),(1,0),(1,1)):
            for kind in (9,10):
                c=default_case(3);c[1:3]=enable,narrow;c[kind]=mask;yield c
    for bit in range(32):
        for pattern in (1<<bit,MASK^(1<<bit)):
            for enable,narrow in ((0,0),(1,0),(1,1)):
                c=default_case(3);c[1:3]=enable,narrow;c[7:9]=pattern,pattern^MASK;yield c

def stream(chip, output):
    data=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
    oracle=Oracle(chip,data[chip]);digest=hashlib.sha256();count=0;coverage=[0]*len(oracle.starts)
    for case in cases(chip):
        result,trace=oracle.run(case)
        require(len(trace)%8==0,'Invalid trace shape')
        words=case+[result,len(trace)//8]+trace
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
