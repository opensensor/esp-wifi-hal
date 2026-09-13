#!/usr/bin/env python3
"""Bounded interpreter of original C3/S3 PBUS instructions, not Rust source."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

MASK = 0xffffffff
CONDITIONAL = ('beq', 'beqi', 'bne', 'beqz', 'beqz.n', 'bnez', 'bnez.n', 'bltu')
MMIO = (0x600060c8, 0x600060cc, 0x600060e0, 0x600060e4, 0x600060e8, 0x600060ec,
        0x600060f0, 0x600060f4, 0x60006104, 0x6000610c, 0x6002600c, 0x6001c02c)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def decode(evidence):
    program, starts, regions, jump_targets = {}, [], {}, None
    for region in evidence['regions']:
        data = bytes.fromhex(region['data_hex'])
        require(len(data) == region['size_bytes'], 'Region size differs')
        require(hashlib.sha256(data).hexdigest() == region['sha256'], 'Region hash differs')
        address = int(region['address'], 0)
        for offset, byte in enumerate(data):
            require(address+offset not in regions, 'Overlapping constant region')
            regions[address+offset] = byte
        if region['purpose'] == 'jump_table':
            require(jump_targets is None and len(data) == 40, 'Unexpected jump table')
            jump_targets = [int.from_bytes(data[i:i+4], 'little') for i in range(0,40,4)]
        else:
            require(region['purpose'] == 'constant_words', 'Unknown constant region')
    require(jump_targets is not None and len(set(jump_targets)) == 10, 'Missing jump table')
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
            address, width = int(address,16), len(raw)//2
            require(width in (2,3,4) and start <= address and address+width <= start+size,
                    'Instruction out of range')
            offsets = set(range(address-start,address-start+width))
            require(not covered.intersection(offsets) and address not in program, 'Overlapping instruction')
            covered.update(offsets)
            require(int(raw,16).to_bytes(width,'little') == body[address-start:address-start+width],
                    'Instruction bytes differ')
            program[address] = (address+width,op,[a.strip() for a in (args or '').split(',') if a.strip()])
        require(all(body[i] == 0 for i in set(range(size))-covered), 'Unrecorded nonzero code')
        pending, reached = [start], set()
        while pending:
            address = pending.pop()
            if address in reached:
                continue
            require(start <= address < start+size and address in program, 'Unknown branch target')
            reached.add(address)
            next_pc,op,args = program[address]
            if op in ('ret','retw.n'):
                continue
            if op in ('jr','jx'):
                if function['name'] == 'set_pbus_mem':
                    pending.extend(jump_targets)
                else:
                    require(op == 'jr' and args == ['t1'] and function['name'] in
                            ('txcal_debuge_mode','txcal_work_mode'), 'Unknown indirect tail call')
                continue
            if op == 'j':
                target = int(args[0],16)
                if start <= target < start+size:
                    pending.append(target)
                else:
                    require(function['name'] == 'set_pbus_mem' and target in starts,
                            'Unknown direct tail call')
                continue
            if op in CONDITIONAL or op == 'loop':
                pending.append(int(args[-1],16))
            pending.append(next_pc)
        require(reached == {a for a in program if start <= a < start+size}, 'Unreachable fixture instruction')
    require(len(starts) in (4,5) and len(set(starts)) == len(starts), 'Unexpected function count')
    return program,starts,regions,set(jump_targets)


class Oracle:
    def __init__(self, chip, evidence):
        require(chip in ('esp32c3','esp32s3'), 'Unknown chip')
        self.chip,self.e = chip,evidence
        self.program,self.starts,self.constants,self.jump_targets = decode(evidence)
        s3 = chip == 'esp32s3'
        require(len(self.starts) == (4 if s3 else 5), 'Unexpected chip function count')
        self.operations = ([None]+self.starts) if s3 else self.starts
        self.param = int(evidence['symbols']['phy_param']['address'],0)
        self.param_size = evidence['symbols']['phy_param']['size_bytes']
        require(self.param_size == (740 if s3 else 848), 'Unexpected parameter size')
        self.table_var = int(evidence['symbols']['g_phyFuns']['address'],0)
        self.memcpy = int(evidence['symbols']['memcpy']['address'],0)
        self.delay = int(evidence['symbols']['ets_delay_us']['address'],0)
        self.stop_tone = int(evidence['symbols']['stop_tx_tone']['address'],0)
        self.slots = ([0x44,0x1b0,0x1c8,0xdc,0x1cc,0xe8,0x1c0,0x1b4] if s3 else
                      [0x50,0x1d4,0x1ec,0xec,0x1f0,0xfc,0x1e4,0x1d8])

    def run(self, case):
        require(len(case) == 24 and all(0 <= x <= MASK for x in case), 'Invalid case words')
        operation,force,index,seed,index_result,table_mask,param_mask,param_xor,read_xor,delay1,delay2,reserved = case[:12]
        require(operation in range(5) and self.operations[operation] is not None and reserved == 0,
                'Invalid case')
        require(table_mask < 64 and param_mask < 64, 'Unknown callback mutation mask')
        s3 = self.chip == 'esp32s3'
        index_offset,save_offset = (0x20c,0x2ac) if s3 else (0xa3,0x328)
        index &= 255
        mem = bytearray(((offset*37)^seed)&255 for offset in range(self.param_size))
        mem[index_offset] = index
        mmio = dict(zip(MMIO[:8] if s3 else MMIO,case[12:]))
        generation,read_count,callback_count = 0,0,0
        trace,stack = [],{}

        def event(kind,*args):
            require(len(args) <= 8,'Oversized event')
            trace.extend((kind,*(a&MASK for a in args),*([0]*(8-len(args)))))

        def read(address,width):
            nonlocal read_count
            if self.param <= address and address+width <= self.param+self.param_size:
                offset = address-self.param
                require((width==1 and offset in (index_offset,14+index)) or
                        (width==2 and offset==32+2*index), 'Unexpected parameter read')
                value = int.from_bytes(mem[offset:offset+width],'little')
                event(1,width,offset,value)
                return value
            if address in mmio:
                require(width==4,'Unexpected MMIO width')
                shift = read_count % 32
                perturbation = ((read_xor<<shift)|(read_xor>>((32-shift)%32)))&MASK
                value = mmio[address]^perturbation
                read_count += 1
                event(7,address,value)
                return value
            if address == self.table_var and width == 4:
                event(4,generation)
                return 0x70000000+generation*0x1000
            if 0x70000000 <= address < 0x70010000 and width == 4:
                active,offset = divmod(address-0x70000000,0x1000)
                require(active<=generation and offset in self.slots,'Unknown callback slot')
                event(5,offset,active)
                return 0x71000000+active*0x1000+offset
            if address in self.constants:
                require(all(address+i in self.constants for i in range(width)), 'Constant range overflow')
                return int.from_bytes(bytes(self.constants[address+i] for i in range(width)),'little')
            if 0x100000 <= address < 0x101100:
                require(all(address+i in stack for i in range(width)), 'Uninitialized stack read')
                return int.from_bytes(bytes(stack[address+i] for i in range(width)),'little')
            raise ValueError(f'Unmapped read {address:x}/{width}')

        def write(address,width,value):
            value &= (1<<(width*8))-1
            if self.param <= address and address+width <= self.param+self.param_size:
                offset = address-self.param
                require(width==4 and offset in range(save_offset,save_offset+24,4), 'Unexpected parameter write')
                mem[offset:offset+width] = value.to_bytes(width,'little')
                event(2,width,offset,value)
            elif address in mmio:
                require(width==4,'Unexpected MMIO width')
                mmio[address] = value
                event(8,address,value)
            else:
                require(width==4 and address%4==0 and 0x100000<=address and address+width<=0x101100,
                        'Non-stack store')
                for i,b in enumerate(value.to_bytes(width,'little')):
                    stack[address+i] = b

        def mutate_callback():
            nonlocal generation,callback_count
            require(callback_count < 6, 'Unexpected callback count')
            if table_mask & (1<<callback_count): generation += 1
            if param_mask & (1<<callback_count):
                for i in range(len(mem)): mem[i] ^= param_xor&255
            callback_count += 1

        def opaque(target,regs):
            arguments = [regs[f'a{i+(10 if s3 else 0)}']&MASK for i in range(6)]
            if target == self.memcpy:
                dest,source,count = arguments[:3]
                require(count in (12,16,32) and count%4==0, 'Unknown memcpy length')
                require(source in self.constants and 0x100000<=dest and dest+count<=0x101100,
                        'Unknown memcpy boundary')
                for i in range(0,count,4): write(dest+i,4,read(source+i,4))
                return dest
            if target == self.delay:
                require(not s3 and arguments[0] in (1,2), 'Unknown delay')
                event(9,arguments[0])
                mmio[0x6001c02c] ^= delay1 if arguments[0]==1 else delay2
                return 0xabcdef01
            if target == self.stop_tone:
                require(arguments[0]==1,'Wrong stop tone argument')
                event(10,arguments[0]);mutate_callback()
                return 0xabcdef01
            require(0x71000000<=target<0x71010000,'Unknown callback target')
            active,slot = divmod(target-0x71000000,0x1000)
            require(active<=generation and slot in self.slots,'Unknown callback slot')
            ordinal = self.slots.index(slot)
            arity = [1,0,2,1,1,0,1,0][ordinal]
            args = arguments[:arity]
            if ordinal==4: args[0] = (args[0]-self.param)&MASK
            event(6,slot,active,*args)
            mutate_callback()
            return index_result if ordinal==3 else 0xdeadbeef

        def new_registers():
            regs = {f'a{i}':0 for i in range(16)}
            regs.update({f's{i}':0 for i in range(12)})
            regs.update({f't{i}':0 for i in range(7)})
            regs.update(sp=0x101000,ra=0)
            regs['a1'] = 0x101000
            return regs

        def clobber(regs,value):
            names = [f'a{i}' for i in range(8,16)] if s3 else [f'a{i}' for i in range(8)]+[f't{i}' for i in range(7)]
            for name in names: regs[name] = 0xdeadbeef
            regs['a10' if s3 else 'a0'] = value&MASK

        def execute(pc,regs,depth=0):
            require(depth<4,'Call nesting budget exhausted')
            loop_begin,loop_end,loop_remaining,shift = None,None,0,0
            for step in range(5000):
                require(pc in self.program,'Unknown branch target')
                next_pc,op,args = self.program[pc]
                if op=='entry':
                    require(s3 and step==0 and args[0]=='a1' and int(args[1]) in (32,224),'Unexpected entry')
                    regs['a1'] -= int(args[1])
                elif op in ('mv','mov.n'): regs[args[0]] = regs[args[1]]
                elif op in ('li','movi','movi.n'): regs[args[0]] = int(args[1],0)&MASK
                elif op=='lui': regs[args[0]] = (int(args[1],0)<<12)&MASK
                elif op in ('addi','addi.n','addmi'):
                    regs[args[0]] = (regs[args[1]]+int(args[2],0))&MASK
                elif op=='auipc': regs[args[0]] = (pc+(int(args[1],0)<<12))&MASK
                elif op in ('add','add.n','addx2','addx4','or','and','xor'):
                    left,right = regs[args[1]],regs[args[2]]
                    if op=='addx2': value=2*left+right
                    elif op=='addx4': value=4*left+right
                    elif op=='or': value=left|right
                    elif op=='and': value=left&right
                    elif op=='xor': value=left^right
                    else: value=left+right
                    regs[args[0]]=value&MASK
                elif op in ('andi','ori'):
                    left,right=regs[args[1]],int(args[2],0)&MASK
                    regs[args[0]]=left&right if op=='andi' else left|right
                elif op=='not': regs[args[0]]=(~regs[args[1]])&MASK
                elif op in ('slli','srli'):
                    value,amount=regs[args[1]],int(args[2],0)
                    regs[args[0]]=((value<<amount) if op=='slli' else (value>>amount))&MASK
                elif op=='ssl':
                    require(s3,'Wrong variable shift ABI');shift=regs[args[0]]&31
                elif op=='sll':
                    amount=shift if s3 else regs[args[2]]&31
                    regs[args[0]]=(regs[args[1]]<<amount)&MASK
                elif op=='extui':
                    regs[args[0]]=(regs[args[1]]>>int(args[2]))&((1<<int(args[3]))-1)
                elif op=='l32r':
                    literal=hex(int(args[1],16));require(literal in self.e['literals'],'Unrecorded literal')
                    regs[args[0]]=int(self.e['literals'][literal],0)
                elif op in ('lw','lbu','lhu','sw'):
                    match=re.fullmatch(r'(-?\d+)\((\w+)\)',args[1]);require(match is not None,'Bad memory operand')
                    address=(regs[match[2]]+int(match[1]))&MASK
                    width={'lw':4,'lbu':1,'lhu':2,'sw':4}[op]
                    if op=='sw': write(address,width,regs[args[0]])
                    else: regs[args[0]]=read(address,width)
                elif op in ('l32i','l32i.n','l8ui','l16ui','s32i','s32i.n'):
                    address=(regs[args[1]]+int(args[2],0))&MASK
                    width=1 if op=='l8ui' else 2 if op=='l16ui' else 4
                    if op.startswith('s32'): write(address,width,regs[args[0]])
                    else: regs[args[0]]=read(address,width)
                elif op in CONDITIONAL:
                    left=regs[args[0]]
                    if op in ('beqz','beqz.n'): taken=left==0
                    elif op in ('bnez','bnez.n'): taken=left!=0
                    else:
                        right=int(args[1],0) if op=='beqi' else regs[args[1]]
                        if op in ('beq','beqi'): taken=left==right
                        elif op=='bne': taken=left!=right
                        else: taken=left<right
                    if taken: next_pc=int(args[-1],16)
                elif op=='loop':
                    require(s3 and loop_remaining==0,'Nested or unsupported loop')
                    loop_begin,loop_end=next_pc,int(args[1],16)
                    loop_remaining=regs[args[0]]
                    require(0<loop_remaining<=32,'Unsupported loop domain')
                elif op=='j': next_pc=int(args[0],16)
                elif op in ('jr','jx'):
                    target=regs[args[0]]
                    if target in self.jump_targets: next_pc=target
                    else:
                        require(not s3 and args==['t1'],'Unknown indirect jump')
                        return opaque(target,regs)
                elif op in ('jal','jalr','call8','callx8'):
                    if op in ('jal','call8'): target=int(args[0],16)
                    elif '(' in args[0]:
                        match=re.fullmatch(r'(-?\d+)\((\w+)\)',args[0]);require(match is not None,'Bad call operand')
                        target=(regs[match[2]]+int(match[1]))&MASK
                    else: target=regs[args[0]]
                    if target in self.starts:
                        require(target==self.operations[3],'Unexpected selected call')
                        if s3:
                            child=new_registers();child['a1']=regs['a1']
                            child.update({f'a{i+2}':regs[f'a{i+10}'] for i in range(6)})
                            result=execute(target,child,depth+1);clobber(regs,result)
                        else:
                            regs['ra']=next_pc;execute(target,regs,depth+1)
                    else:
                        result=opaque(target,regs);clobber(regs,result)
                elif op=='memw': require(s3 and not args,'Unexpected memory barrier')
                elif op in ('ret','retw.n'):
                    require((op=='retw.n')==s3,'Wrong return ABI')
                    return regs['a2' if s3 else 'a0']&MASK
                else: raise ValueError(f'Unsupported instruction {op}')
                if loop_remaining and next_pc==loop_end:
                    loop_remaining-=1
                    if loop_remaining: next_pc=loop_begin
                pc=next_pc
            raise ValueError('Instruction budget exhausted')

        registers=new_registers()
        registers['a2' if s3 else 'a0']=force
        execute(self.operations[operation],registers)
        return 0,trace


def default_case(operation):
    return [operation,0,2,0xa5,3,0,0,0x5a,0,0x80000001,0x5a5aa5a5,0,
            0xa5a55a5a,0x12345678,0x80000001,0x5a5aa5a5,0xdeadbeef,0x01234567,
            0xfedcba98,0x76543210,0x12345678,0xa5a55a5a,2,0x5aa55aa5]


def cases(chip):
    patterns=(0,MASK,0x80000001,0x5a5aa5a5)
    xors=(0,0x80000001,0x5a5aa5a5)
    if chip=='esp32c3':
        flags=(*range(256),256,257,0x10000,0x80000000,MASK,*(1<<i for i in range(9,31)))
        for argument in flags:
            for gate in (0,1,2,3,0xfffffffd,MASK):
                for perturbation in xors:
                    c=default_case(0);c[1],c[8],c[22]=argument,perturbation,gate
                    yield c
        for bit in range(32):
            for pattern in (1<<bit,MASK^(1<<bit)):
                for perturbation in xors:
                    c=default_case(0);c[20:24]=[pattern]*4;c[8]=perturbation
                    yield c
    # Exhaust every index byte. Some indices overlap the index byte itself or
    # its containing halfword; initial memory is synthesized before overriding
    # that byte, exactly as the host test does.
    for index in range(256):
        for seed in (0,0xa5,0x5a,255):
            for result in (0,1,0x123,0x7fff,0xffff,0x10000,0x80000000,MASK):
                for table_mask,param_mask in ((0,0),(63,0),(0,63),(63,63)):
                    c=default_case(1);c[2:7]=[index,seed,result,table_mask,param_mask]
                    yield c
    # Exhaust every helper-result halfword with nonzero raw upper bits. This
    # catches S3's explicit narrowing and C3's full-register wrapping offset.
    for result in range(65536):
        c=default_case(1);c[4]=0xa5a50000|result;c[5]=63
        yield c
    for mask in range(64):
        for operation in (1,2):
            c=default_case(operation);c[5],c[6]=mask,mask^63
            yield c
    # Walking bits plus fresh read perturbations exercise every selector/control
    # bit in all twelve PBUS programming stages and the final saved snapshot.
    for operation in (3,4):
        for pattern in (*patterns,*(1<<bit for bit in range(32)),*(MASK^(1<<bit) for bit in range(32))):
            for perturbation in xors:
                c=default_case(operation);c[12:]=[pattern]*12;c[8]=perturbation
                yield c


def main():
    chip,destination=sys.argv[1:]
    fixture=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
    oracle=Oracle(chip,fixture['chips'][chip])
    digest,count=hashlib.sha256(),0
    with open(destination,'wb') as stream:
        for case in cases(chip):
            result,trace=oracle.run(case)
            words=(*case,result,len(trace)//9,*trace)
            encoded=struct.pack('<'+'I'*len(words),*words)
            stream.write(encoded);digest.update(encoded);count+=1
    report={'chip':chip,'cases':count,'oracle_sha256':digest.hexdigest()}
    expected=json.loads(Path(__file__).with_name('expected-results.json').read_text())[chip]
    require(report==expected,'Original instruction trace digest changed')
    print(json.dumps(report))


if __name__=='__main__':
    main()
