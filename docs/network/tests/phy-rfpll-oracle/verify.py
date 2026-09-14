#!/usr/bin/env python3
"""Execute pinned PHY tracking instructions with ordered state and callback traces."""
import hashlib,json,re,struct,sys
from pathlib import Path
MASK=0xffffffff
SUPPORTED = {'sub', 'sh', 'bltu', 'l32r', 'addi.n', 'add.n', 'movi.n', 'l8ui', 'j', 'sw', 'bnez.n', 'mov.n', 'l16ui', 's16i', 'l16si', 'slli', 'li', 'srli', 'l32i.n', 'jal', 'call8', 'movi', 'sext', 'and', 'beq', 's32i.n', 'lw', 'blti', 'bge', 's8i', 'lb', 'bnei', 'jr', 'div', 'l32i', 'bne', 'or', 'entry', 'lhu', 'lh', 'auipc', 'mv', 'beqz', 'lui', 'jalr', 'extui', 'mulsh', 'retw.n', 'addmi', 'bgez', 'bltz', 'lbu', 'blt', 'bnez', 'callx8', 'add', 'addi', 'zext.b', 'beqz.n', 'memw', 'ret', 'srai', 'sb', 's32i'}
SUPPORTED.add('moveqz')
SUPPORTED.update({'movnez', 'mul16u', 'addx8', 'addx4', 'beqi', 'bbsi', 'quos', 'loop', 'snez', 'mul', 'ori', 'andi', 'addx2', 'mull'})
CONDITIONAL = ('beqi','bbsi','beq','bne','beqz','beqz.n','bnez','bnez.n','bltz','bgez','blt','bltu','bge','bnei','blti')

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
            require(op in SUPPORTED, 'Unsupported instruction '+op)
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
                    require(target in {int(s['address'],0) for s in [*evidence['symbols'].values(),*evidence['functions']]}, 'Unknown tail target')
                    continue
                pending.append(target)
                continue
            if op in CONDITIONAL or op == 'loop':
                pending.append(int(args[-1], 16))
            pending.append(next_pc)
        require(reached == {a for a in program if start <= a < start+size}, 'Unreachable fixture instruction')
    require(len(starts) in (16,18) and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts



NAMES={chip:dict(enumerate(['restart_cal','write_rfpll_sdm','wait_rfpll_cal_end','rfpll_set_freq','correct_rfpll_offset',
 'rom2_write_pll_cap' if chip=='esp32c3' else 'ram_write_pll_cap',
 'rom2_read_pll_cap' if chip=='esp32c3' else 'read_pll_cap',
 'ram2_rfpll_cap_correct' if chip=='esp32c3' else 'rfpll_cap_correct','rfpll_cap_init_cal','set_rfpll_freq','set_rf_freq_offset','set_channel_rfpll_freq','chip_v7_set_chan_misc','chip_v7_set_chan','chip_v7_set_chan_offset','chip_v7_set_chan_ana']+([] if chip=='esp32c3' else ['phy_set_freq','ram_pll_vol_cal']))) for chip in ['esp32c3','esp32s3']}
ARITY={0:0,1:1,2:0,3:4,4:3,5:1,6:0,7:2,8:0,9:4,10:3,11:3,12:1,13:2,14:1,15:1,16:2,17:0}
RETURNS={6,7,8,11,17}
EXT_ARITY={0:1,1:1,2:3,3:8,4:1,5:2,6:1,7:0,8:1,9:2,10:2}
POINTER={1:0,3:3,4:2,9:3}

def fields(chip):
    return {1:{0xe6,0xef,0xf0,0xf1,0xf3,0x1f2,0x1f3,0x1f4,0x1f6,0x11a,0x11e,0x11f,0x2a8 if chip=='esp32s3' else 0x325},2:{0xe0,0x11c,0x118,0x2aa if chip=='esp32s3' else 0x326},4:{0x120}}

def initial(chip,c):
    s3=chip=='esp32s3';rows=[]
    def put(o,w,v):rows.append((o,w,v&((1<<(w*8))-1)))
    for o,i,shift in [(0xe0,24,0),(0x2aa if s3 else 0x326,24,16),(0x11c,28,0),(0x118,28,16)]:put(o,2,c[i]>>shift)
    for o,i,shift in [(0x2a8 if s3 else 0x325,25,0),(0xef,25,8),(0xe6,25,16),(0x1f4,25,24),(0x1f2,26,0),(0xf3,26,8),(0xf0,26,16),(0xf1,26,24),(0x1f6,27,0),(0x11a,27,8),(0x11e,27,16),(0x11f,27,24)]:put(o,1,c[i]>>shift)
    put(0x1f3,1,0);put(0x120,4,c[29]);return rows

class Oracle:
    def __init__(self,chip,evidence):
        require(chip in NAMES,'Unknown chip');self.chip,self.e=chip,evidence
        self.program,_=decode(evidence)
        require({f['name'] for f in evidence['functions']}==set(NAMES[chip].values()),'Unexpected function names')
        self.entries={kind:next(int(f['address'],0) for f in evidence['functions'] if f['name']==name) for kind,name in NAMES[chip].items()};self.kinds={v:k for k,v in self.entries.items()}
        symbols=evidence['symbols'];self.param=int(symbols['phy_param']['address'],0);self.table=int(symbols['g_phyFuns']['address'],0);self.extent=symbols['phy_param']['size_bytes']
        require(self.extent==(848 if chip=='esp32c3' else 740),'Wrong state extent')
        names={0:'ets_delay_us',1:'rom2_pll_cap_mem_update' if chip=='esp32c3' else 'pll_cap_mem_update',2:'set_chan_freq_sw_start',3:'wr_rx_gain_mem',6:'force_txrx_off',8:'chan14_mic_cfg',9:'phy_11p_set',10:'phy_freq_correct'}
        if chip=='esp32c3':names.update({4:'rom_set_chan_reg',5:'ram1_wifi_set_tx_gain',7:'get_txcap_data'})
        self.externals={int(symbols[name]['address'],0):kind for kind,name in names.items()}
        self.printf=int(symbols['phy_printf']['address'],0);self.memcpy=int(symbols['memcpy']['address'],0)
        self.strings={int(s['address'],0):s['kind'] for s in evidence['strings']}
        require(len(self.strings)==2,'Wrong format count')
        for s in evidence['strings']:require(bytes.fromhex(s['bytes'])==s['text'].encode()+b'\0','Format bytes differ')
        self.slots=({0x1ac:3,0x1b4:4,0x1b8:5,0x1bc:6,0x28:3,0x1f8:1,0x184:0,0x188:1,8:0,12:0,0x78:1,0x60:7} if chip=='esp32c3' else {0x188:3,0x190:4,0x194:5,0x198:6,0x28:3,0x20c:1,0x1d4:1,0x160:0,0x164:1,8:0,12:0,0x6c:1,0x24c:1,0x264:2})
        self.visited=set();self.branches=set()

    def run(self,c):
        require(len(c)==48 and all(0<=v<=MASK for v in c),'Invalid case words')
        require(c[0] in self.entries and c[17]<=100 and c[37]<=2 and c[38]<=1 and not any(c[39:]),'Invalid case domain')
        s3=self.chip=='esp32s3';param=self.param;memory={};trace=[];generation=0;calls=0;clamps=0;statuses=0;polls=0;steps=0;mmreads=0;bindings=[]
        def event(kind,*args):
            require(len(args)<=11 and len(trace)<12*4096,'Event budget exhausted');trace.extend([kind,*(a&MASK for a in args),*([0]*(11-len(args)))])
        def put(address,width,value):
            for i in range(width):memory[address+i]=(value>>(i*8))&255
        def get(address,width):
            require(all(address+i in memory for i in range(width)),f'Uninitialized memory {address:x}/{width}');return sum(memory[address+i]<<(8*i) for i in range(width))
        for offset,width,value in initial(self.chip,c):put(param+offset,width,value)
        for i in range(16):put(0x300000+i,1,(c[30+i//4%2]>>(8*(i%4)))&255)
        for i,a in enumerate([0x6000e0c4,0x6000e0c0,0x6000e148,0x6001c130]):put(a,4,c[32+i])
        constants={}
        for blob in self.e['constants']:
            a=int(blob['address'],0)
            for i,v in enumerate(bytes.fromhex(blob['bytes'])):constants[a+i]=v
        def canonical(address):
            if param<=address<param+self.extent:return 0x200000+address-param
            if 0x300000<=address<0x300010:return address
            for base,width,target in reversed(bindings):
                if base<=address<base+width:return target+address-base
            raise ValueError(f'Unknown canonical address {address:x}')
        def bind(address,kind):
            if not 0x100000<=address<0x110000:return
            if not any(base==address and target==(0x310000 if kind==1 else 0x300000) for base,width,target in bindings):bindings.append((address,9 if kind==1 and not s3 else (1 if kind==1 else 3),0x310000 if kind==1 else 0x300000))
        access_fields=fields(self.chip)
        def read(address,width):
            nonlocal mmreads
            if address==self.table and width==4:event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=address<0x70400000 and width==4:
                active,slot=divmod(address-0x70000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback slot');event(5,slot,active);return 0x71000000+active*0x1000+slot
            if address in [0x6000e0c4,0x6000e0c0,0x6000e148,0x6001c130]:
                require(width==4,'Wrong MMIO width');value=get(address,4)^((c[36]*mmreads)&MASK);mmreads+=1;event(7,address,value);return value
            if param<=address<param+self.extent:
                require(width in access_fields and address-param in access_fields[width] or width==1 and c[37]!=0 and param+0xe0<=address<param+0xe0+3 or width in (1,2) and c[37]==2 and param+0x11e<=address and address+width<=param+0x121,f'Unknown parameter read {address-param:x}/{width} op{c[0]}')
                value=get(address,width);event(1,canonical(address),width,value);return value
            if address in constants:
                require(width==1,'Wrong constant width');return constants[address]
            if 0x300000<=address and address+width<=0x300010:
                value=get(address,width);event(1,address,width,value);return value
            require(0x100000<=address and address+width<=0x110000,'Unmapped read')
            value=get(address,width)
            if any(b<=address and address+width<=b+w for b,w,t in bindings):event(1,canonical(address),width,value)
            return value
        def write(address,width,value):
            value&=(1<<(width*8))-1
            if address in [0x6000e0c4,0x6000e0c0,0x6000e148,0x6001c130]:require(width==4,'Wrong MMIO width');event(8,address,value);put(address,width,value);return
            if param<=address<param+self.extent:
                require(width in access_fields and address-param in access_fields[width] or width==1 and c[37]!=0 and param+0xe0<=address<param+0xe0+3 or width in (1,2) and c[37]==2 and param+0x11e<=address and address+width<=param+0x121,f'Unknown parameter write {address-param:x}/{width} op{c[0]}');event(2,canonical(address),width,value);put(address,width,value);return
            if 0x300000<=address and address+width<=0x300010:event(2,address,width,value);put(address,width,value);return
            require(0x100000<=address and address+width<=0x110000 and width in (1,2,4),'Non-stack write')
            if any(b<=address and address+width<=b+w for b,w,t in bindings):event(2,canonical(address),width,value)
            put(address,width,value)
        def mutate():
            nonlocal generation,calls
            require(calls<1024,'Opaque call budget exhausted')
            mask=1<<(calls%32)
            if c[19]&mask:generation+=1
            if c[20]&mask:
                for width,offsets in access_fields.items():
                    for offset in sorted(offsets):put(param+offset,width,get(param+offset,width)^((c[22]+offset*17)&((1<<(width*8))-1)))
            if c[21]&mask:
                for address in [0x300000,*[b for b,w,t in bindings if t==0x300000]]:
                    for i in range(3):
                        if address+i in memory:put(address+i,1,get(address+i,1)^((c[22]+i*17)&255))
            calls+=1
        def new_registers():
            r={f'a{i}':(0xabc00000+i*0x1001)&MASK for i in range(16)}
            r.update({f's{i}':0xddd00000+i*0x1001 for i in range(12)});r.update({f't{i}':0xeee00000+i*0x1001 for i in range(7)});r.update(sp=0x110000,ra=0,zero=0)
            if s3:r['a1']=0x110000
            return r
        def clobber(regs,result):
            for key in ([f'a{i}' for i in range(8,16)] if s3 else [f'a{i}' for i in range(8)]+[f't{i}' for i in range(7)]):regs[key]=0xdeadbeef
            regs['a10' if s3 else 'a0']=result&MASK
        def invoke(target,args,parent,depth):
            before=len(bindings)
            if s3:
                child=new_registers();child['a1']=parent['a1'];child.update({f'a{i+2}':v for i,v in enumerate(args[:6])});result=execute(target,child,depth+1)
            else:result=execute(target,parent,depth+1)
            del bindings[before:];return result
        def execute(pc,r,depth=0):
            nonlocal steps,clamps,statuses,polls
            require(depth<12,'Call nesting exhausted');loop=None
            while True:
                steps+=1;require(steps<=200000,'Instruction budget exhausted')
                require(pc in self.program,'Unknown branch target')
                self.visited.add(pc)
                next_pc,op,args=self.program[pc]
                if op=='entry':
                    require(s3 and args[0]=='a1' and int(args[1],0) in (16,32,48,64,80,96,112,128),'Unexpected entry')
                    r['a1']-=int(args[1],0)
                elif op in ('li','movi','movi.n'):r[args[0]]=int(args[1],0)&MASK
                elif op in ('mv','mov.n'):r[args[0]]=r[args[1]]
                elif op=='lui':r[args[0]]=(int(args[1],0)<<12)&MASK
                elif op=='auipc':r[args[0]]=(pc+(int(args[1],0)<<12))&MASK
                elif op in ('addi','addi.n','addmi'):r[args[0]]=(r[args[1]]+int(args[2],0))&MASK
                elif op in ('add','add.n','addx2','addx4','addx8','mul','mull','mul16u','mulsh','sub','or','and','div','divu','quos','quou'):
                    left,right=r[args[1]],r[args[2]]
                    if op in ('add','add.n'):value=left+right
                    elif op=='addx2':value=2*left+right
                    elif op=='addx4':value=4*left+right
                    elif op=='addx8':value=8*left+right
                    elif op in ('mul','mull'):value=left*right
                    elif op=='mul16u':value=(left&65535)*(right&65535)
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
                elif op in ('moveqz','movnez'):
                    if (r[args[2]]==0)==(op=='moveqz'):r[args[0]]=r[args[1]]
                elif op=='snez':r[args[0]]=int(r[args[1]]!=0)
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
                    if op=='bbsi':take=bool(left&(1<<int(args[1],0)))
                    elif op in ('bnez','bnez.n'):take=left!=0
                    elif op in ('beqz','beqz.n'):take=left==0
                    elif op=='bltz':take=signed(left)<0
                    elif op=='bgez':take=signed(left)>=0
                    else:
                        right=int(args[1],0)&MASK if op in ('beqi','bnei','blti') else r[args[1]]
                        if op in ('beq','beqi'):take=left==right
                        elif op in ('bne','bnei'):take=left!=right
                        elif op=='bltu':take=left<right
                        elif op in ('blt','blti'):take=signed(left)<signed(right)
                        else:take=signed(left)>=signed(right)
                    self.branches.add((pc,take))
                    if take:next_pc=int(args[-1],16)
                elif op=='loop':
                    require(s3 and 0<r[args[0]]<=100,'Unexpected loop count')
                    loop=[next_pc,int(args[1],16),r[args[0]]]
                elif op=='j' and int(args[0],16) in self.program and int(args[0],16) not in self.kinds:
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
                    def values(n):
                        return [r[f'a{i+10}'] if i<6 else get(r['a1']+(i-6)*4,4) for i in range(n)] if s3 else [r[f'a{i}'] for i in range(n)]
                    if target in self.kinds:
                        kind=self.kinds[target];v=values(ARITY[kind]);clean=v.copy()
                        if kind in POINTER:
                            index=POINTER[kind];bind(v[index],0);clean[index]=canonical(v[index])
                        event(9,kind,*clean)
                        if c[23]&(1<<kind):result=invoke(target,v,r,depth)
                        else:
                            if kind in (3,9) and c[38]:
                                for i in range(3):put(v[3]+i,1,c[30]>>(i*8))
                            mutate();result=c[10] if kind==6 else c[12]
                    elif target in self.externals:
                        kind=self.externals[target];v=values(EXT_ARITY[kind]);clean=v.copy()
                        if kind==3:
                            bind(v[2],1)
                            for i in (2,3,4,5):clean[i]=canonical(v[i])
                            event(13,*[get(v[2]+i,1) for i in range(1 if s3 else 9)])
                        event(10,kind,*clean);mutate();result=c[12]
                    elif target==self.printf:
                        fmt=values(1)[0];require(fmt in self.strings,'Unknown format string');kind=self.strings[fmt]
                        event(12,kind,*values(1 if kind==0 else 7)[1:]);mutate();result=c[12]
                    elif target==self.memcpy:
                        v=values(3);require(not s3 and v[2]==9 and bytes(constants.get(v[1]+i,0) for i in range(9))==bytes.fromhex('a0848ee8eed2f2f8fe'),'Unexpected local constant copy')
                        for i in range(9):put(v[0]+i,1,constants[v[1]+i])
                        result=v[0]
                    else:
                        require(0x71000000<=target<0x71400000,'Unknown callback target')
                        active,slot=divmod(target-0x71000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback slot')
                        v=values(self.slots[slot]);event(6,target,*v)
                        if s3 and slot==0x20c and c[23]&(1<<5):result=invoke(self.entries[5],v,r,depth)
                        else:
                            result=c[12]
                            if slot==0x28:
                                result=c[7+min(clamps,1)] if c[9] else min(max(signed(v[0]),signed(v[2])),signed(v[1]))&MASK;clamps+=1
                            elif slot==(0x1d4 if s3 else 0x1f8):result=c[11]
                            elif slot==(0x188 if s3 else 0x1ac):
                                if v==[98,1,5]:result=c[5]
                                else:
                                    require(v==[98,1,12],'Unexpected raw read')
                                    code=((c[14+statuses//16]>>(2*(statuses%16)))&3) if statuses<32 else c[16]&3
                                    result=(c[13]&~12)|(code<<2);statuses+=1
                            elif slot==(0x194 if s3 else 0x1b8):
                                if v==[98,1,7,2,2]:result=c[6]
                                else:
                                    require(v==[98,1,7,1,1],'Unexpected mask read');result=0 if polls<c[17] else c[18];polls+=1
                            mutate()
                    clobber(r,result)
                    if tail:return result
                elif op=='memw':require(s3 and not args,'Unexpected barrier')
                elif op in ('ret','retw.n'):
                    require((op=='retw.n')==s3,'Wrong return ABI');return r['a2' if s3 else 'a0']
                else:raise ValueError('Unknown instruction '+op)
                if loop and next_pc==loop[1]:
                    loop[2]-=1
                    if loop[2]:next_pc=loop[0]
                    else:loop=None
                pc=next_pc
        registers=new_registers();args=c[1:5].copy()
        if c[0] in POINTER:
            args[POINTER[c[0]]]=(param+(0xe0 if c[37]==1 else 0x11e)) if c[37] else 0x300000
            # Partial overlap with adjacent bytes is explicit in the pointer cases.
            for i in range(3):
                address=args[POINTER[c[0]]]+i
                if address not in memory:put(address,1,(c[30]>>(i*8))&255)
        for i,value in enumerate(args):registers[f'a{i+(2 if s3 else 0)}']=value
        result=execute(self.entries[c[0]],registers)
        return result if c[0] in RETURNS else 0,trace

def default_case(op):
    c=[0]*48;c[0]=op;c[1:5]=[1,1,3,0];c[5]=200;c[6]=0;c[7:9]=[202,204];c[10]=200;c[11]=2412;c[12]=0x13579bdf;c[13]=0xabcdef03;c[14]=1;c[17]=2;c[18]=1;c[22]=0x1357;c[23]=0x3ffff;c[24]=100|(201<<16);c[25]=0x00010100;c[26]=1|(1<<8)|(3<<16)|(0x97<<24);c[27]=8|(4<<8);c[28]=0x12340010;c[30]=0x00985634;c[31]=0x87654321;c[32:36]=[0x543210ff,0x12345678,0xabcd1234,0x98761234];c[38]=1
    if op==3:c[1:4]=[2412,1,3]
    if op==7:c[1:3]=[1,0]
    return c

def smoke_cases(chip):
    for op in NAMES[chip]:
        for nested in (0,0x3ffff):
            c=default_case(op);c[23]=nested;yield c
        for axis,values in [(1,(0,1,2,14,127,128,255,256,257,MASK)),(2,(0,1,2,3,255,256,MASK)),(3,(0,32767,32768,65535,65536,MASK)),(17,(0,99,100)),(19,(1,2,MASK)),(20,(1,2,MASK)),(21,(1,2,MASK)),(23,(1<<5,1<<6)),(25,(0,1,MASK)),(29,(0,32,MASK)),(36,(0,0x12345678))]:
            for value in values:
                c=default_case(op);c[axis]=value;yield c
    for op in (1,3,4,9):
        for alias in (1,2):c=default_case(op);c[37]=alias;yield c

def cases(chip):
    yield from smoke_cases(chip)
    edges=(0,1,2,3,4,9,10,14,31,127,128,255,256,257,511,512,32767,32768,65535,65536,0x7fffffff,0x80000000,MASK)
    for op in NAMES[chip]:
        for axis in [1,2,3,5,6,7,8,10,11,12,13,14,15,16,18,22,24,25,26,27,28,29,30,31,32,33,34,35,36]:
            for value in edges:
                c=default_case(op);c[axis]=value;c[9]=int(axis in (7,8));yield c
        for mask in (0,1,2,4,8,0x55,0xaa,0xffff,MASK):
            for axis in (19,20,21,23):
                c=default_case(op);c[axis]=mask;yield c
    # Independent input axes, not a Cartesian proof of all PLL states.
    for value in range(65536):
        c=default_case(3);c[3]=value;c[2]=value%5;yield c
        c=default_case(5);c[1]=value;yield c
    for first in range(4):
        for second in range(4):
            for final in range(4):
                for at in (1,2,9,10):
                    for busy in (0,1):
                        c=default_case(7);c[14]=sum((first if i<at else second if i==at else final)<<(i*2) for i in range(16));c[25]=busy;c[2]=busy;yield c
    for count in range(101):
        c=default_case(2);c[17]=count;yield c
    for op in (7,8):
        for word in (0,0x55555555,0xaaaaaaaa,MASK,1,4,0x40000000,0x80000000):
            for value in (0,1,255,256,511,65535,MASK):
                c=default_case(op);c[14]=c[15]=word;c[5]=value;c[10]=value;yield c

def stream(chip,output,smoke=False):
    data=json.loads(Path(__file__).with_name('original-instructions.json').read_text());oracle=Oracle(chip,data[chip]);digest=hashlib.sha256();count=0;coverage={str(op):0 for op in NAMES[chip]}
    for case in (smoke_cases(chip) if smoke else cases(chip)):
        result,trace=oracle.run(case);require(len(trace)%12==0,'Invalid trace shape');words=case+[result,len(trace)//12]+trace;packed=struct.pack('<'+'I'*len(words),*words);output.write(packed);digest.update(packed);count+=1;coverage[str(case[0])]+=1
    require(all(coverage.values()),'Missing function coverage')
    return {'cases':count,'operations':coverage,'case_stream_sha256':digest.hexdigest(),'fixture_sha256':hashlib.sha256(json.dumps(data[chip],sort_keys=True).encode()).hexdigest(),'visited_instructions':len(oracle.visited),'reachable_instructions':len(oracle.program),'conditional_edges':len(oracle.branches)}

def main():
    require(len(sys.argv) in (3,4),'Usage: verify.py chip output.bin [--smoke]');chip=sys.argv[1]
    with Path(sys.argv[2]).open('wb') as out:result=stream(chip,out,len(sys.argv)==4)
    if len(sys.argv)==3:
        expected=json.loads(Path(__file__).with_name('expected-results.json').read_text())[chip]
        require(result==expected,'Oracle results differ from reviewed fixture')
        require(result['visited_instructions']==result['reachable_instructions'],'Instruction coverage incomplete')
    print(json.dumps({chip:result}))
if __name__=='__main__':main()
