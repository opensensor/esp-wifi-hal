#!/usr/bin/env python3
"""Execute pinned register-programming instructions with ordered state and callback traces."""
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
CONDITIONAL += ('bgeu', 'bgei', 'bltui', 'bgeui', 'bgtz', 'blez')
SUPPORTED |= {'neg','mulsh','mull','sltiu','seqz','sltu','slt','bgei','bltui','bgeui','bgtz','blez','srl','sra','xori','subx2','subx4','subx8','mulhu','mulh','movsp','max','min','sltz','movltz','ssr'}
SUPPORTED |= {'bbci','bnone','rem','remu','divu','muluh','minu'}
CONDITIONAL += ('bbci','bnone')
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
            if op in ('ret', 'retw.n', 'jr', 'jx'):
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
    require(len(starts) == 5 and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts

NAMES={'esp32c3': {0: 'gen_rx_gain_table', 1: 'wr_rx_gain_mem', 2: 'set_rx_gain_param', 3: 'set_rx_gain_table', 4: 'phy_rx_table_init'}, 'esp32s3': {0: 'gen_rx_gain_table', 1: 'wr_rx_gain_mem', 2: 'set_rx_gain_param', 3: 'set_rx_gain_table', 4: 'phy_rx_table_init'}}
ARITY={0:7,1:8,2:6,3:2,4:0}
MMIO=[0x60006110,0x6000607c,0x6001c02c,0x6001c13c,0x6001c0d0,0x60011848,0x6001c0a4]
LOCAL_OFFSETS=[0,12,24,40,56,72,88,288]

class Oracle:
    def __init__(self,chip,e):
        self.chip,self.e=chip,e;self.program,starts=decode(e)
        require([f['name'] for f in e['functions']]==list(NAMES[chip].values()),'Function names differ')
        self.entries=dict(enumerate(starts));self.kinds={v:k for k,v in self.entries.items()}
        self.param=int(e['symbols']['phy_param']['address'],0);self.extent=e['symbols']['phy_param']['size_bytes']
        self.table=int(e['symbols']['g_phyFuns']['address'],0)
        require(self.extent==(740 if chip=='esp32s3' else 848),'Parameter extent differs')
        self.helpers={int(s['address'],0):n for n,s in e['symbols'].items()}
        self.slots=({0x2c:3,4:0,0x248:0,0x1b0:0,0x1b4:0,0x1ac:2,0x1a8:3,0x1c0:1} if chip=='esp32s3' else {0x2c:3,4:0,0x1d4:0,0x1d8:0,0x1d0:2,0x1cc:3,0x1e4:1})
        self.visited=set();self.branches=set()
        self.constants={}
        for row in e['readonly']:
            data=bytes.fromhex(row['bytes']);require(len(data)==row['size_bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'],'Readonly hash differs')
            for i,v in enumerate(data):self.constants[int(row['address'],0)+i]=v
        self.log_addresses={int(row['address'],0):i for i,row in enumerate(e['logs'])}

    def run(self,c):
        require(len(c)==32 and all(0<=v<=MASK for v in c),'Invalid case words')
        require(c[0] in self.entries,'Unknown function')
        s3=self.chip=='esp32s3';param=self.param;memory={};trace=[];locals=[]
        generation=calls=mmreads=mmwrites=steps=0
        root=self.e['readonly'][0];data=bytes.fromhex(root['bytes'])
        def event(k,*args):
            require(len(args)<=15 and len(trace)<16*65536,'Trace budget exhausted')
            trace.extend([k,*(a&MASK for a in args),*([0]*(15-len(args)))])
        def put(a,w,v):
            for i in range(w):memory[a+i]=(v>>(8*i))&255
        def canonical(a):
            if param<=a<param+self.extent:return 0x200000+a-param
            for start,size,dest in locals:
                if start<=a<start+size:return dest+a-start
            return a
        def mapped(a,w):
            a=canonical(a)
            return 0x200000<=a and a+w<=0x200000+self.extent or any(base<=a and a+w<=base+size for base,size in [(0x300000,512),(0x310000,256),(0x320000,256),(0x330000,256),(0x340000,1024),(0x350000,16),(0x360000,262144),(0x500000,512)])
        for i in range(self.extent):put(param+i,1,(c[9]+i*17)&255)
        for o,w,v in [(0x120,4,c[17]),(0x1f2,1,c[18]),(0x1f5,1,c[25]),(0x1f6,1,c[26]),(0x348 if not s3 else 0x2da,1,c[19]),(0x218,1,c[29]),(0xa2,1,c[30]),(0x34c if not s3 else 0x2da,1,c[31])]:
            if o+w<=self.extent:put(param+o,w,v)
        for i in range(256):
            code=(data[(25 if s3 else 32)+i%9]+c[23])&255
            step=data[(10 if s3 else 0)+i%15];start=data[(58 if s3 else 16)+i%15]
            if c[21]==1:step=1;start=0
            if c[21]==2:step=0;start=0
            if c[21]==3:step=255;start=4
            if c[21]==4:step=20;start=0
            put(0x310000+i,1,code);put(0x320000+i,1,step);put(0x330000+i,1,start)
        for i in range(128):put(0x300000+i*4,4,(c[22]+i*0x01010001)&MASK)
        for a in MMIO:put(a,4,c[9]^((a*0x1021)&MASK))
        def get(a,w):
            if all(a+i in memory for i in range(w)):return sum(memory[a+i]<<(8*i) for i in range(w))
            if all(a+i in self.constants for i in range(w)):return sum(self.constants[a+i]<<(8*i) for i in range(w))
            if any(base<=a and a+w<=base+size for base,size in [(0x340000,1024),(0x350000,16),(0x360000,262144)]):
                return sum(((c[9]+(a+i)*17)&255)<<(8*i) for i in range(w))
            raise ValueError(f'Uninitialized read {a:x}/{w}')
        def change_state():
            # Change all parameter bytes except pointer-domain/count fields; each
            # effect is deterministic and reflected in subsequent loads.
            for o in (0x120,0x150,0x152,0xf3,0x1f5,0x1f6,0xd4):
                w=4 if o in (0x120,0xd4) else 2 if o in (0x150,0x152) else 1
                put(param+o,w,get(param+o,w)^((c[24]+o*17)&((1<<(8*w))-1)))
        def mutate():
            nonlocal generation,calls
            mask=1<<(calls%32)
            if c[13]&mask:generation+=1
            if c[14]&mask:change_state()
            calls+=1
        def read(a,w):
            nonlocal mmreads
            if a==self.table and w==4:event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=a<0x70400000 and w==4:
                active,slot=divmod(a-0x70000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback slot');event(5,slot,active);return 0x71000000+active*0x1000+slot
            if a in MMIO:
                require(w==4,'Wrong MMIO width');v=get(a,w)^((c[11]*mmreads)&MASK);event(7,a,v)
                if c[10]&(1<<(mmreads%32)):change_state()
                mmreads+=1;return v
            value=get(a,w)
            if mapped(a,w):event(1,canonical(a),w,value)
            else:require(0x100000<=a and a+w<=0x110000 or all(a+i in self.constants for i in range(w)),f'Unmapped read {a:x}/{w}')
            return value
        def write(a,w,v):
            nonlocal mmwrites
            v&=(1<<(w*8))-1
            if a in MMIO:
                require(w==4,'Wrong MMIO width');event(8,a,v);put(a,w,v)
                if c[12]&(1<<(mmwrites%32)):change_state()
                mmwrites+=1;return
            if mapped(a,w):event(2,canonical(a),w,v)
            else:require(0x100000<=a and a+w<=0x110000,f'Unmapped write {a:x}/{w}')
            put(a,w,v)
        def bind(a,size,destination):
            require(not any(max(a,start)<min(a+size,start+n) for start,n,_ in locals),'Overlapping local arrays')
            locals.append((a,size,destination))
        copies=0;generators=0
        def dispatch(t,values,r,depth):
            nonlocal copies,generators
            if t in self.kinds:
                kind=self.kinds[t];a=values(ARITY[kind]);require(kind in (0,1,2),'Unexpected child kind')
                if kind==0:
                    bind(a[0],200,0x500000+(88 if generators==0 else 288));generators+=1
                observed=a.copy()
                if kind==2:
                    for unused in (1,3,4):observed[unused]=0
                event(9,kind,*(canonical(v) for v in observed))
                if c[20]&(1<<kind):
                    child=registers(r['a1'] if s3 else r['sp'])
                    for i,v in enumerate(a):
                        if i<(6 if s3 else 8):child[f'a{i+(2 if s3 else 0)}']=v
                        else:put(child['a1']+(i-6)*4,4,v)
                    return execute(t,child,kind,depth+1)
                value=c[27] if kind==0 else 0;mutate();return value
            name=self.helpers.get(t)
            if name=='memcpy':
                dest,source,n=values(3);require(n in (9,10,15),'Unexpected constant copy length')
                require(all(source+i in self.constants for i in range(n)),'Copy outside pinned readonly input')
                for i in range(n):put(dest+i,1,self.constants[source+i])
                if c[0]==3 and depth==0:
                    require(copies<6,'Too many table copies');bind(dest,n,0x500000+LOCAL_OFFSETS[copies]);copies+=1
                return dest
            if name=='phy_printf':
                addr=values(1)[0];require(addr in self.log_addresses,'Unknown format');kind=self.log_addresses[addr]
                a=values(9 if kind==0 else 2)[1:];event(11,kind,*a);mutate();return 0
            if name in ('set_rx_gain_cal_iq','set_rx_gain_cal_dc','set_rf_freq_offset','rom_phy_reg_init'):
                kind={'set_rx_gain_cal_iq':0,'set_rx_gain_cal_dc':1,'set_rf_freq_offset':2,'rom_phy_reg_init':3}[name]
                a=values([4,10 if s3 else 8,3,0][kind]);event(10,kind,*(canonical(v) for v in a));mutate();return 0
            require(0x71000000<=t<0x71400000,f'Unknown call {t:x}/{name}')
            active,slot=divmod(t-0x71000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback')
            a=values(self.slots[slot]);v=(c[15]+calls*c[16])&MASK if self.slots[slot]==2 else 0
            event(6,t,*a,v);mutate();return v
        def registers(sp=0x10ff00):
            r={f'a{i}':0xabc00000+i*0x1001 for i in range(16)}
            r.update({f's{i}':0xddd00000+i*0x1001 for i in range(12)});r.update({f't{i}':0xeee00000+i*0x1001 for i in range(7)});r.update(sp=sp,ra=0,zero=0)
            if s3:r['a1']=sp
            return r
        def clobber(r,value):
            for key in ([f'a{i}' for i in range(8,16)] if s3 else [f'a{i}' for i in range(8)]+[f't{i}' for i in range(7)]):r[key]=0xdeadbeef
            r.pop('left_shift',None);r.pop('right_shift',None);r['a10' if s3 else 'a0']=value&MASK
        def execute(pc,r,kind,depth=0):
            nonlocal steps
            require(depth<12,'Call depth exhausted');loop=None
            try:
                while True:
                    steps+=1;require(steps<=500000,'Instruction budget exhausted');require(pc in self.program,f'Unknown PC {pc:x}')
                    self.visited.add(pc);next_pc,op,args=self.program[pc]
                    if op=='entry':
                        require(s3 and args[0]=='a1' and int(args[1],0)%16==0,'Unexpected entry');r['a1']-=int(args[1],0)
                    elif op in ('li','movi','movi.n'):r[args[0]]=int(args[1],0)&MASK
                    elif op in ('mv','mov.n','movsp'):r[args[0]]=r[args[1]]
                    elif op in ('seqz','snez','sltz','neg'):r[args[0]]=(int(r[args[1]]==0) if op=='seqz' else int(r[args[1]]!=0) if op=='snez' else int(signed(r[args[1]])<0) if op=='sltz' else -r[args[1]])&MASK
                    elif op=='sltiu':r[args[0]]=int(r[args[1]]<(int(args[2],0)&MASK))
                    elif op=='lui':r[args[0]]=(int(args[1],0)<<12)&MASK
                    elif op=='auipc':r[args[0]]=(pc+(int(args[1],0)<<12))&MASK
                    elif op in ('addi','addi.n','addmi'):r[args[0]]=(r[args[1]]+int(args[2],0))&MASK
                    elif op in ('add','add.n','addx2','addx4','addx8','mul','sub','and','or','xor','div','mull','mulsh','sltu','slt','subx2','subx4','subx8','mulhu','mulh','max','min','rem','remu','divu','muluh','minu'):
                        left,right=r[args[1]],r[args[2]]
                        if op in ('add','add.n'):value=left+right
                        elif op.startswith('addx'):value=int(op[-1])*left+right
                        elif op in ('mul','mull'):value=left*right
                        elif op in ('mulsh','mulh'):value=(signed(left)*signed(right))>>32
                        elif op=='sub':value=left-right
                        elif op=='and':value=left&right
                        elif op=='or':value=left|right
                        elif op=='xor':value=left^right
                        elif op=='sltu':value=int(left<right)
                        elif op=='slt':value=int(signed(left)<signed(right))
                        elif op.startswith('subx'):value=int(op[-1])*left-right
                        elif op in ('mulhu','muluh'):value=(left*right)>>32
                        elif op=='minu':value=min(left,right)
                        elif op=='divu':value=MASK if right==0 else left//right
                        elif op=='remu':value=left if right==0 else left%right
                        elif op=='rem':
                            left,right=signed(left),signed(right);q=0 if right==0 else (abs(left)//abs(right))*(-1 if (left<0)!=(right<0) else 1);value=left-q*right
                        elif op=='max':value=max(signed(left),signed(right))
                        elif op=='min':value=min(signed(left),signed(right))
                        else:
                            left,right=signed(left),signed(right);value=MASK if right==0 else (abs(left)//abs(right))*(-1 if (left<0)!=(right<0) else 1)
                        r[args[0]]=value&MASK
                    elif op in ('andi','ori'):
                        value=int(args[2],0)&MASK;r[args[0]]=r[args[1]]&value if op=='andi' else r[args[1]]|value
                    elif op in ('moveqz','movnez'):
                        if (r[args[2]]==0)==(op=='moveqz'):r[args[0]]=r[args[1]]
                    elif op=='not':r[args[0]]=(~r[args[1]])&MASK
                    elif op in ('slli','srli','srai'):
                        value=r[args[1]];amount=int(args[2],0);r[args[0]]=((value<<amount) if op=='slli' else (signed(value)>>amount) if op=='srai' else value>>amount)&MASK
                    elif op=='xori':r[args[0]]=(r[args[1]]^int(args[2],0))&MASK
                    elif op=='ssr':require(s3,'Wrong shift ABI');r['right_shift']=r[args[0]]&31
                    elif op in ('srl','sra'):
                        amount=r['right_shift'] if s3 else r[args[2]]&31;r[args[0]]=((signed(r[args[1]]) if op=='sra' else r[args[1]])>>amount)&MASK
                    elif op=='ssl':require(s3,'Wrong shift ABI');r['left_shift']=r[args[0]]&31
                    elif op=='sll':
                        require(not s3 or 'left_shift' in r,'Missing shift state');amount=r['left_shift'] if s3 else r[args[2]]&31;r[args[0]]=(r[args[1]]<<amount)&MASK
                    elif op=='zext.b':r[args[0]]=r[args[1]]&255
                    elif op=='extui':r[args[0]]=(r[args[1]]>>int(args[2],0))&((1<<int(args[3],0))-1)
                    elif op=='sext':r[args[0]]=signed(r[args[1]],int(args[2],0)+1)&MASK
                    elif op in ('movgez','movltz'):
                        if (signed(r[args[2]])>=0)==(op=='movgez'):r[args[0]]=r[args[1]]
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
                        elif op=='bgez':take=signed(left)>=0
                        elif op=='bgtz':take=signed(left)>0
                        elif op=='blez':take=signed(left)<=0
                        elif op in ('bbsi','bbci'):take=bool(left&(1<<int(args[1],0)))==(op=='bbsi')
                        elif op=='bnone':take=(left&r[args[1]])==0
                        else:
                            right=int(args[1],0)&MASK if op in ('beqi','bnei','blti','bgei','bltui','bgeui') else r[args[1]]
                            if op in ('beq','beqi'):take=left==right
                            elif op in ('bne','bnei'):take=left!=right
                            elif op in ('bltu','bltui'):take=left<right
                            elif op in ('blt','blti'):take=signed(left)<signed(right)
                            elif op in ('bge','bgei'):take=signed(left)>=signed(right)
                            elif op in ('bgeu','bgeui'):take=left>=right
                            else:raise ValueError('Unsupported conditional '+op)
                        self.branches.add((pc,take))
                        if take:next_pc=int(args[-1],16)
                    elif op=='loop':
                        require(s3 and 0<r[args[0]]<=255,'Unexpected loop count');loop=[next_pc,int(args[1],16),r[args[0]]]
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
                        value=dispatch(target,values,r,depth)
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
            finally:pass
        r=registers();a=arguments(c)
        for i,v in enumerate(a):
            if i<(6 if s3 else 8):r[f'a{i+(2 if s3 else 0)}']=v
            else:put(r['a1']+(i-6)*4,4,v)
        result=execute(self.entries[c[0]],r,c[0])
        return (result if c[0]==0 else 0),trace

def arguments(c):
    return {0:[0x300000,c[2],0x310000,0x320000,0x330000,c[6],c[7]],1:[c[1],c[2],0x310000,0x340000,0x350000,0x360000,c[7],0x300000],2:[c[1],c[2],0x310000,c[4],c[5],c[6]],3:[c[1],c[2]],4:[]}[c[0]]

def default_case(op):
    c=[0]*32;c[0]=op;c[1]=1;c[2]=22 if op==0 else 0;c[6]=9;c[7]=0 if op==0 else 79
    c[9]=0x543210ff;c[15]=0x1025;c[16]=0x123;c[18]=3;c[20]=7;c[22]=0xa001a000;c[24]=0x1357;c[25]=76;c[26]=79;c[27]=17
    return c

def smoke_cases(chip):
    for op in NAMES[chip]:
        yield default_case(op)
        axes=[(9,(0,1,0x12345678,MASK)),(13,(1,2,4,MASK)),(15,(0,1,2,65535,65536,0x80000000,MASK)),(16,(0,1,MASK))]
        if op in (2,3,4):axes += [(10,(1,2,4,MASK)),(11,(1,0x12345,MASK)),(12,(1,2,4,MASK)),(14,(1,2,4,MASK)),(17,(0,512,1024,1536,MASK)),(24,(0,1,MASK))]
        if op in (1,2):axes += [(1,(0,1,2,255,256,257,MASK))]
        if op==2:axes += [(6,(0,1,255,256,257,MASK))]
        if op==3:axes += [(1,(0,1,65535,65536,65537,MASK)),(2,tuple(range(9))),(19,(0,249,250,251,127,128,255)),(25,(0,1,75,76,77,79,82,255)),(26,(0,1,75,76,77,79,82,255)),(29,(0,1,2,255)),(30,(0,17,255)),(31,(0,1,255))]
        for axis,values in axes:
            for value in values:
                c=default_case(op);c[axis]=value
                # State churn around a full table rebuild cannot make the
                # caller-owned table shorter than its resulting count.
                if op==3 and axis in (10,12,14,25,26):c[17]|=512
                yield c
    # Generator byte-domain and finite table families, including index-limit exit.
    for family in range(5):
        for maximum in (0,1,5,6,7,22,25,28):
            for count in (1,2,5,7,9,127,255):
                for logging in (0,1,256,257):
                    # Some families reach gain 30 before an index-limit exit at
                    # maximum 28 only if corrupted; the fixed fixtures stay <=29.
                    c=default_case(0);c[21]=family;c[2]=maximum;c[6]=count;c[7]=logging;yield c
    for maximum in (255,256,257,MASK):
        c=default_case(0);c[21]=1;c[6]=255;c[2]=maximum;c[7]=1;yield c
    for mode in (0,1,256,257):
        for alternate in (0,1,256,257):
            for count in (0,1,2,54,55,63,64,65,76,79,80):
                for word in (0,0xffff,0xffff0000,MASK,0x00800080,0x00f800f8,0xa001a000):
                    c=default_case(1);c[1]=mode;c[2]=alternate;c[7]=count;c[22]=word;yield c
    for signed_index in (0,1,2,3,127,128,255):
        c=default_case(1);c[1]=0;c[18]=signed_index;yield c
    for ret in (0,76,79,82,83,85,255,256,MASK):
        c=default_case(3);c[20]=0;c[27]=ret;yield c

def write_cases(chip,e,output):
    o=Oracle(chip,e);digest=hashlib.sha256();count=0
    with output.open('wb') as f:
        for c in smoke_cases(chip):
            result,trace=o.run(c);raw=struct.pack('<'+'I'*(34+len(trace)),*c,result,len(trace),*trace)
            f.write(raw);digest.update(raw);count+=1
    edges={(pc,take) for pc,(_,op,_) in o.program.items() if op in CONDITIONAL for take in (False,True)}
    require(o.visited==set(o.program),'Unreached instruction')
    require(o.branches==edges,'Unreached conditional edge')
    return {'cases':count,'case_stream_sha256':digest.hexdigest(),'recorded_instructions':len(o.visited),'conditional_edges':len(edges)}

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('chip',choices=NAMES);p.add_argument('output',type=Path);a=p.parse_args()
    here=Path(__file__).resolve().parent;raw=(here/'original-instructions.json').read_bytes()
    base=json.loads((here/'baselines.json').read_text())[a.chip];e=json.loads(raw)[a.chip]
    require(hashlib.sha256(raw).hexdigest()==base['fixture_sha256'],'Fixture hash differs')
    require(e['elf_sha256']==base['elf_sha256'] and e['map_sha256']==base['map_sha256'],'Baseline differs')
    result=write_cases(a.chip,e,a.output)
    require(result==json.loads((here/'expected-results.json').read_text())[a.chip],'Case stream or coverage differs')
    print(json.dumps({'chip':a.chip,**result}))
if __name__=='__main__':main()
