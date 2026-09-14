#!/usr/bin/env python3
"""Execute pinned transmit-gain instructions with ordered state and callback traces."""
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
    require(len(starts) in (11, 14) and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts

NAMES={'esp32c3': {0: 'rom1_wifi_tx_dig_gain', 1: 'bt_chan_pwr_interp', 2: 'rom1_get_rate_fcc_index', 3: 'rom1_get_chan_target_power', 4: 'rom2_get_tx_gain_value1', 5: 'rom1_bt_get_tx_gain_new', 6: 'rom1_wifi_get_tx_gain', 7: 'ram1_wifi_set_tx_gain', 8: 'rom1_bt_set_tx_gain', 9: 'bt_tx_gain_init', 10: 'txcal_gain_check'}, 'esp32s3': {0: 'ram_wifi_tx_dig_gain', 1: 'bt_chan_pwr_interp', 2: 'ram_get_rate_fcc_index', 3: 'ram_get_chan_target_power', 4: 'get_tx_gain_value', 5: 'ram_bt_get_tx_gain', 6: 'ram_wifi_get_tx_gain', 7: 'ram_wifi_set_tx_gain', 8: 'ram_bt_set_tx_gain', 9: 'bt_tx_gain_init', 10: 'tx_gain_set', 11: 'dig_gain_check', 12: '__opensensor_reg_digital_gain', 13: '__opensensor_basic_interpolate'}}
ARITY={0:1,1:2,2:4,3:7,4:8,5:11,6:13,7:2,8:1,9:0,10:0,11:2,12:1,13:2}
MMIO=[0x60006024,0x60006028,0x6000602c,0x60006030]
LOCAL_BASE=0x500000

def arguments(c,chip):
    x,y,z=0x310000,0x310010,0x310020
    out=0x310000
    if c[8]==1:out=0x300000;x=0x320000;y=0x330000;z=0x340000
    elif c[8]==2:out=0x300002;x=y=z=0x310000
    elif c[8]==3:out=0x320002;x=0x340002;y=0x340004;z=0x340006
    return {
        0:[0x300000],1:[0x300000,c[1]],2:[c[1],out,0x320000,0x330000],
        3:[c[1],c[2],out,0x300000,c[3],0x320000,0x330000],
        4:([c[3],c[4],c[1],x,y,z,0x320000,0x330000,0x340000,c[2],c[5]] if chip=='esp32s3' else [c[1],x,y,z,0x320000,0x330000,0x340000,c[2]]),
        5:[0x300000,c[1],c[2],0x320000,0x330000,0x340000,out,0x310040,c[35],c[34],c[4]],
        6:[c[1],0x350000,0x300000,c[2],c[3],0x320000,0x330000,0x340000,out,0x310040,0x310080,0x360000,c[4]],
        7:[c[1],c[4]],8:[c[4]],9:[],10:[],11:[0x300000,0x300000 if c[8] else 0x310000],12:[0x300000],13:[0x300000,c[1]],
    }[c[0]]

class Oracle:
    def __init__(self,chip,e):
        self.chip,self.e=chip,e;self.program,starts=decode(e)
        require([f['name'] for f in e['functions']]==list(NAMES[chip].values()),'Function names differ')
        self.entries=dict(enumerate(starts));self.kinds={v:k for k,v in self.entries.items()}
        self.param=int(e['symbols']['phy_param']['address'],0);self.extent=e['symbols']['phy_param']['size_bytes']
        self.global_address=int(e['symbols']['chip7_phy_init_ctrl']['address'],0)
        self.table=int(e['symbols']['g_phyFuns']['address'],0)
        require(self.extent==(740 if chip=='esp32s3' else 848),'Parameter extent differs')
        self.helpers={int(s['address'],0):n for n,s in e['symbols'].items()}
        self.slots=({0x28:3,0xfc:2,0xdc:1,0xe0:1,0x228:13,0x210:6,0x224:1,0x218:11,0x214:1,0x270:1} if chip=='esp32s3' else {0x28:3,0x110:2,0x128:4})
        self.returns={0x28,0xfc,0xdc,0xe0} if chip=='esp32s3' else {0x28,0x110}
        self.visited=set();self.branches=set();self.constants={}
        for row in e['readonly']:
            data=bytes.fromhex(row['bytes']);require(len(data)==row['size_bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'],'Readonly hash differs')
            for i,v in enumerate(data):self.constants[int(row['address'],0)+i]=v
        self.log_addresses={int(row['address'],0):i for i,row in enumerate(e['logs'])}
        for row in e['logs']:
            data=bytes.fromhex(row['bytes']);require(hashlib.sha256(data).hexdigest()==row['sha256'] and data==row['format'].encode()+b'\0','Log format differs')

    def run(self,c):
        require(len(c)==48 and all(0<=v<=MASK for v in c),'Invalid case words')
        require(c[0] in self.entries,'Unknown function')
        s3=self.chip=='esp32s3';param=self.param;memory={};trace=[];locals=[]
        generation=calls=reads=writes=steps=0
        def event(k,*args):
            require(len(args)<=15 and len(trace)<16*65536,'Trace budget exhausted')
            trace.extend([k,*(a&MASK for a in args),*([0]*(15-len(args)))])
        def put(a,w,v):
            for i in range(w):memory[(a+i)&MASK]=(v>>(8*i))&255
        def canonical(a):
            a&=MASK
            if param<=a<param+self.extent:return 0x200000+a-param
            if self.global_address<=a<self.global_address+42:return 0x280000+a-self.global_address
            for start,size,dest in reversed(locals):
                if start<=a<start+size:return dest+a-start
            return a
        def observed(a,w):
            a=canonical(a)
            return (0x200000<=a and a+w<=0x200000+self.extent) or (0x280000<=a and a+w<=0x28002a) or any(b-512<=a and a+w<=b+2048 for b in (0x300000,0x310000,0x320000,0x330000,0x340000,0x350000,0x360000))
        for i in range(self.extent):put(param+i,1,c[9]+i*17)
        for i in range(42):put(self.global_address+i,1,c[6]+i*7)
        for b in (0x300000,0x310000,0x320000,0x330000,0x340000,0x350000,0x360000):
            for i in range(-512,2048):put(b+i,1,c[6]+i*17)
        for i in range(256):
            threshold=(c[37]-i*(1 if c[7]==1 else 8))&65535
            if c[7]==2:threshold=c[37]&65535
            if c[7]==3:threshold=(i*8-c[37])&65535
            if c[7]==4:threshold=(c[37]+(i%3)*16-i*8)&65535
            put(0x340000+i*2,2,threshold)
            put(0x330000+i*2,2,c[26]+i*11)
            put(0x320000+i,1,c[25]+i*13)
        for i in range(18):
            put(param+14+i,1,c[25]+i*13);put(param+32+i*2,2,c[26]+i*11);put(param+68+i*2,2,c[37]-i*8)
        for i in range(14):put(param+0x68+i,1,c[25]+i*7);put(param+0x76+i*2,2,c[37]-i*8)
        for o,v in [(0x99,c[17]),(0x104,c[18]),(0x98,c[19]),(0x217,c[21]),(0x20d,c[22]),(0x2c8,c[23]),(0x2c9,c[33]),(0x1fb,c[31]),(0x1fc,c[31]),(0x9a,c[32]),(0x175,c[33]),(0x17c,c[33])]:
            if o<self.extent:put(param+o,1,v)
        for i in range(3):
            v=(c[38]>>(8*i))&255;put(0x300000+i,1,v);put(0x350000+i,1,v)
        if c[0]==11:put(0x300000,2,c[1]);put(0x310000,2,c[2])
        for a in MMIO:put(a,4,c[9]^a)
        def get(a,w):
            if all(a+i in memory for i in range(w)):return sum(memory[a+i]<<(8*i) for i in range(w))
            if all(a+i in self.constants for i in range(w)):return sum(self.constants[a+i]<<(8*i) for i in range(w))
            raise ValueError(f'Uninitialized read {a:x}/{w}')
        def change_state():
            for o in (0x217,0x98,0x1fb,0x9a,0x175,0x1fc,0x17c,0x2c9):
                if o<self.extent:put(param+o,1,get(param+o,1)^((c[24]+o*17)&255))
        def mutate():
            nonlocal generation,calls
            mask=1<<(calls%32)
            if c[13]&mask:generation+=1
            if c[14]&mask:change_state()
            calls+=1
        def read(a,w):
            nonlocal reads
            if a==self.table and w==4:event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=a<0x70400000 and w==4:
                active,slot=divmod(a-0x70000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback slot');event(5,slot,active);return 0x71000000+active*0x1000+slot
            value=get(a,w)
            if a in MMIO:require(w==4,'Wrong MMIO width');event(7,a,value)
            elif observed(a,w):event(1,canonical(a),w,value)
            else:require(0x100000<=a and a+w<=0x110000 or all(a+i in self.constants for i in range(w)),f'Unmapped read {a:x}/{w}')
            if observed(a,w) or a in MMIO:
                if c[10]&(1<<(reads%32)):change_state()
                reads+=1
            return value
        def write(a,w,v):
            nonlocal writes
            v&=(1<<(w*8))-1
            if a in MMIO:require(w==4,'Wrong MMIO width');event(8,a,v)
            elif observed(a,w):event(2,canonical(a),w,v)
            else:require(0x100000<=a and a+w<=0x110000,f'Unmapped write {a:x}/{w}')
            put(a,w,v)
            if observed(a,w) or a in MMIO:
                if c[12]&(1<<(writes%32)):change_state()
                writes+=1
        def bind(a,size,destination):
            locals.append((a,size,destination))
        def enter(kind,sp):
            if kind==0:bind(sp,14,LOCAL_BASE)
            elif kind==3:bind(sp+(0 if s3 else 12),4,LOCAL_BASE+0x1000)
            elif kind in (5,6):
                base=LOCAL_BASE+(0x2000 if kind==5 else 0x3000)
                if s3:
                    bind(sp+(36 if kind==5 else 38),1,base);bind(sp+32,2,base+4);bind(sp+(34 if kind==5 else 36),2,base+8)
                    if kind==6:bind(sp+34,2,base+12)
                else:bind(sp+43,1,base);bind(sp+46,2,base+4);bind(sp+44,2,base+8)
            elif kind==7:
                if not s3:bind(sp+48,14,LOCAL_BASE+0x4000)
                bind(sp+32,14,LOCAL_BASE+0x4020)
        def child(kind,a,r,depth):
            require(kind in self.entries,'Unknown child kind')
            observed_args=list(a)
            if kind==6:observed_args[11]=0 # Original body never consumes this argument.
            event(9,kind,*(canonical(v) for v in observed_args))
            if c[20]&(1<<kind):
                regs=registers(r['a1'] if s3 else r['sp'])
                for i,v in enumerate(a):
                    if i<(6 if s3 else 8):regs[f'a{i+(2 if s3 else 0)}']=v
                    else:put((regs['a1'] if s3 else regs['sp'])+(i-(6 if s3 else 8))*4,4,v)
                result=execute(self.entries[kind],regs,kind,depth+1)
                return result if kind in (1,13) or s3 and kind==4 else 0
            if kind==4:
                ptrs=a[3:6] if s3 else a[1:4]
                for p,w,v in zip(ptrs,(1,2,2),c[25:28]):write(p,w,v)
                value=c[28] if s3 else 0
            elif kind==2:
                for i in range(4):write(a[1]+i,1,c[25]+i*c[16])
                value=0
            elif kind==3:
                for i in range(14):write(a[2]+i,1,c[25]+i*c[16])
                value=0
            elif kind==11:write(a[0],2,c[26]);write(a[1],2,c[27]);value=0
            elif kind in (1,13):value=c[15]
            else:value=0
            mutate();return value
        def dispatch(t,values,r,depth):
            if t in self.kinds:
                kind=self.kinds[t];return child(kind,values(11 if s3 and kind==4 else ARITY[kind]),r,depth)
            name=self.helpers.get(t)
            if name in ('memcpy','memset'):
                d,v,n=values(3);require(n<=256,'Copy extent')
                if name=='memcpy':require(all(v+i in self.constants for i in range(n)),'Copy outside readonly');data=[self.constants[v+i] for i in range(n)]
                else:data=[v&255]*n
                for i,b in enumerate(data):put(d+i,1,b)
                return d
            if name=='phy_printf':
                address=values(1)[0];require(address in self.log_addresses,'Unknown format');kind=self.log_addresses[address]
                event(11,kind,*values(7 if kind==0 else 8)[1:]);mutate();return 0
            ext={'rom_set_tx_gain_mem':(0,6),'rom_bt_tx_dig_gain':(1,1),'bt_txdc_cal':(2,0),'bt_txiq_cal':(3,0),'bt_tx_pwctrl_init':(4,0),'bt_txpwr_freq':(5,1)}
            if name in ext:
                k,n=ext[name];event(10,k,*(canonical(v) for v in values(n)));mutate();return 0
            require(0x71000000<=t<0x71400000,f'Unknown call {t:x}/{name}')
            active,slot=divmod(t-0x71000000,0x1000);require(active<=generation and slot in self.slots,'Unknown callback')
            a=values(self.slots[slot]);observed_args=list(a)
            if slot==0x228 and s3:observed_args[11]=0
            event(6,t,*(canonical(v) for v in observed_args))
            routing=({0xfc:13,0x228:6,0x224:0,0x218:5,0x270:8} if s3 else {0x128:2})
            if slot in routing and c[39]&(1<<routing[slot]):v=child(routing[slot],a,r,depth)
            elif slot==0x128 and not s3:
                for i in range(4):write(a[1]+i,1,c[25]+i*c[16])
                v=0
            elif slot in self.returns:v=((c[36] if s3 and slot==0xdc else c[15])+calls*c[16])&MASK
            else:v=0
            mutate();event(14,t,v);return v
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
                        require(s3 and args[0]=='a1' and int(args[1],0)%16==0,'Unexpected entry');r['a1']-=int(args[1],0);enter(kind,r['a1'])
                    elif op in ('li','movi','movi.n'):r[args[0]]=int(args[1],0)&MASK
                    elif op in ('mv','mov.n','movsp'):r[args[0]]=r[args[1]]
                    elif op in ('seqz','snez','sltz','neg'):r[args[0]]=(int(r[args[1]]==0) if op=='seqz' else int(r[args[1]]!=0) if op=='snez' else int(signed(r[args[1]])<0) if op=='sltz' else -r[args[1]])&MASK
                    elif op=='sltiu':r[args[0]]=int(r[args[1]]<(int(args[2],0)&MASK))
                    elif op=='lui':r[args[0]]=(int(args[1],0)<<12)&MASK
                    elif op=='auipc':r[args[0]]=(pc+(int(args[1],0)<<12))&MASK
                    elif op in ('addi','addi.n','addmi'):
                        r[args[0]]=(r[args[1]]+int(args[2],0))&MASK
                        if not s3 and args[0]=='sp' and int(args[2],0)<0:enter(kind,r['sp'])
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
        r=registers();a=arguments(c,self.chip)
        for i,v in enumerate(a):
            if i<(6 if s3 else 8):r[f'a{i+(2 if s3 else 0)}']=v
            else:put((r['a1'] if s3 else r['sp'])+(i-(6 if s3 else 8))*4,4,v)
        result=execute(self.entries[c[0]],r,c[0])
        return (result if c[0] in (1,13) or s3 and c[0]==4 else 0),trace

def default_case(op):
    c=[0]*48;c[0]=op;c[1]=1;c[2]=18 if op==4 else 0;c[3]=1 if op==3 else 0
    if op==3:c[2]=60
    c[6]=33;c[9]=0x543210ff;c[15]=2;c[18]=1;c[19]=70;c[20]=0xffff;c[24]=0x1357
    c[25]=17;c[26]=0x102;c[27]=12;c[28]=3;c[31]=60;c[32]=16;c[33]=8;c[34]=3;c[35]=(-96)&MASK
    c[36]=1;c[37]=72;c[38]=0x281800;c[39]=0xffff
    return c

def smoke_cases(chip):
    for op in NAMES[chip]:
        yield default_case(op)
        axes=[(6,(0,1,127,128,255)),(9,(0,MASK)),(13,(1,2,4,MASK)),(14,(1,2,4,MASK)),(10,(1,2,4,MASK)),(12,(1,2,4,MASK)),(15,(0,1,3,4,24,80,127,128,255,65535,0x80000000,MASK)),(16,(0,1,MASK))]
        if op in (2,3,4,5,6,11):axes.append((8,(1,2,3)))
        if op in (1,2,3,6,7,13):axes.append((1,(0,1,2,3,6,11,12,13,14,25,37,38,255,256,257,MASK)))
        if op in (0,1,13):axes.append((38,(0,0xffffff,0x7f0080,0x807f00,0x7f807f,0x0100ff)))
        if op in (3,5,6):axes.append((2,(0,24,64,127,128,255,256,257,65535,MASK)))
        if op==3:axes.extend([(3,(0,1,2,255,256,257,MASK)),(21,(0,1,127,128,255))])
        if op in (5,6,7,8):axes.append((4,(0,1,255,256,257,MASK)))
        if op in (5,6):axes.extend([(20,(0xffff^(1<<4),0xffff^(1<<11))),(27,(0,24,25,127,128,255,65535,0x8000,0xffaf)),(37,(0,127,128,32767,32768,65535)),(7,(0,1,2,3,4))])
        if op==5:axes.extend([(34,(0,1,127,128,255,256,257)),(35,(0,1,127,128,255,256,257))])
        if op in (7,8,9):axes.extend([(17,(0,1,2,255)),(18,(0,1,2,255)),(19,(0,127,128,255)),(23,(0,1,2,255)),(31,(0,127,128,255)),(32,(0,127,128,255)),(33,(0,127,128,255)),(39,(0,1<<0,1<<2,1<<5,1<<6,1<<8,1<<13))])
        if op==10:axes.append((22,(0,1,2,255)))
        if op==11:axes.extend([(1,(0,1,255,65535,65536,MASK)),(2,(0,1,7,8,9,16,24,25,127,128,255,256,257,MASK)),(36,(0,1,2,3,4,255,256,MASK))])
        if op==4:
            axes.extend([(1,(0,1,24,80,127,128,255,32767,32768,65535,65536,0x80000000,MASK)),(2,(0,1,2,14,18,127,255)),(3,(0,1,13,17,127,255)),(4,(0,1,127,128,32767,32768,65535,MASK)),(5,(0,1,127,128,255,256,257,MASK)),(7,(0,1,2,3,4))])
        for axis,values in axes:
            for value in values:
                c=default_case(op);c[axis]=value
                if op==7 and axis==1 and not 1<=value<=14:
                    c[20]&=~(1<<2);c[39]&=~(1<<2)
                yield c
    if chip=='esp32s3':
        for index in (0,1,2,3):
            for gain in (0,1,7,8,16,24,31,32,33,127,128,255):
                c=default_case(11);c[36]=index;c[2]=gain;yield c
    # Joint lookup boundaries exercise both directions and neighboring thresholds.
    for initial in (0,1,6,13,17):
        for target in (-200,-97,-96,-81,-80,-65,-64,-8,-1,0,1,7,8,23,24,25,64,72,80,127):
            for adjustment in (-128,-8,0,24,127):
                c=default_case(4);c[1]=target&MASK;c[3]=initial;c[4]=adjustment&MASK;c[5]=(-8)&MASK;yield c
    for first in (0,1,127,128,255):
        for middle in (0,1,127,128,255):
            for channel in (0,1,11,12,13,36,37,38,79,255):
                c=default_case(1);c[1]=channel;c[38]=first|(middle<<8)|((255-first)<<16);yield c

def write_cases(chip,e,output):
    o=Oracle(chip,e);digest=hashlib.sha256();count=0
    with output.open('wb') as f:
        for c in smoke_cases(chip):
            try:result,trace=o.run(c)
            except Exception as ex:raise RuntimeError(f'Case {count} {c}') from ex
            raw=struct.pack('<'+'I'*(50+len(trace)),*c,result,len(trace),*trace)
            f.write(raw);digest.update(raw);count+=1
    edges={(pc,take) for pc,(_,op,_) in o.program.items() if op in CONDITIONAL for take in (False,True)}
    missing_instructions=sorted(set(o.program)-o.visited);missing_edges=sorted(edges-o.branches)
    require(not missing_instructions,'Unreached instructions '+repr([hex(v) for v in missing_instructions]))
    require(not missing_edges,'Unreached conditional edges '+repr([(hex(v),b) for v,b in missing_edges]))
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
