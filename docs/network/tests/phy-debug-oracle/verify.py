#!/usr/bin/env python3
"""Execute pinned linked debug helpers with ordered memory/callback boundaries."""
import hashlib,json,re,struct,sys
from pathlib import Path
MASK=0xffffffff
SUPPORTED = {'jal', 'movi.n', 'bnez', 'callx8', 'beqz.n', 'l32i', 'srai', 'j', 'l32i.n', 'lui', 'beqz', 'srli', 'ret', 'mov.n', 'sb', 'lw', 'retw.n', 'sub', 'sw', 'l32r', 'addi', 'quos', 's8i', 'movi', 'slli', 'mv', 'call8', 'div', 'entry', 'li', 'mul', 'blt', 'jalr', 'andi', 'extui'}
CONDITIONAL = ('beqz','beqz.n','bnez','blt')

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
                require(start <= target < start+size, 'Unknown tail target')
                pending.append(target)
                continue
            if op in CONDITIONAL:
                pending.append(int(args[-1], 16))
            pending.append(next_pc)
        require(reached == {a for a in program if start <= a < start+size}, 'Unreachable fixture instruction')
    require(len(starts) == 3 and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts


class Oracle:
    def __init__(self,chip,evidence):
        require(chip in ('esp32c3','esp32s3'),'Unknown chip')
        self.chip,self.e=chip,evidence
        require([f['name'] for f in evidence['functions']]==['get_iq_value','get_bias_ref_code','phy_get_vdd33'],'Unexpected function names')
        self.program,self.starts=decode(evidence)
        self.table_var=int(evidence['symbols']['g_phyFuns']['address'],0)
        require(all(int(v,0)==self.table_var for v in evidence['literals'].values()),'Unexpected literal value')

    def run(self,case):
        require(len(case)==16 and all(0<=v<=MASK for v in case),'Invalid case words')
        operation=case[0]
        require(operation<3 and case[5]<4096 and case[6]<2 and case[7]<2 and case[9:]==[0]*7,'Invalid case domain')
        s3=self.chip=='esp32s3'
        mask,sample,enter,mode,exit=((0x198,0x12c,0x1b0,0x1a8,0x1b4) if s3 else (0x1bc,0x150,0x1d4,0x1cc,0x1d8))
        arities={mask:6,sample:1,enter:0,mode:3,exit:0}
        trace=[];stack={};generation=0;call_count=0;samples=0
        destination=0x200003
        def event(kind,*args):
            require(len(args)<=7,'Oversized event')
            trace.extend((kind,*(v&MASK for v in args),*([0]*(7-len(args)))))
        def begin_bias():
            nonlocal generation
            event(9)
            if case[7]:generation+=1
        def read(address,width):
            if address==self.table_var and width==4:
                require(operation!=0,'Unexpected IQ table read')
                event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=address<0x70020000 and width==4:
                active,offset=divmod(address-0x70000000,0x1000)
                require(active<=generation and offset in arities,'Unknown table slot')
                event(5,offset,active);return 0x71000000+active*0x1000+offset
            if address in stack and width==4:return stack[address]
            raise ValueError(f'Unmapped read {address:x}/{width}')
        def write(address,width,value):
            if operation==0 and destination<=address<destination+2:
                require(width==1,'Unexpected IQ store width')
                event(1,destination,address-destination,value&255)
            else:
                require(width==4 and address%4==0 and 0x100000<=address<0x100100,'Non-stack store')
                stack[address]=value&MASK
        def opaque(target,regs):
            nonlocal generation,call_count,samples
            require(0x71000000<=target<0x71020000,'Unknown helper')
            active,offset=divmod(target-0x71000000,0x1000)
            require(active<=generation and offset in arities,'Unknown callback')
            args=[regs['a'+str(i+(10 if s3 else 0))] for i in range(arities[offset])]
            event(6,target,*args)
            result=case[8]^0xdeadbeef
            if offset==sample:
                result=case[3] if operation==1 or (case[6] and samples==0) else case[4]
                samples+=1
            if case[5]&(1<<call_count):generation+=1
            call_count+=1
            require(call_count<=12,'Callback budget exhausted')
            return result
        def new_registers():
            regs = {f'a{i}': (case[8]+i*0x12345)&MASK for i in range(16)}
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
                elif op in ('slli','srai','srli'):
                    value = regs[args[1]]
                    shift = int(args[2],0)
                    regs[args[0]] = ((value << shift) if op=='slli' else ((value >> shift) if op=='srli' else (signed(value) >> shift))) & MASK
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
                        require(operation==2 and target==self.starts[1] and depth==0,'Unexpected direct call')
                        begin_bias()
                        if case[6]==0:
                            clobber(regs,case[3]);pc=next_pc;continue
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

        registers=new_registers()
        if operation==0:
            registers.update({'a2':destination,'a3':case[1],'a4':case[2]} if s3 else {'a0':destination,'a1':case[1],'a2':case[2]})
        result=execute(self.starts[operation],registers)
        require(call_count==(0 if operation==0 else (5 if operation==1 else 7+5*case[6])),'Unexpected callback count')
        return (0 if operation==0 else result),trace

def default_case(operation):
    return [operation,0,0,1024,900,0,1,0,0x13579bdf,0,0,0,0,0,0,0]

def cases(chip):
    for packed in range(65536):
        for selector in (0,1):
            c=default_case(0);c[1:3]=packed,selector;yield c
    for packed in range(4096):
        for selector in (2,127,255,256,257,0x80000000,0xffffff00,MASK):
            c=default_case(0);c[1:3]=packed,selector;yield c
    lows=(0,1,31,32,63,0x3ff,0x400,0x7ff,0x800,0xfff)
    for selector in range(256):
        for packed in lows:
            c=default_case(0);c[1:3]=packed,selector;yield c
    for bit in range(12,32):
        for packed in lows:
            for selector in (0,1,256,257):
                for pattern in (1<<bit,MASK^((1<<bit)-1)):
                    c=default_case(0);c[1:3]=pattern|packed,selector;yield c
    edges=(0,1,2,31,32,255,256,1023,1024,2047,4095,32767,65535,65536,0x800000,0x7fffffff,0x80000000,0xfffffffe,MASK)
    for value in range(65536):
        c=default_case(1);c[3]=value;c[5]=value&31;yield c
    for value in edges:
        for mutation in range(32):
            c=default_case(1);c[3]=value;c[5]=mutation;yield c
    for value in range(65536):
        c=default_case(2);c[4]=value;c[3]=edges[value%len(edges)];c[5]=value&4095;c[6]=value&1;c[7]=(value>>1)&1;yield c
    for value in range(65536):
        c=default_case(2);c[3]=value;c[4]=edges[value%len(edges)];c[5]=value&4095;c[6]=value&1;yield c
    for bias in edges:
        for sample in edges:
            for composed in (0,1):
                c=default_case(2);c[3:5]=bias,sample;c[5]=4095;c[6]=composed;c[7]=1;yield c
    for mutation in range(4096):
        for bias in (0,1024):
            c=default_case(2);c[3]=bias;c[4]=0x12345678;c[5]=mutation;yield c

def stream(chip,output):
    data=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
    oracle=Oracle(chip,data[chip]);digest=hashlib.sha256();count=0;coverage=[0]*3
    for case in cases(chip):
        result,trace=oracle.run(case)
        require(len(trace)%8==0,'Invalid trace shape')
        words=case+[result,len(trace)//8]+trace
        packed=struct.pack('<'+'I'*len(words),*words)
        output.write(packed);digest.update(packed);count+=1;coverage[case[0]]+=1
    require(all(coverage),'Uncovered function')
    return {'cases':count,'operations':coverage,'case_stream_sha256':digest.hexdigest(),'fixture_sha256':hashlib.sha256(json.dumps(data[chip],sort_keys=True).encode()).hexdigest()}

def main():
    require(len(sys.argv)==3,'Usage: verify.py esp32c3|esp32s3 output.bin')
    chip=sys.argv[1];require(chip in ('esp32c3','esp32s3'),'Unknown chip')
    with Path(sys.argv[2]).open('wb') as output:result=stream(chip,output)
    expected=json.loads(Path(__file__).with_name('expected-results.json').read_text())[chip]
    require(result==expected,'Oracle results differ from reviewed fixture')
    print(json.dumps({chip:result}))
if __name__=='__main__':main()
