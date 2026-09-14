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
    require(len(starts) == 16 and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts

NAMES={'esp32c3': {0: 'ram1_set_pbus_reg', 1: 'rom1_tx_paon_set', 2: 'btbb_wifi_bb_cfg2', 3: 'rx_agc_reg_opt', 4: 'rx_11b_opt', 5: 'rom1_disable_wifi_agc', 6: 'rom1_enable_wifi_agc', 7: 'ram1_fe_i2c_reg_renew', 8: 'phy_wifi_enable_set', 9: 'txiq_set_reg', 10: 'rxiq_set_reg', 11: 'start_tx_tone_step', 12: 'stop_tx_tone', 13: 'rom1_set_noise_floor', 14: 'phy_freq_correct', 15: 'force_txrx_off'}, 'esp32s3': {0: 'ram_set_pbus_reg', 1: 'ram_wifi_tx_dig_gain_reg', 2: 'btbb_wifi_bb_cfg2', 3: 'rx_agc_reg_opt', 4: 'rx_11b_opt', 5: 'ram_disable_wifi_agc', 6: 'ram_enable_wifi_agc', 7: 'ram_fe_i2c_reg_renew', 8: 'phy_wifi_enable_set', 9: 'txiq_set_reg', 10: 'rxiq_set_reg', 11: 'start_tx_tone_step', 12: 'stop_tx_tone', 13: 'ram_set_noise_floor', 14: 'phy_freq_correct', 15: 'force_txrx_off'}}
ARITY={0:0,1:0,2:0,3:0,4:1,5:0,6:0,7:0,8:1,9:2,10:2,11:6,12:1,13:0,14:2,15:1}
MMIO=[0x60006000+o for o in (0,0x24,0x28,0x2c,0x30,0x40,0x44,0x4c,0x50,0x64,0x68,0x70,0x7c,0x90,0xe0,0xe4,0xe8,0xec,0xf0,0xf4,0xf8,0xfc,0x110,0x1e4)]+[0x6000e048,0x6000e058,0x6000e060]+[0x6001c000+o for o in (0x1c,0x34,0x44,0x5c,0x68,0x80,0x94,0xa4,0x104,0x124,0x134,0x13c,0x1b0,0x400,0x804,0x850,0xc98)]+[0x6001d000,0x6001d030,0x6001d06c,0x6002600c,0x60026010]

def fields(chip):
    return [(0x2ac+i*4 if chip=='esp32s3' else 0x328+i*4,4) for i in range(6)]+([(0x2a1,1)] if chip=='esp32s3' else [(0x1f5,1),(0x1f6,1),(0x31d,1),(0x31e,1)])

class Oracle:
    def __init__(self,chip,e):
        require(chip in NAMES,'Unknown chip');self.chip,self.e=chip,e
        self.program,_=decode(e)
        require({f['name'] for f in e['functions']}==set(NAMES[chip].values()),'Unexpected function names')
        self.entries={k:next(int(f['address'],0) for f in e['functions'] if f['name']==n) for k,n in NAMES[chip].items()};self.kinds={v:k for k,v in self.entries.items()}
        self.param=int(e['symbols']['phy_param']['address'],0);self.extent=e['symbols']['phy_param']['size_bytes'];self.table=int(e['symbols']['g_phyFuns']['address'],0)
        require(self.extent==(848 if chip=='esp32c3' else 740),'Wrong parameter extent')
        self.delay=int(e['symbols']['ets_delay_us']['address'],0)
        self.slots={0x190 if chip=='esp32s3' else 0x1b4:4}
        self.visited=set();self.branches=set()

    def run(self,c):
        require(len(c)==32 and all(0<=v<=MASK for v in c),'Invalid case words')
        require(c[0] in self.entries and c[16]<4 and not any(c[22:]),'Invalid case domain')
        s3=self.chip=='esp32s3';param=self.param;memory={};trace=[]
        generation=calls=mmreads=mmwrites=steps=0
        buffer=0x300000+c[16]
        def event(kind,*args):
            require(len(args)<=7 and len(trace)<8*65536,'Trace budget exhausted')
            trace.extend([kind,*(a&MASK for a in args),*([0]*(7-len(args)))])
        def put(a,w,v):
            for i in range(w):memory[a+i]=(v>>(8*i))&255
        def get(a,w):
            require(all(a+i in memory for i in range(w)),f'Uninitialized memory {a:x}/{w}')
            return sum(memory[a+i]<<(8*i) for i in range(w))
        for o,w in fields(self.chip):put(param+o,w,(c[17]+o*0x1021)&MASK)
        if not s3:
            put(param+0x1f6,1,c[18]);put(param+0x1f5,1,c[19]);put(param+0x31d,1,c[20]);put(param+0x31e,1,c[21])
        else:put(param+0x2a1,1,c[20])
        for i in range(14):put(buffer+i,1,c[17]+i*17)
        for a in MMIO:put(a,4,c[7]^((a*0x1021)&MASK))
        def canonical(a):return 0x200000+a-param if param<=a<param+self.extent else a
        def change_state():
            for o,w in fields(self.chip):put(param+o,w,get(param+o,w)^((c[11]+o*17)&((1<<(8*w))-1)))
            for i in range(14):put(buffer+i,1,get(buffer+i,1)^((c[11]+i*17)&255))
        def mutate():
            nonlocal generation,calls
            mask=1<<(calls%32)
            if c[12]&mask:generation+=1
            if c[13]&mask:change_state()
            if c[14]&mask:
                for a in MMIO:put(a,4,get(a,4)^((c[11]+a*17)&MASK))
            calls+=1
        def read(a,w):
            nonlocal mmreads
            if a==self.table and w==4:event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=a<0x70400000 and w==4:
                active,slot=divmod(a-0x70000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback slot');event(5,slot,active);return 0x71000000+active*0x1000+slot
            if a in MMIO:
                require(w==4,'Wrong MMIO width');value=get(a,4)^((c[8]*mmreads)&MASK);event(7,a,value)
                if c[10]&(1<<(mmreads%32)):change_state()
                mmreads+=1;return value
            require(param<=a and a+w<=param+self.extent or buffer<=a and a+w<=buffer+14 or 0x100000<=a and a+w<=0x110000,f'Unmapped read {a:x}/{w}')
            value=get(a,w)
            if not 0x100000<=a<0x110000:event(1,canonical(a),w,value)
            return value
        def write(a,w,v):
            nonlocal mmwrites
            v&=(1<<(8*w))-1
            if a in MMIO:
                require(w==4,'Wrong MMIO width');event(8,a,v);put(a,w,v)
                if c[9]&(1<<(mmwrites%32)):change_state()
                mmwrites+=1;return
            require(0x100000<=a and a+w<=0x110000,f'Unexpected non-stack write {a:x}/{w}');put(a,w,v)
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
                    elif op in ('add','add.n','addx2','addx4','addx8','mul','sub','and','or','xor','div','mull','mulsh','sltu','slt','subx2','subx4','subx8','mulhu','mulh','max','min'):
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
                        elif op=='mulhu':value=(left*right)>>32
                        elif op=='max':value=max(signed(left),signed(right))
                        elif op=='min':value=min(signed(left),signed(right))
                        else:
                            left,right=signed(left),signed(right);value=MASK if right==0 else (abs(left)//abs(right))*(-1 if (left<0)!=(right<0) else 1)
                        r[args[0]]=value&MASK
                    elif op in ('andi','ori'):
                        value=int(args[2],0)&MASK;r[args[0]]=r[args[1]]&value if op=='andi' else r[args[1]]|value
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
                        elif op=='bbsi':take=bool(left&(1<<int(args[1],0)))
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
                        value=0
                        if target in self.kinds:
                            child_kind=self.kinds[target];require(child_kind in (2,3),'Unexpected internal call');event(9,child_kind)
                            if c[15]&(1<<child_kind):
                                child=registers(r['a1']) if s3 else r
                                execute(target,child,child_kind,depth+1)
                            else:mutate()
                        elif target==self.delay:
                            v=values(1);require(v==[1],'Unexpected delay');event(10,0,*v);mutate()
                        else:
                            require(0x71000000<=target<0x71400000,f'Unknown callback target {target:x}');active,slot=divmod(target-0x71000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback slot')
                            v=values(4);require(v[:2]==[102,0] and v[2] in (4,5),'Unexpected raw I2C arguments');event(6,target,*v);mutate()
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
        r=registers();a=c[1:7].copy();arity=ARITY[c[0]]
        if s3 and c[0]==1:a[0]=buffer;arity=1
        for i,value in enumerate(a[:arity]):r[f'a{i+(2 if s3 else 0)}']=value
        result=execute(self.entries[c[0]],r,c[0])
        return (result if c[0] in (9,10) else 0),trace

def default_case(op):
    c=[0]*32;c[0]=op;c[1:7]=[1,1,3,1,7,5];c[7]=0x543210ff;c[11]=0x1357;c[15]=12;c[17]=0x29;c[18:22]=[7,5,0x63,0x79]
    return c

def smoke_cases(chip):
    for op in NAMES[chip]:
        yield default_case(op)
        for axis,values in [(1,(0,1,2,3,15,31,127,128,255,256,257,32768,0x80000000,MASK)),(2,(0,1,255,256,257,MASK)),(7,(0,MASK,0x20000000,0x12345678)),(8,(1,0x12345678,MASK)),(9,(1,2,4,MASK)),(10,(1,2,4,MASK)),(12,(1,MASK)),(13,(1,MASK)),(14,(1,MASK)),(15,(0,4,8)),(16,(1,2,3)),(17,(0,127,128,255)),(18,(0,1,2,3,4,5,127,128,255)),(19,(0,255))]:
            for value in values:
                c=default_case(op);c[axis]=value;yield c
    # All signed byte coefficients, clamp/halving boundaries and raw input widths.
    for op in (9,10):
        for value in [*(v&MASK for v in range(-128,256)),0x7fffffff,0x80000000,0x80000001,0xffff7fff]:
            for mode in (0,1,256,257):
                c=default_case(op);c[1]=value;c[2]=mode;yield c
    for offset in [-32769,-32768,-32767,-1281,-1280,-1279,-254,-253,-252,-251,-1,0,1,251,252,253,254,1279,1280,1281,32767,32768,32769,0x3fffffff,0x40000000,0x7fffffff,0x80000000,0x80000001,0xffffffff]:
        for mode in (0,1,256,257):
            c=default_case(14);c[1]=mode;c[2]=offset&MASK;yield c
    for en0,en1 in [(0,0),(0,1),(1,0),(1,1),(256,0),(0,256),(255,255),(MASK,MASK)]:
        for bit in (0,1):
            for freq in [-32769,-32768,-5,-4,-3,-2,-1,0,1,2,3,4,32767,32768,0x7fffffff,0x80000000,MASK]:
                c=default_case(11);c[1:7]=[en0,freq&MASK,(freq+128)&MASK,en1,(-freq)&MASK,(freq+255)&MASK];c[7]=(c[7]&~(1<<29))|((bit^bool((0x60006040*0x1021)&(1<<29)))<<29);yield c

def write_cases(chip,e,output):
    oracle=Oracle(chip,e);digest=hashlib.sha256();count=0
    with output.open('wb') as f:
        for c in smoke_cases(chip):
            result,trace=oracle.run(c);raw=struct.pack('<'+'I'*(34+len(trace)),*c,result,len(trace),*trace);f.write(raw);digest.update(raw);count+=1
    branches={(pc,take) for pc,(_,op,_) in oracle.program.items() if op in CONDITIONAL for take in (False,True)}
    require(oracle.visited==set(oracle.program),f'Unreached instructions {sorted(set(oracle.program)-oracle.visited)}')
    require(oracle.branches==branches,f'Unreached conditional edges {sorted(branches-oracle.branches)}')
    return {'cases':count,'case_stream_sha256':digest.hexdigest(),'recorded_instructions':len(oracle.visited),'conditional_edges':len(branches)}

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('chip',choices=NAMES);p.add_argument('output',type=Path);a=p.parse_args()
    here=Path(__file__).resolve().parent;raw=(here/'original-instructions.json').read_bytes();e=json.loads(raw)[a.chip];baseline=json.loads((here/'baselines.json').read_text())[a.chip]
    require(hashlib.sha256(raw).hexdigest()==baseline['fixture_sha256'],'Fixture hash differs')
    require(e['elf_sha256']==baseline['elf_sha256'] and e['map_sha256']==baseline['map_sha256'],'Baseline hashes differ')
    result=write_cases(a.chip,e,a.output);expected=json.loads((here/'expected-results.json').read_text())[a.chip]
    require(result==expected,'Case stream or coverage differs from reviewed result');print(json.dumps({'chip':a.chip,**result}))
if __name__=='__main__':main()
