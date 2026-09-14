#!/usr/bin/env python3
"""Execute pinned PHY tracking instructions with ordered state and callback traces."""
import hashlib,json,re,struct,sys
from pathlib import Path
MASK=0xffffffff
SUPPORTED = {'sub', 'sh', 'bltu', 'l32r', 'addi.n', 'add.n', 'movi.n', 'l8ui', 'j', 'sw', 'bnez.n', 'mov.n', 'l16ui', 's16i', 'l16si', 'slli', 'li', 'srli', 'l32i.n', 'jal', 'call8', 'movi', 'sext', 'and', 'beq', 's32i.n', 'lw', 'blti', 'bge', 's8i', 'lb', 'bnei', 'jr', 'div', 'l32i', 'bne', 'or', 'entry', 'lhu', 'lh', 'auipc', 'mv', 'beqz', 'lui', 'jalr', 'extui', 'mulsh', 'retw.n', 'addmi', 'bgez', 'bltz', 'lbu', 'blt', 'bnez', 'callx8', 'add', 'addi', 'zext.b', 'beqz.n', 'memw', 'ret', 'srai', 'sb', 's32i'}
CONDITIONAL = ('beq','bne','beqz','beqz.n','bnez','bnez.n','bltz','bgez','blt','bltu','bge','bnei','blti')

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
                if not start <= target < start+size:
                    require(target in {int(s['address'],0) for s in evidence['symbols'].values()}, 'Unknown tail target')
                    continue
                pending.append(target)
                continue
            if op in CONDITIONAL or op == 'loop':
                pending.append(int(args[-1], 16))
            pending.append(next_pc)
        require(reached == {a for a in program if start <= a < start+size}, 'Unreachable fixture instruction')
    require(len(starts) in (7,8) and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts



NAMES={
 'esp32c3':{0:'rom2_wait_hw_freq_busy',1:'rom2_ulp_ext_code_set',2:'rom2_ulp_code_track',3:'ram2_rfpll_cap_track',4:'rom1_txpwr_cal_track',5:'txpwr_offset',6:'rfcal_track'},
 'esp32s3':{0:'wait_hw_freq_busy',1:'ulp_ext_code_set',2:'ulp_code_track',3:'rfpll_cap_track',4:'ram_txpwr_cal_track',5:'txpwr_offset',7:'ram_wifi_track_tx_power',8:'ram_bt_track_tx_power'}}
class BoundaryStop(Exception):pass

def fields(chip):
    s3=chip=='esp32s3';busy=0x2a4 if s3 else 0x321
    return {1:{0x204,0x9b,0x9f,0xa0,0x1fa,0x1fb,0x1fc,0x1f2,busy,busy+4},
            2:{0x92,0x94,0x96,0xae,0xb0,0xb2,0xb4,*((0x206,0x208,0x2c4,0x2c6) if s3 else (0x20c,0x20e,0x210,0x212,0x214))},4:{0x120,0x200}}

def initial(chip,c):
    s3=chip=='esp32s3';rows=[]
    def put(offset,width,value):rows.append((offset,width,value&((1<<(8*width))-1)))
    for offset,index,shift in [(0x92,19,0),(0x94,19,16),(0x96,20,0),(0x2c6 if s3 else 0x212,20,16),(0x206 if s3 else 0x20c,21,0),(0x208 if s3 else 0x20e,21,16),(0x2c4 if s3 else 0x210,22,0),(0xae,23,0),(0xb0,23,16),(0xb2,24,0),(0xb4,24,16)]:put(offset,2,c[index]>>shift)
    if not s3:put(0x214,2,c[22]>>16)
    for offset,index,shift in [(0x204,25,0),(0x9b,25,8),(0x9f,25,16),(0xa0,25,24),(0x1fa,26,0),(0x1fb,26,8),(0x1fc,26,16),(0x1f2,26,24),(0x2a4 if s3 else 0x321,27,0),(0x2a8 if s3 else 0x325,27,8)]:put(offset,1,c[index]>>shift)
    put(0x120,4,c[28]);put(0x200,4,c[18]);return rows

class Oracle:
    def __init__(self,chip,evidence):
        require(chip in NAMES,'Unknown chip');self.chip,self.e=chip,evidence
        self.program,starts=decode(evidence)
        require({f['name'] for f in evidence['functions']}==set(NAMES[chip].values()),'Unexpected function names')
        self.entries={kind:next(int(f['address'],0) for f in evidence['functions'] if f['name']==name) for kind,name in NAMES[chip].items()}
        self.kinds={value:key for key,value in self.entries.items()}
        symbols=evidence['symbols'];self.param=int(symbols['phy_param']['address'],0);self.table=int(symbols['g_phyFuns']['address'],0)
        self.extent=symbols['phy_param']['size_bytes'];require(self.extent==(848 if chip=='esp32c3' else 740),'Wrong state extent')
        ext={0:'ets_delay_us',1:'__opensensor_debug_voltage',2:'__opensensor_tsens_temp_to_power',3:'ram2_rfpll_cap_correct' if chip=='esp32c3' else 'rfpll_cap_correct'}
        if chip=='esp32c3':ext.update({4:'txdc_cal_init',5:'ram1_wifi_set_tx_gain',6:'rom1_bt_set_tx_gain',7:'rom_phy_bbpll_cal'})
        self.externals={int(symbols[name]['address'],0):kind for kind,name in ext.items()}
        self.printf=int(symbols['phy_printf']['address'],0)
        self.strings={int(s['address'],0):s['kind'] for s in evidence['strings']}
        require(len(self.strings)==(4 if chip=='esp32c3' else 3),'Wrong format count')
        for s in evidence['strings']:require(bytes.fromhex(s['bytes'])==s['text'].encode()+b'\0','Format bytes differ')
        self.abs_slot=0x100 if chip=='esp32c3' else 0xec
        self.slots=({0x100:1,0x28:3,0x1ac:3,0x1b4:4,0x1bc:6,0x228:0,0x224:0,0x118:2,8:0,12:0} if chip=='esp32c3' else {0xec:1,0x28:3,0x188:3,0x190:4,0x198:6,0x204:0,0x200:0,0x194:5,0x104:2,0x240:1,0x264:2,0x270:1,0x268:3})

    def run(self,c):
        require(len(c)==32 and all(0<=v<=MASK for v in c),'Invalid case words')
        require(c[0] in self.entries and c[16]<16 and (c[17]<64 or c[17]==MASK) and c[31]==0,'Invalid case domain')
        s3=self.chip=='esp32s3';param=self.param;memory={};trace=[];generation=0;calls=0;abs_calls=0;conversions=0;polls=0;steps=0
        def event(kind,*args):
            require(len(args)<=7 and len(trace)<8*512,'Event budget exhausted')
            trace.extend([kind,*(a&MASK for a in args),*([0]*(7-len(args)))])
        def put(address,width,value):
            for i in range(width):memory[address+i]=(value>>(i*8))&255
        def get(address,width):
            require(all(address+i in memory for i in range(width)),f'Uninitialized memory {address:x}/{width}')
            return sum(memory[address+i]<<(8*i) for i in range(width))
        for offset,width,value in initial(self.chip,c):put(param+offset,width,value)
        def canonical(address):
            require(param<=address<param+self.extent,'Unknown parameter address');return 0x200000+address-param
        access_fields=fields(self.chip)
        def read(address,width):
            nonlocal polls
            if address==self.table and width==4:event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=address<0x70040000 and width==4:
                active,slot=divmod(address-0x70000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback slot');event(5,slot,active);return 0x71000000+active*0x1000+slot
            if address==0x6000e168:
                require(width==4,'Wrong MMIO width')
                if polls==64:raise BoundaryStop()
                value=(c[30]&0x7fffffff)|((polls<c[17])<<31);polls+=1;event(7,address,value);return value
            if param<=address<param+self.extent:
                require(width in access_fields and address-param in access_fields[width],'Unknown parameter read')
                value=get(address,width);event(1,canonical(address),width,value);return value
            require(0x100000<=address and address+width<=0x110000,'Unmapped read');return get(address,width)
        def write(address,width,value):
            value&=(1<<(width*8))-1
            if param<=address<param+self.extent:
                require(width in access_fields and address-param in access_fields[width],'Unknown parameter write')
                event(2,canonical(address),width,value);put(address,width,value);return
            require(0x100000<=address and address+width<=0x110000 and width in (1,2,4),'Non-stack write');put(address,width,value)
        def mutate():
            nonlocal generation,calls
            require(calls<32,'Opaque call budget exhausted')
            if c[14]&(1<<calls):generation+=1
            if c[15]&(1<<calls):
                for width,offsets in access_fields.items():
                    for offset in sorted(offsets):put(param+offset,width,get(param+offset,width)^((c[29]+offset*17)&((1<<(width*8))-1)))
            calls+=1
        def new_registers():
            r={f'a{i}':(0xabc00000+i*0x1001)&MASK for i in range(16)}
            r.update({f's{i}':0xddd00000+i*0x1001 for i in range(12)})
            r.update({f't{i}':0xeee00000+i*0x1001 for i in range(7)})
            r.update(sp=0x110000,ra=0,zero=0)
            r['a1']=0x110000 if s3 else r['a1']
            return r
        def clobber(regs,result):
            for key in ([f'a{i}' for i in range(8,16)] if s3 else [f'a{i}' for i in range(8)]+[f't{i}' for i in range(7)]):regs[key]=0xdeadbeef
            regs['a10' if s3 else 'a0']=(result[0] if isinstance(result,tuple) else result)&MASK
            if isinstance(result,tuple):regs['a11' if s3 else 'a1']=result[1]&MASK
        def invoke(target,args,parent,depth):
            if s3:
                child=new_registers();child['a1']=parent['a1']
                child.update({f'a{i+2}':v for i,v in enumerate(args[:6])})
                return execute(target,child,depth+1)
            return execute(target,parent,depth+1)
        def execute(pc,r,depth=0):
            nonlocal steps,abs_calls,conversions
            require(depth<5,'Call nesting exhausted');loop=None
            while True:
                steps+=1;require(steps<=10000,'Instruction budget exhausted')
                require(pc in self.program,'Unknown branch target')
                next_pc,op,args=self.program[pc]
                if op=='entry':
                    require(s3 and args[0]=='a1' and int(args[1],0) in (16,32,48,64,80,96,112,128),'Unexpected entry')
                    r['a1']-=int(args[1],0)
                elif op in ('li','movi','movi.n'):r[args[0]]=int(args[1],0)&MASK
                elif op in ('mv','mov.n'):r[args[0]]=r[args[1]]
                elif op=='lui':r[args[0]]=(int(args[1],0)<<12)&MASK
                elif op=='auipc':r[args[0]]=(pc+(int(args[1],0)<<12))&MASK
                elif op in ('addi','addi.n','addmi'):r[args[0]]=(r[args[1]]+int(args[2],0))&MASK
                elif op in ('add','add.n','addx4','addx8','mul','mulsh','sub','or','and','div','divu','quos','quou'):
                    left,right=r[args[1]],r[args[2]]
                    if op in ('add','add.n'):value=left+right
                    elif op=='addx4':value=4*left+right
                    elif op=='addx8':value=8*left+right
                    elif op=='mul':value=left*right
                    elif op=='mulsh':value=(signed(left)*signed(right))>>32
                    elif op=='sub':value=left-right
                    elif op=='or':value=left|right
                    elif op=='and':value=left&right
                    elif op in ('divu','quou'):
                        if not right:
                            if op=='quou':raise BoundaryStop(1)
                            value=MASK
                        else:value=left//right
                    else:
                        if right==0:
                            require(op=='div','Unexpected signed zero divisor');value=MASK
                        else:
                            left,right=signed(left),signed(right);value=(abs(left)//abs(right))*(-1 if (left<0)!=(right<0) else 1)
                    r[args[0]]=value&MASK
                elif op in ('andi','ori'):
                    value=int(args[2],0)&MASK;r[args[0]]=r[args[1]]&value if op=='andi' else r[args[1]]|value
                elif op in ('slli','srli','srai'):
                    value=r[args[1]];n=int(args[2],0)
                    r[args[0]]=((value<<n) if op=='slli' else ((signed(value)>>n) if op=='srai' else value>>n))&MASK
                elif op=='zext.b':r[args[0]]=r[args[1]]&255
                elif op=='extui':r[args[0]]=(r[args[1]]>>int(args[2],0))&((1<<int(args[3],0))-1)
                elif op=='sext':r[args[0]]=signed(r[args[1]],int(args[2],0)+1)&MASK
                elif op=='moveqz':
                    if r[args[2]]==0:r[args[0]]=r[args[1]]
                elif op=='l32r':
                    literal=hex(int(args[1],16));require(literal in self.e['literals'],'Unknown literal');r[args[0]]=int(self.e['literals'][literal],0)
                elif op in ('lw','lh','lhu','lbu','lb','sw','sh','sb'):
                    m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[1]);require(m is not None,'Bad memory operand')
                    address=(r[m[2]]+int(m[1]))&MASK;width=4 if op in ('lw','sw') else (1 if op in ('lbu','lb','sb') else 2)
                    if op in ('sw','sh','sb'):write(address,width,r[args[0]])
                    else:
                        value=read(address,width);r[args[0]]=(signed(value,16 if op=='lh' else 8) if op in ('lh','lb') else value)&MASK
                elif op in ('l32i','l32i.n','l16si','l16ui','s16i','s32i','s32i.n','l8ui','s8i'):
                    address=(r[args[1]]+int(args[2],0))&MASK;width=2 if '16' in op else (1 if op in ('l8ui','s8i') else 4)
                    if op.startswith('s'):write(address,width,r[args[0]])
                    else:
                        value=read(address,width);r[args[0]]=(signed(value,16) if op=='l16si' else value)&MASK
                elif op in CONDITIONAL:
                    left=r[args[0]]
                    if op in ('bnez','bnez.n'):take=left!=0
                    elif op in ('beqz','beqz.n'):take=left==0
                    elif op=='bltz':take=signed(left)<0
                    elif op=='bgez':take=signed(left)>=0
                    else:
                        right=int(args[1],0)&MASK if op in ('bnei','blti') else r[args[1]]
                        if op=='beq':take=left==right
                        elif op in ('bne','bnei'):take=left!=right
                        elif op=='bltu':take=left<right
                        elif op in ('blt','blti'):take=signed(left)<signed(right)
                        else:take=signed(left)>=signed(right)
                    if take:next_pc=int(args[-1],16)
                elif op=='loop':
                    require(s3 and r[args[0]]==4,'Unexpected loop count')
                    loop=[next_pc,int(args[1],16),r[args[0]]]
                elif op=='j' and int(args[0],16) in self.program:
                    next_pc=int(args[0],16)
                elif op in ('j','jr','jal','jalr','call8','callx8'):
                    tail=op in ('j','jr')
                    if op in ('j','jal','call8'):target=int(args[0],16)
                    elif '(' in args[0]:
                        m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[0]);require(m is not None,'Bad call operand');target=(r[m[2]]+int(m[1]))&MASK
                    else:target=r[args[0]]
                    if not s3:
                        target&=~1
                        if not tail:r['ra']=next_pc
                    values=[r[f'a{i+(10 if s3 else 0)}'] for i in range(6)]
                    if target in self.kinds:
                        kind=self.kinds[target];arity={0:0,1:2,2:1}[kind]
                        event(9,kind,*values[:arity])
                        if c[16]&(1<<kind):result=invoke(target,values,r,depth)
                        else:mutate();result=c[13]
                    elif target in self.externals:
                        kind=self.externals[target];arity={0:1,1:0,2:2 if s3 else 3,3:2,4:4,5:2,6:1,7:1}[kind]
                        clean=values[:arity]
                        if kind==4:clean[0]=canonical(clean[0])
                        event(10,kind,*clean)
                        result={1:c[8],2:c[11],3:c[12]}.get(kind,c[13]);mutate()
                    elif target==self.printf:
                        require(values[0] in self.strings,'Unknown format string')
                        kind=self.strings[values[0]];arity={0:2,1:4 if s3 else 3,2:4 if s3 else 3,3:2}[kind]
                        event(12,kind,*values[1:1+arity]);mutate();result=c[13]
                    else:
                        require(0x71000000<=target<0x71040000,'Unknown callback target')
                        active,slot=divmod(target-0x71000000,0x1000)
                        require(active<=generation and slot in self.slots,'Unknown callback slot')
                        arity=self.slots[slot];event(6,target,*values[:arity])
                        if s3 and slot==0x268 and c[16]&8:result=invoke(self.entries[4],values,r,depth)
                        else:
                            if slot==self.abs_slot:result=c[4+min(abs_calls,1)];abs_calls+=1
                            elif slot==0x28:result=c[6]
                            elif slot==(0x104 if s3 else 0x118):result=c[9+min(conversions,1)];conversions+=1
                            elif slot in ((0x188,0x194) if s3 else (0x1ac,)):result=c[7]
                            else:result=c[13]
                            mutate()
                    clobber(r,result)
                    if tail:return 0
                elif op=='memw':require(s3 and not args,'Unexpected barrier')
                elif op in ('ret','retw.n'):
                    require((op=='retw.n')==s3,'Wrong return ABI');return 0
                else:raise ValueError('Unknown instruction '+op)
                if loop and next_pc==loop[1]:
                    loop[2]-=1
                    if loop[2]:next_pc=loop[0]
                    else:loop=None
                pc=next_pc
        registers=new_registers()
        for i,value in enumerate(c[1:4]):registers[f'a{i+(2 if s3 else 0)}']=value
        status=0
        try:execute(self.entries[c[0]],registers)
        except BoundaryStop:status=1
        return status,trace

def default_case(operation):
    c=[0]*32;c[0]=operation;c[1:4]=[1,1,1];c[4:14]=[20,20,40,19,3200,100,80,0xfffffffd,7,0x13579bdf]
    c[16]=15;c[17]=2;c[18]=0x2468abcd;c[19]=100|(75<<16);c[20]=50|(60<<16);c[21]=60|(70<<16);c[22]=65|(70<<16)
    c[23]=c[24]=((-50)&65535)|(200<<16);c[25]=1|(7<<8)|(19<<16)|(19<<24);c[26]=0x1a020100;c[29]=0x1357;c[30]=0x13579bdf;return c

def smoke_cases(chip):
    for op in NAMES[chip]:
        for arg in (0,1,2,255,256,257,0xffffffff):
            for mode in (0,15):
                c=default_case(op);c[1]=arg;c[16]=mode;yield c
        for index,values in [(4,(0,7,8,9,10,0x7fffffff,0x80000000,MASK)),(5,(1,2,3,4,MASK)),(6,(0,127,128,255,256,32767,32768,65535,65536,MASK)),(7,(0,255,256,MASK)),(8,(0,3299,3300,65535,MASK)),(11,(0,127,128,255,256,MASK)),(17,(0,1,7,63,MASK)),(28,(1<<22,MASK))]:
            for value in values:
                c=default_case(op);c[index]=value;yield c
        for mask in (0,1,2,4,8,0x55,0xaa,0xffff,MASK):
            c=default_case(op);c[14]=mask;c[15]=mask;yield c

def cases(chip):
    yield from smoke_cases(chip)
    edges=(0,1,2,3,4,7,8,9,10,15,16,31,32,63,64,127,128,255,256,257,32767,32768,65535,65536,0x7fffffff,0x80000000,MASK)
    # Exhaustive low-halfword axes: ULP signed delta, clamp return, and
    # power clamp return. Other coordinates vary; this is not a Cartesian proof.
    for value in range(65536):
        c=default_case(2);c[19]=value<<16;c[20]=0;c[6]=edges[value%len(edges)];c[1]=value&1;yield c
        c=default_case(2);c[6]=value;c[25]=(value&255)<<16|((value>>8)<<24);c[1]=value&1;yield c
        c=default_case(4);c[6]=value;c[1]=value%3;c[11]=edges[value%len(edges)];c[3]=value&1;yield c
    for op in NAMES[chip]:
        for axis in (1,2,3,4,5,6,7,8,9,10,11,12,13,18,19,20,21,22,23,24,25,26,27,28,29,30):
            for value in edges:
                c=default_case(op);c[axis]=value;yield c
        for mask in range(256):
            for nested in (0,15):
                for which in (14,15):
                    c=default_case(op);c[which]=mask;c[16]=nested;c[1]=mask&1;yield c
        for bit in range(32):
            for axis in (14,15,28):
                for value in (1<<bit,MASK^(1<<bit)):
                    c=default_case(op);c[axis]=value;yield c
    for value in range(256):
        for high in (0,0x100,0x7fffff00,0xffffff00):
            for op in NAMES[chip]:
                for axis in (1,2,3):
                    c=default_case(op);c[axis]=value|high;c[25]=(c[25]&~255)|value;yield c
        for current in (0,127,128,255):
            for op in (2,4):
                c=default_case(op);c[25]=(value<<16)|(current<<24);c[26]=(value<<8)|(current<<16)|value;c[11]=current;yield c
    for value in range(64):
        for op in (0,3):
            for noise in (0,0x13579bdf,0x7fffffff):
                c=default_case(op);c[17]=value;c[30]=noise;yield c
    for voltage in range(3295,3305):
        for first in edges:
            for second in (0,1,127,128,255,MASK):
                c=default_case(5);c[8:11]=voltage,first,second;yield c
    for op in (3,4,6) if chip=='esp32c3' else (3,4,7,8):
        for distance in range(12):
            for second in range(6):
                for mode in (0,1,16,255):
                    for radio in (0,1,2):
                        c=default_case(op);c[1]=radio;c[4:6]=distance,second;c[25]=(c[25]&~255)|mode;yield c

def stream(chip,output):
    data=json.loads(Path(__file__).with_name('original-instructions.json').read_text());oracle=Oracle(chip,data[chip]);digest=hashlib.sha256();count=0;coverage={str(op):0 for op in NAMES[chip]};stops=0
    for case in cases(chip):
        status,trace=oracle.run(case);require(len(trace)%8==0,'Invalid trace shape')
        words=case+[status,len(trace)//8]+trace;packed=struct.pack('<'+'I'*len(words),*words);output.write(packed);digest.update(packed);count+=1;coverage[str(case[0])]+=1;stops+=status
    require(all(coverage.values()),'Missing function coverage')
    return {'cases':count,'operations':coverage,'busy_prefix_cases':stops,'case_stream_sha256':digest.hexdigest(),'fixture_sha256':hashlib.sha256(json.dumps(data[chip],sort_keys=True).encode()).hexdigest()}

def main():
    require(len(sys.argv)==3,'Usage: verify.py chip output.bin');chip=sys.argv[1]
    with Path(sys.argv[2]).open('wb') as out:result=stream(chip,out)
    expected=json.loads(Path(__file__).with_name('expected-results.json').read_text())[chip];require(result==expected,'Oracle results differ from reviewed fixture');print(json.dumps({chip:result}))
if __name__=='__main__':main()
