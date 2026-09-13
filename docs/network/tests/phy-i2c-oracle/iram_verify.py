#!/usr/bin/env python3
"""Bounded original IRAM I2C instruction interpreter and synthetic corpus."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from verify import require,signed

MASK=0xffffffff
CONFIG=0x6000e048
INPUT=0x72000000
CONDITIONAL=('beq','bne','bnei','beqz','beqz.n','bnez','bnez.n','bltu','bgeu','bltui','bltz','bany')


def decode(evidence):
    program,starts={},{}
    for function in evidence['functions']:
        start,size=int(function['address'],0),function['size_bytes'];body=bytes.fromhex(function['code_hex'])
        require(len(body)==size,'Code size differs')
        require(hashlib.sha256(body).hexdigest()==function['body_sha256'],'Code hash differs')
        starts[function['name']]=start;covered=set()
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
            if op in ('ret','retw.n','jr'):continue
            if op=='j':
                target=int(args[0],16)
                if start<=target<start+size:pending.append(target)
                else:require(function['name']=='bias_dreg_i2c_set','Unknown direct tail call')
                continue
            if op in CONDITIONAL:pending.append(int(args[-1],16))
            pending.append(next_pc)
        require(reached=={a for a in program if start<=a<start+size},'Unreachable fixture instruction')
    require(len(starts) in (8,9) and len(set(starts.values()))==len(starts),'Unexpected function count')
    return program,starts


class Oracle:
    def __init__(self,chip,evidence):
        require(chip in ('esp32c3','esp32s3'),'Unknown chip')
        self.chip,self.e=chip,evidence;self.program,self.starts=decode(evidence)
        s3=chip=='esp32s3';prefix='ram_' if s3 else 'rom1_'
        names=[prefix+'get_i2c_hostid',prefix+'chip_i2c_readReg',prefix+'chip_i2c_writeReg',
               prefix+'phy_i2c_init1','phy_i2c_bbtop_wakeup','bias_dreg_i2c_set',
               'bias_dreg_i2c_set.part.0','ram_set_txcap_reg','phy_i2c_enter_critical','phy_i2c_exit_critical']
        self.operations=[self.starts.get(n) for n in names]
        require(sum(x is not None for x in self.operations)==(8 if s3 else 9),'Unexpected chip function count')
        self.param=int(evidence['symbols']['phy_param']['address'],0)
        self.param_size=evidence['symbols']['phy_param']['size_bytes']
        require(self.param_size==(740 if s3 else 848),'Unexpected parameter size')
        self.table_var=int(evidence['symbols']['g_phyFuns']['address'],0)
        self.init2=int(evidence['symbols']['phy_i2c_init2']['address'],0)
        self.memset=int(evidence['symbols']['memset']['address'],0) if s3 else None
        self.sar2=None if s3 else int(evidence['symbols']['rom_i2c_sar2_init_code']['address'],0)
        # pause, resume, read mask(block), get host(block), read original,
        # register read, register write, register mask write, init mask(block),
        # bulk, read masked register, optional S3 SAR2.
        self.slots=([0x160,0x164,0x154,0x15c,0x168,0x188,0x190,0x198,0x158,0x180,0x194,0x23c] if s3 else
                    [0x184,0x188,0x178,0x180,0x18c,0x1ac,0x1b4,0x1bc,0x17c,0x1a4,0x1b8])

    def run(self,case):
        require(len(case)==32 and all(0<=x<=MASK for x in case),'Invalid case words')
        operation=case[0];require(operation in range(10) and self.operations[operation] is not None and case[31]==0,'Invalid case')
        table_mask=case[13]|case[14]<<32;param_mask=case[15]|case[16]<<32;mmio_mask=case[21]|case[22]<<32
        s3=self.chip=='esp32s3'
        mem=bytearray(((offset*37)^case[5])&255 for offset in range(self.param_size))
        mem[0x2cd]=case[24]&255
        fallback=b''.join(v.to_bytes(4,'little') for v in case[25:28])[:9]
        mem[0x2ce:0x2d7]=fallback
        input_bytes=b''.join(v.to_bytes(4,'little') for v in case[28:31])[:9]
        host_address=((0x18003800+case[8])<<2)&MASK
        mmio={CONFIG:case[18]}
        if operation==2: mmio.setdefault(host_address,0)
        generation,callback_count,read_count,poll_count,wakeup_count=0,0,0,0,0
        trace,stack=[],{}

        def event(kind,*args):
            require(len(args)<=8,'Oversized event')
            trace.extend((kind,*(a&MASK for a in args),*([0]*(8-len(args)))))

        def read(address,width):
            nonlocal read_count,poll_count
            if address in mmio:
                require(width==4,'Unexpected MMIO width')
                shift=read_count%32;perturb=((case[19]<<shift)|(case[19]>>((32-shift)%32)))&MASK
                value=mmio[address]^perturb;read_count+=1
                if operation==2 and address==host_address:
                    value=(value&~0x02000000)|(0x02000000 if poll_count<case[23] else 0);poll_count+=1
                event(7,address,value);return value
            if self.param<=address and address+width<=self.param+self.param_size:
                offset=address-self.param
                require(width==1 and offset in (*range(0xbd,0xd1),*range(0x2cd,0x2d7)),'Unexpected parameter read')
                value=mem[offset];event(1,width,offset,value);return value
            if INPUT<=address<INPUT+9:
                require(width==1,'Unexpected input width');offset=address-INPUT;value=input_bytes[offset]
                event(3,width,offset,value);return value
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
            if address in mmio:
                require(width==4,'Unexpected MMIO width');mmio[address]=value;event(8,address,value)
            elif self.param<=address and address+width<=self.param+self.param_size:
                offset=address-self.param;require(s3 and width==1 and offset in (0xbd,0xbe),'Unexpected parameter write')
                mem[offset]=value;event(2,width,offset,value)
            else:
                require(width in (1,2,4) and address%width==0 and 0x100000<=address and address+width<=0x101100,
                        'Non-stack store')
                for i,b in enumerate(value.to_bytes(width,'little')):stack[address+i]=b

        def mutate():
            nonlocal generation,callback_count
            require(callback_count<64,'Callback budget exhausted')
            bit=1<<callback_count
            if table_mask&bit:generation+=1
            if param_mask&bit:
                for i in range(len(mem)):mem[i]^=case[17]&255
            if mmio_mask&bit:mmio[CONFIG]^=case[20]
            callback_count+=1

        def opaque(target,regs):
            nonlocal wakeup_count
            args=[regs[f'a{i+(10 if s3 else 0)}']&MASK for i in range(6)]
            if target==self.memset:
                dest,value,count=args[:3]
                require(s3 and value==0 and count==10 and 0x100000<=dest and dest+10<=0x101100,'Unknown memset boundary')
                for i in range(count):write(dest+i,1,0)
                return dest
            if target==self.sar2:
                require(args[0]==1400,'Unexpected SAR2 argument');event(13,args[0]);mutate();return 0xdeadbeef
            if target==self.init2:event(14);mutate();return 0xdeadbeef
            require(0x71000000<=target<0x71040000,'Unknown callback target')
            active,slot=divmod(target-0x71000000,0x1000)
            require(active<=generation and slot in self.slots,'Unknown callback slot')
            kind=self.slots.index(slot)
            if kind==9:
                length,flag=(read(regs['a1'],4),read(regs['a1']+4,4)) if s3 else (regs['a6'],regs['a7'])
                require(length==10 and flag==0,'Unknown bulk array domain')
                event(11,slot,active,length,flag)
                for index,address in enumerate(args):
                    require(0x100000<=address and address+10<=0x101100,'Unknown bulk array pointer')
                    data=read(address,10).to_bytes(10,'little')+b'\0\0'
                    event(12,index,*struct.unpack('<III',data))
                mutate();return 0xdeadbeef
            arity=[0,1,1,1,4,3,4,6,1,0,5,1][kind]
            event(6,slot,active,*args[:arity]);mutate()
            if kind==0:return case[6]
            if kind in (2,8):return case[7]
            if kind==3:return case[8]
            if kind==4:return case[9]
            if kind==5:
                require(operation==4 and wakeup_count<2,'Unexpected wakeup read')
                result=case[11+wakeup_count];wakeup_count+=1;return result
            if kind==10:return case[10]
            return 0xdeadbeef

        def new_registers():
            regs={f'a{i}':0 for i in range(16)};regs.update({f's{i}':0 for i in range(12)})
            regs.update({f't{i}':0 for i in range(7)});regs.update(sp=0x101000,ra=0,zero=0);regs['a1']=0x101000
            return regs

        def clobber(regs,value):
            for n in ([f'a{i}' for i in range(8,16)] if s3 else [f'a{i}' for i in range(8)]+[f't{i}' for i in range(7)]):
                regs[n]=0xdeadbeef
            regs['a10' if s3 else 'a0']=value&MASK

        def execute(pc,regs,depth=0):
            require(depth<4,'Call nesting budget exhausted')
            if pc==self.operations[8]:event(9)
            if pc==self.operations[9]:event(10)
            shift=0
            for step in range(5000):
                require(pc in self.program,'Unknown branch target');next_pc,ins,args=self.program[pc]
                if ins=='entry':
                    require(s3 and step==0 and args[0]=='a1' and int(args[1]) in (32,48,112),'Unexpected entry')
                    regs['a1']-=int(args[1])
                elif ins in ('mv','mov.n'):regs[args[0]]=regs[args[1]]
                elif ins in ('li','movi','movi.n'):regs[args[0]]=int(args[1],0)&MASK
                elif ins=='lui':regs[args[0]]=(int(args[1],0)<<12)&MASK
                elif ins in ('addi','addi.n','addmi'):regs[args[0]]=(regs[args[1]]+int(args[2],0))&MASK
                elif ins=='auipc':regs[args[0]]=(pc+(int(args[1],0)<<12))&MASK
                elif ins in ('add','add.n','and','or'):
                    a,b=regs[args[1]],regs[args[2]]
                    regs[args[0]]=((a+b) if ins in ('add','add.n') else a&b if ins=='and' else a|b)&MASK
                elif ins=='andi':regs[args[0]]=regs[args[1]]&(int(args[2],0)&MASK)
                elif ins=='zext.b':regs[args[0]]=regs[args[1]]&255
                elif ins=='snez':regs[args[0]]=int(regs[args[1]]!=0)
                elif ins=='slli':regs[args[0]]=(regs[args[1]]<<int(args[2],0))&MASK
                elif ins=='ssl':require(s3,'Wrong shift ABI');shift=regs[args[0]]&31
                elif ins=='sll':regs[args[0]]=(regs[args[1]]<<(shift if s3 else regs[args[2]]&31))&MASK
                elif ins=='extui':regs[args[0]]=(regs[args[1]]>>int(args[2]))&((1<<int(args[3]))-1)
                elif ins=='sext':regs[args[0]]=signed(regs[args[1]],int(args[2])+1)&MASK
                elif ins=='movnez':
                    if regs[args[2]]!=0:regs[args[0]]=regs[args[1]]
                elif ins=='l32r':
                    literal=hex(int(args[1],16));require(literal in self.e['literals'],'Unrecorded literal')
                    regs[args[0]]=int(self.e['literals'][literal],0)
                elif ins in ('lw','lbu','sw','sb','sh'):
                    m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[1]);require(m is not None,'Bad memory operand')
                    address=(regs[m[2]]+int(m[1]))&MASK;width={'lw':4,'lbu':1,'sw':4,'sb':1,'sh':2}[ins]
                    if ins in ('sw','sb','sh'):write(address,width,regs[args[0]])
                    else:regs[args[0]]=read(address,width)
                elif ins in ('l32i','l32i.n','l8ui','s8i','s32i.n'):
                    address=(regs[args[1]]+int(args[2],0))&MASK;width=1 if ins in ('l8ui','s8i') else 4
                    if ins in ('s8i','s32i.n'):write(address,width,regs[args[0]])
                    else:regs[args[0]]=read(address,width)
                elif ins in CONDITIONAL:
                    left=regs[args[0]]
                    if ins in ('beqz','beqz.n'):taken=left==0
                    elif ins in ('bnez','bnez.n'):taken=left!=0
                    elif ins=='bltz':taken=signed(left)<0
                    else:
                        right=int(args[1],0) if ins in ('bnei','bltui') else regs[args[1]]
                        if ins=='beq':taken=left==right
                        elif ins in ('bne','bnei'):taken=left!=right
                        elif ins=='bgeu':taken=left>=right
                        elif ins=='bany':taken=(left&right)!=0
                        else:taken=left<right
                    if taken:next_pc=int(args[-1],16)
                elif ins=='j':next_pc=int(args[0],16)
                elif ins in ('jal','jalr','jr','call8','callx8'):
                    if ins in ('jal','call8'):target=int(args[0],16)
                    elif '(' in args[0]:
                        m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[0]);require(m is not None,'Bad call operand')
                        target=(regs[m[2]]+int(m[1]))&MASK
                    else:target=regs[args[0]]
                    if target in self.starts.values():
                        require(target in (self.operations[8],self.operations[9]),'Unexpected selected call')
                        if s3:
                            child=new_registers();child['a1']=regs['a1']
                            child.update({f'a{i+2}':regs[f'a{i+10}'] for i in range(6)})
                            value=execute(target,child,depth+1);clobber(regs,value)
                        else:regs['ra']=next_pc;execute(target,regs,depth+1)
                    else:
                        value=opaque(target,regs)
                        if ins=='jr':return value
                        clobber(regs,value)
                elif ins=='memw':require(s3 and not args,'Unexpected memory barrier')
                elif ins in ('ret','retw.n'):
                    require((ins=='retw.n')==s3,'Wrong return ABI');return regs['a2' if s3 else 'a0']&MASK
                else:raise ValueError(f'Unsupported instruction {ins}')
                pc=next_pc
            raise ValueError('Instruction budget exhausted')

        regs=new_registers()
        regs.update({f'a{i+(2 if s3 else 0)}':case[i+1] for i in range(4)})
        if operation==7:regs['a2']=INPUT
        result=execute(self.operations[operation],regs)
        return (result if operation in (0,1) else 0),trace


def default_case(operation):
    return [operation,103,0,6,0xa5,0x5a,0x81234567,0xfedcba98,1,0xfedc1234,0,
            16,16,0,0,0,0,0x5a,0xa5a55a5a,0,0x80000001,0,0,2,0,
            0x44332211,0x88776655,0x99,0x04030201,0x08070605,9,0]


def cases(chip):
    patterns=(0,1,0xff,0x100,0xffff,0x10000,0x80000000,MASK)
    for raw in range(65536):
        c=default_case(0);c[1]=raw|0xa5a50000;c[19]=0x80000001
        yield c
    for operation in (1,2):
        for byte in range(256):
            for upper in (0,0x100,0xffff0000):
                for host in (0,1,18,0x80000000,MASK):
                    for hooks in (0,1,2,3):
                        c=default_case(operation);c[1:5]=[upper|byte,0xdeadbeef,upper|(byte^85),upper|(byte^170)]
                        c[8]=host;c[19]=0x80000001;c[23]=byte%4
                        c[13:17]=[MASK if hooks&1 else 0]*2+[MASK if hooks&2 else 0]*2
                        c[21:23]=[MASK if hooks&2 else 0]*2
                        yield c
    for operation in (3,4,5,6,7,8,9):
        if chip=='esp32s3' and operation in (5,6):continue
        if chip=='esp32c3' and operation==7:continue
        for value in range(256):
            for hooks in (0,1,2,3):
                c=default_case(operation);c[1]=value;c[2]=value;c[5]=value;c[24]=value
                c[13:17]=[MASK if hooks&1 else 0]*2+[MASK if hooks&2 else 0]*2
                c[21:23]=[MASK if hooks&2 else 0]*2;c[19]=0x80000001
                yield c
    for operation in (0,1,2,3,4):
        for value in patterns:
            for other in patterns:
                c=default_case(operation);c[1]=value;c[7]=value;c[8]=other;c[9]=other
                c[10]=value;c[11:13]=[value,other];c[18]=other;c[19]=value
                c[13:17]=[MASK]*4;c[21:23]=[MASK]*2
                yield c
    if chip=='esp32s3':
        for rate in range(256):
            for enabled in (0,1):
                for position in range(9):
                    for value in (0,1,15,16,127,128,255):
                        c=default_case(7);c[2]=0xffff0000|rate;c[24]=enabled
                        field=25 if enabled else 28
                        payload=bytearray(9);payload[position]=value
                        c[field:field+3]=struct.unpack('<III',payload+b'\0\0\0')
                        c[13:17]=[MASK]*4
                        yield c
    for position in range(8):
        for seed in range(256):
            c=default_case(3);c[5]=seed;c[13]=1<<position;c[15]=1<<position;c[21]=1<<position
            c[19]=0x80000001
            yield c


def main():
    chip,destination=sys.argv[1:]
    fixture=json.loads(Path(__file__).with_name('iram-original-instructions.json').read_text())
    oracle=Oracle(chip,fixture['chips'][chip]);digest,count=hashlib.sha256(),0
    with open(destination,'wb') as stream:
        for case in cases(chip):
            result,trace=oracle.run(case);words=(*case,result,len(trace)//9,*trace)
            encoded=struct.pack('<'+'I'*len(words),*words);stream.write(encoded);digest.update(encoded);count+=1
    report={'chip':chip,'cases':count,'oracle_sha256':digest.hexdigest()}
    expected=json.loads(Path(__file__).with_name('iram-expected-results.json').read_text())[chip]
    require(report==expected,'Original instruction trace digest changed');print(json.dumps(report))


if __name__=='__main__':main()
