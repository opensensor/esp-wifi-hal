#!/usr/bin/env python3
"""Execute pinned hardware-frequency instructions with ordered state and callback traces."""
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

SUPPORTED |= {'sll','ssl','xor','not','jx','bgeu','movgez'}
CONDITIONAL += ('bgeu',)
def decode(evidence):
    program, starts = {}, []
    tables={}
    for table in evidence['jump_tables']:
        raw=bytes.fromhex(table['bytes']);targets=[int(v,0) for v in table['targets']]
        require(hashlib.sha256(raw).hexdigest()==table['sha256'], 'Jump table hash differs')
        require(len(raw)==4*len(targets) and [int.from_bytes(raw[i:i+4],'little') for i in range(0,len(raw),4)]==targets, 'Jump table targets differ')
        owner=next((f for f in evidence['functions'] if f['name']==table['function']),None)
        require(owner is not None, 'Unknown jump table owner')
        start=int(owner['address'],0);end=start+owner['size_bytes'];pc=int(table['dispatch_pc'],0)
        require(start<=pc<end and all(start<=target<end for target in targets), 'Jump table escapes owner')
        require(pc not in tables and len(targets)==(9 if table['function']=='freq_i2c_write_set' else 10), 'Unexpected jump table')
        rows=[r for r in evidence['owned_inputs'] if r['member']=='phy_hw_freq.o' and r['section']=='.rodata.'+table['function']]
        require(len(rows)==1 and rows[0]['address']==table['address'] and rows[0]['size_bytes']==len(raw), 'Jump table ownership differs')
        tables[pc]=targets
    require(len(tables)==2, 'Wrong jump table count')
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
            if op in ('ret', 'retw.n', 'jr', 'jx'):
                if address in tables:
                    require(op in ('jr','jx'),'Wrong dispatch opcode');pending.extend(tables[address])
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
    require(len(starts) == 11 and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts

NAMES={c:dict(enumerate(['wait_freq_set_busy',
 'ram1_phy_dis_hw_set_freq' if c=='esp32c3' else 'ram_phy_dis_hw_set_freq',
 'rom1_phy_en_hw_set_freq' if c=='esp32c3' else 'ram_phy_en_hw_set_freq',
 'wr_rf_freq_mem','freq_i2c_write_set','rom2_pll_cap_mem_update' if c=='esp32c3' else 'pll_cap_mem_update',
 'get_rf_freq_init','freq_get_i2c_data','freq_i2c_data_write','set_chan_freq_hw_init','set_chan_freq_sw_start'])) for c in ('esp32c3','esp32s3')}
ARITY={0:0,1:0,2:0,3:2,4:9,5:1,6:0,7:9,8:0,9:2,10:3}
EXT_ARITY={0:1,1:1,2:4,3:0,4:4,5:0,6:3}
MMIO=[0x6000e000+o for o in (0xc0,0xc4,0xc8,0xcc,0xd0,0xd4,0xd8,0xdc,0xe0,0xe4,0xe8,0xec,0xf0,0xf4,0x100,0x104,0x108,0x10c,0x110,0x114,0x118,0x11c,0x120,0x124,0x128,0x12c,0x148,0x150,0x164,0x168,0x170)]+[0x6003509c]

def fields(chip):
    return [(0xf3,1),(0xde,2),(0xe2,2),(0x326 if chip=='esp32c3' else 0x2aa,2),(0x120,4),*[(0x158+i,1) for i in range(6)]]

def pointers(c):
    return [0x300000+(i*0x400 if c[28]==0 else 0 if c[28]==1 else i if c[28]==2 else (i%2)*0x400) for i in range(8)]

def initial_byte(c,array,index):
    return (c[27]+array*29+index*17 if c[40]==0 else c[27] if c[40]==2 else index if c[40]==3 else [1,99,3,0,0x9a,1,0x65,1][array])&255

class Oracle:
    def __init__(self,chip,e):
        require(chip in NAMES,'Unknown chip');self.chip,self.e=chip,e
        self.program,_=decode(e)
        require({f['name'] for f in e['functions']}==set(NAMES[chip].values()),'Unexpected function names')
        self.entries={k:next(int(f['address'],0) for f in e['functions'] if f['name']==n) for k,n in NAMES[chip].items()};self.kinds={v:k for k,v in self.entries.items()}
        self.param=int(e['symbols']['phy_param']['address'],0);self.extent=e['symbols']['phy_param']['size_bytes'];self.table=int(e['symbols']['g_phyFuns']['address'],0)
        require(self.extent==(848 if chip=='esp32c3' else 740),'Wrong parameter extent')
        names={0:'ets_delay_us',2:'set_rfpll_freq',3:'rom2_read_pll_cap' if chip=='esp32c3' else 'read_pll_cap',4:'rfpll_set_freq',5:'get_bias_ref_code',6:'correct_rfpll_offset'}
        if chip=='esp32c3':names[1]='rom2_write_pll_cap'
        self.externals={int(e['symbols'][n]['address'],0):k for k,n in names.items()}
        self.slots=({0x1ac:3,0x1b8:5,0x1bc:6,0x114:2,0x28:3} if chip=='esp32c3' else {0x188:3,0x194:5,0x198:6,0x100:2,0x28:3,0x20c:1})
        self.dispatch={int(t['dispatch_pc'],0):[int(v,0) for v in t['targets']] for t in e['jump_tables']}
        self.visited=set();self.branches=set();self.dispatch_edges=set()

    def run(self,c):
        require(len(c)==48 and all(0<=v<=MASK for v in c),'Invalid case words')
        require(c[0] in self.entries and c[28]<=3 and c[34]<=1 and c[40]<=3 and not any(c[41:]),'Invalid case domain')
        if self.chip=='esp32c3' and c[0] in (4,7):require(c[8]<=255,'C3 count exceeds bounded domain')
        s3=self.chip=='esp32s3';param=self.param;memory={};trace=[];bindings=[];contexts=[]
        generation=calls=mmreads=busyreads=chanreads=capreads=steps=0
        def event(kind,*args):
            require(len(args)<=11 and len(trace)<12*65536,'Trace budget exhausted')
            trace.extend([kind,*(a&MASK for a in args),*([0]*(11-len(args)))])
        def put(a,w,v):
            for i in range(w):memory[a+i]=(v>>(8*i))&255
        def get(a,w):
            require(all(a+i in memory for i in range(w)),f'Uninitialized memory {a:x}/{w}')
            return sum(memory[a+i]<<(8*i) for i in range(w))
        for o,w in fields(self.chip):put(param+o,w,0)
        for o,w,value in [(0x120,4,c[10]),(0xf3,1,c[11]),(0xde,2,c[12]),(0xe2,2,c[12]>>16),(0x2aa if s3 else 0x326,2,c[12])]:put(param+o,w,value)
        buffers=pointers(c)
        for array,address in enumerate(buffers):
            for i in range(256):put(address+i,1,initial_byte(c,array,i))
        for a in MMIO:put(a,4,c[25]^((a*0x1021)&MASK))
        constants={}
        for t in self.e['jump_tables']:
            for i,v in enumerate(bytes.fromhex(t['bytes'])):constants[int(t['address'],0)+i]=v
        def canonical(a):
            if param<=a<param+self.extent:return 0x200000+a-param
            if 0x300000<=a<0x302000:return a
            for base,width,target in reversed(bindings):
                if base<=a<base+width:return target+a-base
            raise ValueError(f'Unknown pointer {a:x}')
        def bind(a,width,target):
            if 0x100000<=a and a+width<=0x110000:
                require(not any(b==a and (w!=width or t!=target) for b,w,t in bindings),'Conflicting stack binding')
                if (a,width,target) not in bindings:bindings.append((a,width,target))
            else:canonical(a)
        def visible(a,w):
            return (param<=a and a+w<=param+self.extent or 0x300000<=a and a+w<=0x302000 or contexts and contexts[-1] in (3,4,7) and any(b<=a and a+w<=b+size for b,size,t in bindings))
        def mutate_buffers():
            for a in sorted({p+i for p in buffers for i in range(256)}):put(a,1,get(a,1)^((c[24]+(a-0x300000)*17)&255))
            for b,w,t in bindings:
                if t==0x310000:
                    for i in range(w):put(b+i,1,get(b+i,1)^((c[24]+i*17)&255))
        def read(a,w):
            nonlocal mmreads,busyreads,chanreads
            if a==self.table and w==4:event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=a<0x70400000 and w==4:
                active,slot=divmod(a-0x70000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback slot');event(5,slot,active);return 0x71000000+active*0x1000+slot
            if a in MMIO:
                require(w==4,'Wrong MMIO width')
                value=get(a,4)^((c[26]*mmreads)&MASK)
                if a==0x6000e168:
                    value=(value&0x7fffffff)|(((c[29]>>busyreads)&1)<<31) if busyreads<32 else value&0x7fffffff;busyreads+=1
                if a==0x6000e170:value=c[30+min(chanreads,2)];chanreads+=1
                event(7,a,value)
                if c[36]&(1<<(mmreads%32)):mutate_buffers()
                mmreads+=1;return value
            if a in constants:
                require(w==4 and all(a+i in constants for i in range(w)),'Wrong table read');return sum(constants[a+i]<<(8*i) for i in range(w))
            require(param<=a and a+w<=param+self.extent or 0x300000<=a and a+w<=0x302000 or 0x100000<=a and a+w<=0x110000,f'Unmapped read {a:x}/{w}')
            value=get(a,w)
            if visible(a,w):event(1,canonical(a),w,value)
            return value
        def write(a,w,v):
            v&=(1<<(8*w))-1
            if a in MMIO:require(w==4,'Wrong MMIO width');event(8,a,v);put(a,w,v);return
            require(param<=a and a+w<=param+self.extent or 0x300000<=a and a+w<=0x302000 or 0x100000<=a and a+w<=0x110000,f'Unmapped write {a:x}/{w}')
            if visible(a,w):event(2,canonical(a),w,v)
            put(a,w,v)
        def mutate():
            nonlocal calls,generation
            require(calls<4096,'Callback budget exhausted');mask=1<<(calls%32)
            if c[21]&mask:generation+=1
            if c[22]&mask:
                for o,w in fields(self.chip):put(param+o,w,get(param+o,w)^((c[24]+o*17)&((1<<(w*8))-1)))
            if c[23]&mask:mutate_buffers()
            calls+=1
        def clean_args(kind,v):
            clean=v.copy()
            if kind==3:
                bind(v[1],12,0x310010);clean[1]=canonical(v[1])
                for i in range(3):event(11,clean[1]+i*4,4,get(v[1]+i*4,4))
            elif kind in (4,7):
                count=(v[7]&255) if s3 else v[7];require(count<=255,'Nested count exceeds domain')
                for array,index in enumerate([0,1,2,3,4,5,6,8]):
                    bind(v[index],max(count,1),0x320000+array*0x400);clean[index]=canonical(v[index])
                    if kind==4:
                        for i in range(count):event(11,clean[index]+i,1,get(v[index]+i,1))
            return clean
        def registers(sp=0x10ff00):
            r={f'a{i}':0xabc00000+i*0x1001 for i in range(16)}
            r.update({f's{i}':0xddd00000+i*0x1001 for i in range(12)});r.update({f't{i}':0xeee00000+i*0x1001 for i in range(7)});r.update(sp=sp,ra=0,zero=0)
            if s3:r['a1']=sp
            return r
        def clobber(r,value):
            for key in ([f'a{i}' for i in range(8,16)] if s3 else [f'a{i}' for i in range(8)]+[f't{i}' for i in range(7)]):r[key]=0xdeadbeef
            r.pop('left_shift',None);r['a10' if s3 else 'a0']=value&MASK
        def execute(pc,r,kind,depth=0):
            nonlocal steps,capreads
            require(depth<12,'Call depth exhausted');contexts.append(kind);loop=None
            try:
                while True:
                    steps+=1;require(steps<=500000,'Instruction budget exhausted');require(pc in self.program,f'Unknown PC {pc:x}')
                    self.visited.add(pc);next_pc,op,args=self.program[pc]
                    if op=='entry':
                        require(s3 and args[0]=='a1' and int(args[1],0)%16==0,'Unexpected entry');r['a1']-=int(args[1],0)
                    elif op in ('li','movi','movi.n'):r[args[0]]=int(args[1],0)&MASK
                    elif op in ('mv','mov.n'):r[args[0]]=r[args[1]]
                    elif op=='lui':r[args[0]]=(int(args[1],0)<<12)&MASK
                    elif op=='auipc':r[args[0]]=(pc+(int(args[1],0)<<12))&MASK
                    elif op in ('addi','addi.n','addmi'):r[args[0]]=(r[args[1]]+int(args[2],0))&MASK
                    elif op in ('add','add.n','addx2','addx4','addx8','mul','sub','and','or','xor','div'):
                        left,right=r[args[1]],r[args[2]]
                        if op in ('add','add.n'):value=left+right
                        elif op.startswith('addx'):value=int(op[-1])*left+right
                        elif op=='mul':value=left*right
                        elif op=='sub':value=left-right
                        elif op=='and':value=left&right
                        elif op=='or':value=left|right
                        elif op=='xor':value=left^right
                        else:
                            left,right=signed(left),signed(right);value=MASK if right==0 else (abs(left)//abs(right))*(-1 if (left<0)!=(right<0) else 1)
                        r[args[0]]=value&MASK
                    elif op in ('andi','ori'):
                        value=int(args[2],0)&MASK;r[args[0]]=r[args[1]]&value if op=='andi' else r[args[1]]|value
                    elif op=='not':r[args[0]]=(~r[args[1]])&MASK
                    elif op in ('slli','srli','srai'):
                        value=r[args[1]];amount=int(args[2],0);r[args[0]]=((value<<amount) if op=='slli' else (signed(value)>>amount) if op=='srai' else value>>amount)&MASK
                    elif op=='ssl':require(s3,'Wrong shift ABI');r['left_shift']=r[args[0]]&31
                    elif op=='sll':
                        require(not s3 or 'left_shift' in r,'Missing shift state');amount=r['left_shift'] if s3 else r[args[2]]&31;r[args[0]]=(r[args[1]]<<amount)&MASK
                    elif op=='zext.b':r[args[0]]=r[args[1]]&255
                    elif op=='extui':r[args[0]]=(r[args[1]]>>int(args[2],0))&((1<<int(args[3],0))-1)
                    elif op=='sext':r[args[0]]=signed(r[args[1]],int(args[2],0)+1)&MASK
                    elif op=='movgez':
                        if signed(r[args[2]])>=0:r[args[0]]=r[args[1]]
                    elif op=='l32r':
                        literal=hex(int(args[1],16));require(literal in self.e['literals'],'Unknown literal');r[args[0]]=int(self.e['literals'][literal],0)
                    elif op in ('lw','lh','lhu','lbu','lb','sw','sh','sb'):
                        m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[1]);require(m is not None,'Bad memory operand');a=(r[m[2]]+int(m[1]))&MASK;w=4 if op in ('lw','sw') else 1 if op in ('lbu','lb','sb') else 2
                        if op in ('sw','sh','sb'):write(a,w,r[args[0]])
                        else:
                            value=read(a,w);r[args[0]]=(signed(value,w*8) if op in ('lb','lh') else value)&MASK
                    elif op in ('l32i','l32i.n','s32i','s32i.n','l8ui','s8i','l16si','l16ui','s16i'):
                        a=(r[args[1]]+int(args[2],0))&MASK;w=2 if '16' in op else 1 if op in ('l8ui','s8i') else 4
                        if op.startswith('s'):write(a,w,r[args[0]])
                        else:
                            value=read(a,w);r[args[0]]=(signed(value,16) if op=='l16si' else value)&MASK
                    elif op in CONDITIONAL:
                        left=r[args[0]]
                        if op in ('beqz','beqz.n'):take=left==0
                        elif op in ('bnez','bnez.n'):take=left!=0
                        elif op=='bltz':take=signed(left)<0
                        else:
                            right=int(args[1],0)&MASK if op in ('beqi','bnei') else r[args[1]]
                            if op in ('beq','beqi'):take=left==right
                            elif op in ('bne','bnei'):take=left!=right
                            elif op=='bltu':take=left<right
                            elif op=='bgeu':take=left>=right
                            else:raise ValueError('Unsupported conditional '+op)
                        self.branches.add((pc,take))
                        if take:next_pc=int(args[-1],16)
                    elif op=='loop':
                        require(s3 and 0<r[args[0]]<=255,'Unexpected loop count');loop=[next_pc,int(args[1],16),r[args[0]]]
                    elif op in ('jr','jx') and pc in self.dispatch:
                        target=r[args[0]];require(target in self.dispatch[pc],'Unknown dispatch destination');self.dispatch_edges.add((pc,target));next_pc=target
                    elif op=='j' and int(args[0],16) in self.program and int(args[0],16) not in self.kinds:next_pc=int(args[0],16)
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
                            return [r[f'a{i+10}'] if i<6 else get(r['a1']+(i-6)*4,4) for i in range(n)] if s3 else [r[f'a{i}'] if i<8 else get(r['sp']+(i-8)*4,4) for i in range(n)]
                        value=0
                        if target in self.kinds:
                            child_kind=self.kinds[target];v=values(ARITY[child_kind]);before=len(bindings);clean=clean_args(child_kind,v);event(9,child_kind,*clean)
                            if c[33]&(1<<child_kind):
                                if s3:
                                    child=registers(r['a1']);child.update({f'a{i+2}':value for i,value in enumerate(v[:6])})
                                else:child=r
                                execute(target,child,child_kind,depth+1)
                            else:
                                if child_kind==7:
                                    for array,index in enumerate([0,1,2,3,4,5,6,8]):
                                        for i in range(v[7]&255 if s3 else v[7]):put(v[index]+i,1,initial_byte(c,array,i))
                                mutate()
                            del bindings[before:]
                        elif target in self.externals:
                            ext=self.externals[target];v=values(EXT_ARITY[ext]);clean=v.copy()
                            if ext in (2,4):bind(v[3],3,0x310000);clean[3]=canonical(v[3])
                            if ext==6:clean[2]=canonical(v[2])
                            event(10,ext,*clean)
                            if ext in (2,4):
                                pattern=(c[20]+calls*c[39])&MASK
                                for i in range(3):put(v[3]+i,1,pattern>>(i*8))
                            if ext==6:put(v[2],2,c[38])
                            if ext==3:value=c[13+min(capreads,1)];capreads+=1
                            if ext==5:value=c[18]
                            mutate()
                        else:
                            require(0x71000000<=target<0x71400000,f'Unknown callback target {target:x}');active,slot=divmod(target-0x71000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback slot')
                            v=values(self.slots[slot]);clean=v.copy()
                            if slot==(0x100 if s3 else 0x114):clean[0]=canonical(v[0]);require(v[0]==param+0x158 and v[1]==6,'Unexpected clear span')
                            event(6,target,*clean)
                            if slot==0x28:value=c[35] if c[34] else min(max(signed(v[0]),signed(v[2])),signed(v[1]))&MASK
                            elif slot==(0x194 if s3 else 0x1b8):require(v==[98,1,6,3,0],'Unexpected mask read');value=c[15]
                            elif slot==(0x188 if s3 else 0x1ac):require(v in ([98,1,11],[99,1,0]),'Unexpected raw read');value=c[16] if v[0]==98 else c[17]
                            elif slot==(0x100 if s3 else 0x114):
                                for i in range(6):put(v[0]+i,1,c[37]>>(8*(i%4)))
                            mutate()
                        clobber(r,value)
                        if tail:return value
                    elif op=='memw':require(s3 and not args,'Unexpected memory barrier')
                    elif op in ('ret','retw.n'):require((op=='retw.n')==s3,'Wrong return ABI');return r['a2' if s3 else 'a0']
                    else:raise ValueError('Unknown instruction '+op)
                    if loop and next_pc==loop[1]:
                        loop[2]-=1
                        if loop[2]:next_pc=loop[0]
                        else:loop=None
                    r['zero']=0;pc=next_pc
            finally:contexts.pop()
        r=registers();a=c[1:10].copy()
        if c[0]==3:a[1]=buffers[0]
        if c[0] in (4,7):
            for i,index in enumerate([0,1,2,3,4,5,6,8]):a[index]=buffers[i]
        for i,value in enumerate(a[:ARITY[c[0]]]):
            if i<(6 if s3 else 8):r[f'a{i+(2 if s3 else 0)}']=value
            else:put(r['a1' if s3 else 'sp']+(i-(6 if s3 else 8))*4,4,value)
        execute(self.entries[c[0]],r,c[0])
        return 0,trace

def default_case(op):
    c=[0]*48;c[0]=op;c[1:4]=[1,1,3];c[8]=10;c[11]=1;c[12]=0x123400c8;c[13:20]=[200,240,7,0x87,0x76,0x12345678,0x87654321]
    c[20]=0x987654;c[24]=0x1357;c[25]=0x543210ff;c[27]=0x21;c[29]=3;c[30:33]=[1<<17,2<<17,3<<17];c[33]=0x7ff;c[35]=0x12345678;c[38]=0x7654;c[40]=1
    return c

def smoke_cases(chip):
    for op in NAMES[chip]:
        c=default_case(op);yield c
        for axis,values in [(1,(0,1,15,127,128,255,256,0x8000,MASK)),(2,(0,1,3,255,256,0x8000,MASK)),(3,(0,1,255,256,MASK)),(10,(0,32,MASK)),(13,(0,32767,32768,65535,MASK)),(14,(0,32767,32768,65535,MASK)),(15,(0,15,255,MASK)),(21,(1,MASK)),(22,(1,MASK)),(23,(1,MASK)),(26,(0x12345678,)),(28,(1,2,3)),(29,(0,0x55555555,MASK)),(33,(0,1<<3,1<<4,1<<6,1<<7,1<<8)),(34,(1,)),(35,(0,255,256,32768,MASK)),(36,(1,MASK)),(39,(0x11111,))]:
            for value in values:
                c=default_case(op);c[axis]=value;yield c
    for op in (4,7):
        for count in (0,1,2,7,8,9,10,15,16,17,18,19,20,24,31,32,33,64,127,255,*((256,257,0xffffffff) if chip=='esp32s3' else ())):
            for mode in (0,1,2,3):
                c=default_case(op);c[8]=count;c[40]=mode;yield c
        for seed in range(256):
            c=default_case(op);c[8]=24;c[40]=2;c[27]=seed;yield c
    for op in (6,9,10):
        for values in ((3<<17,2<<17,1<<17),(127<<17,127<<17,127<<17),(0,0,0)):
            c=default_case(op);c[30:33]=values;yield c

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('chip',choices=NAMES);p.add_argument('output',type=Path);a=p.parse_args()
    here=Path(__file__).resolve().parent;e=json.loads((here/'original-instructions.json').read_text())[a.chip];expected=json.loads((here/'expected-results.json').read_text())[a.chip]
    baseline=json.loads((here/'baselines.json').read_text())[a.chip]
    require(e['elf_sha256']==baseline['elf_sha256'] and e['map_sha256']==baseline['map_sha256'],'Baseline hashes differ')
    oracle=Oracle(a.chip,e);digest=hashlib.sha256();count=0
    with a.output.open('wb') as f:
        for c in smoke_cases(a.chip):
            _,trace=oracle.run(c);raw=struct.pack('<'+'I'*(49+len(trace)),*c,len(trace),*trace);f.write(raw);digest.update(raw);count+=1
    require(count==expected['cases'] and digest.hexdigest()==expected['case_stream_sha256'],'Case stream differs from reviewed result')
    require(oracle.visited==set(oracle.program),'Not every recorded instruction reached')
    branches={(pc,take) for pc,(_,op,_) in oracle.program.items() if op in CONDITIONAL for take in (False,True)}
    dispatch={(pc,target) for pc,targets in oracle.dispatch.items() for target in targets}
    require(oracle.branches==branches and oracle.dispatch_edges==dispatch,'Branch or dispatch coverage incomplete')
    require(len(oracle.visited)==expected['recorded_instructions'] and len(branches)==expected['conditional_edges'] and len(dispatch)==expected['dispatch_edges'],'Coverage counts differ')
    print(json.dumps({'chip':a.chip,**expected,'all_recorded_instructions_reached':True,'all_conditional_edges_reached':True,'all_dispatch_targets_reached':True}))
if __name__=='__main__':main()
