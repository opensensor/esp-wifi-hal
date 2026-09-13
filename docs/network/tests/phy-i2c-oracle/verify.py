#!/usr/bin/env python3
"""Interpret the original four flash I2C helper bodies and opaque call events."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

MASK=0xffffffff
CONDITIONAL=('beqz','beqz.n','bnez','bnez.n','bge','bltu','bgeu')


def require(ok,message):
    if not ok:raise ValueError(message)


def signed(value,width=32):
    value&=(1<<width)-1
    return value-(1<<width) if value>>(width-1) else value


def decode(evidence):
    program,starts={},[]
    for function in evidence['functions']:
        start,size=int(function['address'],0),function['size_bytes'];body=bytes.fromhex(function['code_hex'])
        require(len(body)==size,'Code size differs')
        require(hashlib.sha256(body).hexdigest()==function['body_sha256'],'Code hash differs')
        starts.append(start);covered=set()
        for line in function['instructions']:
            m=re.fullmatch(r'([0-9a-f]+): ([0-9a-f]+) (\S+)(?: (.*))?',line)
            require(m is not None,'Malformed instruction')
            address,raw,op,args=m.groups();address,width=int(address,16),len(raw)//2
            require(width in (2,3,4) and start<=address and address+width<=start+size,'Instruction out of range')
            offsets=set(range(address-start,address-start+width))
            require(not covered.intersection(offsets) and address not in program,'Overlapping instruction')
            covered.update(offsets)
            require(int(raw,16).to_bytes(width,'little')==body[address-start:address-start+width],'Instruction bytes differ')
            program[address]=(address+width,op,[a.strip() for a in (args or '').split(',') if a.strip()])
        require(all(body[i]==0 for i in set(range(size))-covered),'Unrecorded nonzero code')
        pending,reached=[start],set()
        while pending:
            address=pending.pop()
            if address in reached:continue
            require(start<=address<start+size and address in program,'Unknown branch target')
            reached.add(address);next_pc,op,args=program[address]
            if op in ('ret','retw.n'):continue
            if op=='jr':
                require(function['name'] in ('bias_reg_set','phy_i2c_init2'),'Unknown indirect tail call')
                continue
            if op=='j':pending.append(int(args[0],16));continue
            if op in CONDITIONAL:pending.append(int(args[-1],16))
            pending.append(next_pc)
        require(reached=={a for a in program if start<=a<start+size},'Unreachable fixture instruction')
    require(len(starts)==len(set(starts))==4,'Unexpected function count')
    return program,starts


class Oracle:
    def __init__(self,chip,evidence):
        require(chip in ('esp32c3','esp32s3'),'Unknown chip')
        self.chip,self.e=chip,evidence;self.program,self.starts=decode(evidence)
        self.param=int(evidence['symbols']['phy_param']['address'],0)
        self.param_size=evidence['symbols']['phy_param']['size_bytes']
        require(self.param_size==(740 if chip=='esp32s3' else 848),'Unexpected parameter size')
        self.table_var=int(evidence['symbols']['g_phyFuns']['address'],0)
        self.bias,self.part=(None,None) if chip=='esp32s3' else tuple(int(evidence['symbols'][n]['address'],0)
                      for n in ('bias_dreg_i2c_set','bias_dreg_i2c_set.part.0'))
        self.slots=[0x188,0x190,0x198] if chip=='esp32s3' else [0x1ac,0x1b4,0x1bc]

    def run(self,case):
        require(len(case)==24 and all(0<=x<=MASK for x in case),'Invalid case words')
        op,arg,seed,cache,revision,gate=case[:6]
        require(op in range(4) and case[23]==0,'Invalid case')
        table_mask=case[18]|(case[19]<<32);param_mask=case[20]|(case[21]<<32)
        s3=self.chip=='esp32s3';gate_offset=0x2a6 if s3 else 0x323
        mem=bytearray(((offset*37)^seed)&255 for offset in range(self.param_size))
        for offset,value in [(0x9f,cache),(0x20d,revision),(gate_offset,gate),*zip(range(0x167,0x16f),case[6:14])]:
            mem[offset]=value&255
        generation,callback_count,read_count=0,0,0
        trace,stack=[],{}

        def event(kind,*args):
            require(len(args)<=8,'Oversized event')
            trace.extend((kind,*(a&MASK for a in args),*([0]*(8-len(args)))))

        def read(address,width):
            if self.param<=address and address+width<=self.param+self.param_size:
                offset=address-self.param
                require(width==1 and offset in (0x9f,0x20d,gate_offset,*range(0x167,0x16f)),
                        'Unexpected parameter read')
                value=mem[offset];event(1,width,offset,value);return value
            if address==self.table_var and width==4:
                event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=address<0x70040000 and width==4:
                active,offset=divmod(address-0x70000000,0x1000)
                require(active<=generation and offset in self.slots,'Unknown callback slot')
                event(5,offset,active);return 0x71000000+active*0x1000+offset
            if 0x100000<=address<0x101100:
                require(all(address+i in stack for i in range(width)),'Uninitialized stack read')
                return int.from_bytes(bytes(stack[address+i] for i in range(width)),'little')
            raise ValueError(f'Unmapped read {address:x}/{width}')

        def write(address,width,value):
            value&=(1<<(width*8))-1
            if self.param<=address and address+width<=self.param+self.param_size:
                offset=address-self.param
                require((width==1 and offset in (0x9f,0xa0,0x31d,0x31e,0x2a1,*range(0xbd,0xd3))) or
                        (not s3 and ((width==2 and offset==0xbe) or (width==4 and offset in (0xc0,0xc4,0xc8,0xcc)))),
                        'Unexpected parameter write')
                mem[offset:offset+width]=value.to_bytes(width,'little');event(2,width,offset,value)
            else:
                require(width==4 and address%4==0 and 0x100000<=address and address+width<=0x101100,'Non-stack store')
                for i,b in enumerate(value.to_bytes(width,'little')):stack[address+i]=b

        def mutate():
            nonlocal generation,callback_count
            require(callback_count<64,'Callback budget exhausted')
            if table_mask&(1<<callback_count):generation+=1
            if param_mask&(1<<callback_count):
                for i in range(len(mem)):mem[i]^=case[22]&255
            callback_count+=1

        def opaque(target,regs):
            nonlocal read_count
            args=[regs[f'a{i+(10 if s3 else 0)}']&MASK for i in range(6)]
            if target==self.bias:
                require(args[0]==0,'Unknown direct bias argument');event(9,args[0]);mutate();return 0xdeadbeef
            if target==self.part:event(10);mutate();return 0xdeadbeef
            require(0x71000000<=target<0x71040000,'Unknown callback target')
            active,slot=divmod(target-0x71000000,0x1000)
            require(active<=generation and slot in self.slots,'Unknown callback slot')
            ordinal=self.slots.index(slot);arity=(3,4,6)[ordinal]
            event(6,slot,active,*args[:arity]);mutate()
            if ordinal==0:
                require(read_count<4,'Read callback budget exhausted')
                result=case[14+read_count];read_count+=1;return result
            return 0xdeadbeef

        regs={f'a{i}':0 for i in range(16)}
        regs.update({f's{i}':0 for i in range(12)});regs.update({f't{i}':0 for i in range(7)})
        regs.update(sp=0x101000,ra=0);regs['a1']=0x101000;regs['a2' if s3 else 'a0']=arg

        def clobber(value):
            names=[f'a{i}' for i in range(8,16)] if s3 else [f'a{i}' for i in range(8)]+[f't{i}' for i in range(7)]
            for n in names:regs[n]=0xdeadbeef
            regs['a10' if s3 else 'a0']=value&MASK

        pc=self.starts[op]
        for step in range(1500):
            require(pc in self.program,'Unknown branch target')
            next_pc,ins,args=self.program[pc]
            if ins=='entry':
                require(s3 and step==0 and args==['a1','32'],'Unexpected entry');regs['a1']-=32
            elif ins in ('mv','mov.n'):regs[args[0]]=regs[args[1]]
            elif ins in ('li','movi','movi.n'):regs[args[0]]=int(args[1],0)&MASK
            elif ins=='lui':regs[args[0]]=(int(args[1],0)<<12)&MASK
            elif ins in ('addi','addi.n','addmi'):regs[args[0]]=(regs[args[1]]+int(args[2],0))&MASK
            elif ins=='auipc':regs[args[0]]=(pc+(int(args[1],0)<<12))&MASK
            elif ins=='andi':regs[args[0]]=regs[args[1]]&(int(args[2],0)&MASK)
            elif ins=='zext.b':regs[args[0]]=regs[args[1]]&255
            elif ins in ('slli','srli','srai'):
                value,amount=regs[args[1]],int(args[2],0)
                regs[args[0]]=((value<<amount) if ins=='slli' else
                               ((signed(value) if ins=='srai' else value)>>amount))&MASK
            elif ins=='extui':regs[args[0]]=(regs[args[1]]>>int(args[2]))&((1<<int(args[3]))-1)
            elif ins in ('movnez','moveqz'):
                if (regs[args[2]]!=0)==(ins=='movnez'):regs[args[0]]=regs[args[1]]
            elif ins=='maxu':regs[args[0]]=max(regs[args[1]],regs[args[2]])
            elif ins=='or':regs[args[0]]=regs[args[1]]|regs[args[2]]
            elif ins=='l32r':
                literal=hex(int(args[1],16));require(literal in self.e['literals'],'Unrecorded literal')
                regs[args[0]]=int(self.e['literals'][literal],0)
            elif ins in ('lw','lbu','sw','sb','sh'):
                m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[1]);require(m is not None,'Bad memory operand')
                address=(regs[m[2]]+int(m[1]))&MASK;width={'lw':4,'lbu':1,'sw':4,'sb':1,'sh':2}[ins]
                if ins in ('sw','sb','sh'):write(address,width,regs[args[0]])
                else:regs[args[0]]=read(address,width)
            elif ins in ('l32i','l32i.n','l8ui','s8i'):
                address=(regs[args[1]]+int(args[2],0))&MASK;width=1 if ins in ('l8ui','s8i') else 4
                if ins=='s8i':write(address,width,regs[args[0]])
                else:regs[args[0]]=read(address,width)
            elif ins in CONDITIONAL:
                left=regs[args[0]]
                if ins in ('beqz','beqz.n'):taken=left==0
                elif ins in ('bnez','bnez.n'):taken=left!=0
                else:
                    right=regs[args[1]]
                    taken=signed(left)>=signed(right) if ins=='bge' else left<right if ins=='bltu' else left>=right
                if taken:next_pc=int(args[-1],16)
            elif ins=='j':next_pc=int(args[0],16)
            elif ins in ('jalr','jr','callx8'):
                if '(' in args[0]:
                    m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[0]);require(m is not None,'Bad call operand')
                    target=(regs[m[2]]+int(m[1]))&MASK
                else:target=regs[args[0]]
                value=opaque(target,regs)
                if ins=='jr':return 0,trace
                clobber(value)
            elif ins in ('ret','retw.n'):
                require((ins=='retw.n')==s3,'Wrong return ABI');return 0,trace
            else:raise ValueError(f'Unsupported instruction {ins}')
            pc=next_pc
        raise ValueError('Instruction budget exhausted')


def default_case(operation):
    return [operation,1,0xa5,0,1,0, 11,22,33,44,55,66,77,88,
            0x80000080,0x12345678,0x87654321,0xffffffff,0,0,0,0,0x5a,0]


def cases(chip):
    # Exhaust each revision/cache/gate byte and noncanonical argument classes.
    for value in range(256):
        for operation in (0,1,2):
            for argument in (0,1,2,255,256,257,0x80000000,MASK):
                for hooks in (0,1,2,3):
                    c=default_case(operation);c[1]=argument;c[3:6]=[value]*3
                    c[18:22]=[MASK if hooks&1 else 0]*2+[MASK if hooks&2 else 0]*2
                    yield c
    if chip=='esp32c3':
        # Every signed16 subtraction outcome, including raw nonzero upper bits.
        for raw in range(65536):
            c=default_case(1);c[14]=0xa5a50000|raw
            yield c
    # Each raw helper-return byte and upper-bit patterns for the full PLL read sequence.
    for low in range(256):
        for high in (0,0x80000000,0xffff0000):
            for hooks in (0,1,2,3):
                c=default_case(2);c[14:18]=[high|low,high|(low^85),high|(low^170),high|(low^255)]
                c[18:22]=[MASK if hooks&1 else 0]*2+[MASK if hooks&2 else 0]*2
                yield c
    # Exhaust the entire pair feeding derived init values. The third cached C3
    # byte traverses every low-byte addition/wrap value as part of this domain.
    for first in range(256):
        for second in range(256):
            c=default_case(3);c[11:14]=[(first+second)&255,first,second]
            yield c
    # Walk mutation position through all 33 calls, including high mask word bit0.
    for position in range(33):
        mask=1<<position
        for value in range(256):
            c=default_case(3);c[6:14]=[value]*8
            c[18:22]=[mask&MASK,mask>>32,mask&MASK,mask>>32]
            yield c
    for operation in (1,2,3):
        for pattern in (0,MASK,0xaaaaaaaa,0x55555555):
            for value in (0,1,5,9,10,15,49,50,51,57,58,60,251,252,255):
                c=default_case(operation);c[6:14]=[value]*8
                c[18:22]=[pattern]*4;c[3:6]=[value]*3
                yield c


def main():
    chip,destination=sys.argv[1:]
    fixture=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
    oracle=Oracle(chip,fixture['chips'][chip]);digest,count=hashlib.sha256(),0
    with open(destination,'wb') as stream:
        for case in cases(chip):
            result,trace=oracle.run(case);words=(*case,result,len(trace)//9,*trace)
            encoded=struct.pack('<'+'I'*len(words),*words);stream.write(encoded);digest.update(encoded);count+=1
    report={'chip':chip,'cases':count,'oracle_sha256':digest.hexdigest()}
    expected=json.loads(Path(__file__).with_name('expected-results.json').read_text())[chip]
    require(report==expected,'Original instruction trace digest changed');print(json.dumps(report))


if __name__=='__main__':main()
