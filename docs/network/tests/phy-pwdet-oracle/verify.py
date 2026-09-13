#!/usr/bin/env python3
"""Execute pinned power-detector instructions with ordered memory/callback traces."""
import hashlib,json,re,struct,sys
from pathlib import Path
MASK=0xffffffff
SUPPORTED = {'auipc', 'addi', 'srli', 'sh', 'bnez', 'lhu', 'div', 's32i', 'call8', 'l16ui', 'mv', 'quos', 'ori', 'movi.n', 'sext', 's16i', 's32i.n', 'or', 'srai', 'jalr', 'addi.n', 'l32r', 'li', 'callx8', 'bltu', 'andi', 'divu', 'movi', 'slli', 'sw', 'bne', 'lh', 'add.n', 'ret', 'mov.n', 'extui', 'and', 'l16si', 'l32i', 'sub', 'zext.b', 'memw', 'add', 'jal', 'lw', 'retw.n', 'l32i.n', 'j', 'entry', 'quou', 'lui', 'bnei'}
CONDITIONAL = ("bltu","bne","bnez","bnei")

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
    require(len(starts) in (8,9) and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts


class BoundaryStop(Exception):
    def __init__(self,status):self.status=status

class Oracle:
    def __init__(self,chip,evidence):
        require(chip in ('esp32c3','esp32s3'),'Unknown chip')
        self.chip,self.e=chip,evidence
        self.program,self.starts=decode(evidence)
        names=['phy_set_pwdet_power','get_sar_sig_ref','pwdet_tone_start']
        if chip=='esp32c3':names+=['ram_pkdet_vol_start']
        names += [('rom1_read_sar2_code' if chip=='esp32c3' else 'ram_read_sar2_code'),'get_tone_sar_dout','get_fm_sar_dout','txtone_linear_pwr','get_power_db']
        require([f['name'] for f in evidence['functions']]==names,'Unexpected functions')
        operations=list(range(9)) if chip=='esp32c3' else [0,1,2,4,5,6,7,8]
        self.entries=dict(zip(operations,self.starts));self.kinds={v:k for k,v in self.entries.items()}
        self.param=int(evidence['symbols']['phy_param']['address'],0)
        require(evidence['symbols']['phy_param']['size_bytes']==(848 if chip=='esp32c3' else 740),'Unexpected parameter extent')
        self.table=int(evidence['symbols']['g_phyFuns']['address'],0)
        self.delay=int(evidence['symbols']['ets_delay_us']['address'],0)
        require(self.delay==(0x40000050 if chip=='esp32c3' else 0x40000600),'Unknown delay boundary')
        allowed={self.param,self.table,self.delay,0x60006040,0x40000,0x6000e050,0xfffbffff}
        require(all(int(v,0) in allowed for v in evidence['literals'].values()),'Unknown literal value')

    def run(self,c):
        require(len(c)==16 and all(0<=v<=MASK for v in c),'Invalid case words')
        require(c[0] in self.entries and all(c[i]<=65535 for i in (2,3,14,15)) and c[8]<32 and c[11]<16,'Invalid case domain')
        s3=self.chip=='esp32s3';operation=c[0]
        setup,output,conversion=(0x120,0x124,0x104) if s3 else (0x144,0x148,0x118)
        param=self.param;table=self.table
        memory={};trace=[];generation=0;calls=0;fills=0;converts=0;polls=0;steps=0
        mmio={a:c[12]^i*0x13579bdf for i,a in enumerate([0x60006040,0x6000e050,0x6000e05c])}
        limit=6000 if (operation==5 and not s3 and c[1]>255) else (96 if c[13]==0 else 100000)
        def event(kind,*args):
            require(len(args)<=7,'Oversized event')
            if len(trace)//8>=limit:raise BoundaryStop(2)
            trace.extend([kind,*(v&MASK for v in args),*([0]*(7-len(args)))])
        def put(address,width,value):
            for i in range(width):memory[address+i]=(value>>(8*i))&255
        def get(address,width):
            require(all(address+i in memory for i in range(width)),f'Uninitialized memory {address:x}/{width}')
            return sum(memory[address+i]<<(8*i) for i in range(width))
        put(param+0xda,2,c[2]);put(param+0xdc,2,c[3]);put(0x300000,4,0xa55aa55a)
        locations=[0x300000,0x300002,param+0xda,param+0xdc]
        signal,reference=locations[c[11]%4],locations[c[11]//4]
        def canonical(address):
            if param<=address<param+0x400:return 0x200000+address-param
            return address
        def read(address,width):
            nonlocal polls
            if address==table and width==4:
                event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=address<0x71000000 and width==4:
                active,offset=divmod(address-0x70000000,0x1000)
                require(active<=generation and offset in (setup,output,conversion),'Unknown callback slot')
                event(5,offset,active);return 0x71000000+active*0x1000+offset
            if address in mmio and width==4:
                value=mmio[address]&MASK
                if address==0x6000e050:
                    status=(c[13]>>(4*(polls%8)))&7;polls+=1
                    value=(value&~(7<<24))|(status<<24)
                event(7,address,value);return value
            if address in (param+0xda,param+0xdc) and width==2:
                value=get(address,width);event(1,address-param,value);return value
            if 0x100000<=address<0x120000 or address in (0x300000,0x300002):return get(address,width)
            raise ValueError(f'Unmapped read {address:x}/{width}')
        def write(address,width,value):
            value&=(1<<(8*width))-1
            if address in mmio and width==4:
                event(8,address,value);mmio[address]=value;return
            if address in (param+0xda,param+0xdc,0x300000,0x300002) and width==2:
                event(2,canonical(address),value);put(address,width,value);return
            require(0x100000<=address and address+width<=0x120000 and width in (2,4),'Non-stack store')
            put(address,width,value)
        def mutation():
            nonlocal generation,calls
            bit=1<<(calls%32)
            if c[9]&bit:generation+=1
            if c[10]&bit:
                put(param+0xda,2,get(param+0xda,2)^0x1357)
                put(param+0xdc,2,(get(param+0xdc,2)+0x2468)&65535)
            calls+=1
        def normalize_pointer(address,index):
            if 0x100000<=address<0x120000:return 0x600000+index*2
            return canonical(address)
        def direct(kind,args,invoke):
            if kind==2:event(9,kind)
            elif kind==5:event(9,kind,args[0])
            elif kind==1:event(9,kind,args[0],normalize_pointer(args[1],0),normalize_pointer(args[2],1))
            elif kind==6:event(9,kind,normalize_pointer(args[0],0),normalize_pointer(args[1],1))
            else:raise ValueError('Unexpected direct helper')
            bit={2:0,5:1,1:2,6:3}[kind]
            if c[8]&(1<<bit):return invoke()
            if kind==5:return c[4]
            if kind in (1,6):
                left,right=args[1:3] if kind==1 else args[:2]
                write(left,2,c[14]);write(right,2,c[15])
            return 0
        def opaque(target,args,regs,depth):
            nonlocal fills,converts
            if target==self.delay:
                event(11,args[0]);require(args[0] in (1,2,10),'Unknown delay argument');return 0xdeadbeef
            require(0x71000000<=target<0x72000000,'Unknown call target')
            active,offset=divmod(target-0x71000000,0x1000)
            require(active<=generation and offset in (setup,output,conversion),'Unknown callback target')
            if offset==setup:
                event(6,target)
                if not s3 and c[8]&16:invoke(self.entries[3],[],regs,depth)
                result=0xdeadbeef
            elif offset==output:
                require(args[0]%16==0 and 0x100000<=args[0] and args[0]+16<=0x120000,'Wrong output buffer alignment/range')
                event(6,target,0x600000)
                for i in range(8):
                    value=(c[4]+fills*c[5]+(i-1)*0x1357)&65535
                    event(10,i*2,value);put(args[0]+2*i,2,value)
                fills+=1;result=0xdeadbeef
            else:
                event(6,target,args[0],args[1]);require(args[1]==3,'Conversion selector')
                result=c[6] if converts%2==0 else c[7];converts+=1
            mutation();return result
        def new_registers():
            r={f'a{i}':(0xabc00000+i*0x1001)&MASK for i in range(16)}
            r.update({f's{i}':0xddd00000+i*0x1001 for i in range(12)})
            r.update({f't{i}':0xeee00000+i*0x1001 for i in range(7)})
            r.update(sp=0x110000,ra=0)
            r['a1']=0x110000 if s3 else r['a1']
            return r
        def clobber(regs,result):
            for key in ([f'a{i}' for i in range(8,16)] if s3 else [f'a{i}' for i in range(8)]+[f't{i}' for i in range(7)]):regs[key]=0xdeadbeef
            regs['a10' if s3 else 'a0']=result&MASK
        def invoke(target,args,parent,depth):
            if s3:
                child=new_registers();child['a1']=parent['a1']
                child.update({f'a{i+2}':v for i,v in enumerate(args[:6])})
                return execute(target,child,depth+1)
            return execute(target,parent,depth+1)
        def execute(pc,r,depth=0):
            nonlocal steps
            require(depth<12,'Call nesting exhausted')
            while True:
                steps+=1;require(steps<=1000000,'Instruction budget exhausted')
                require(pc in self.program,'Unknown branch target')
                next_pc,op,args=self.program[pc]
                if op=='entry':
                    require(s3 and args[0]=='a1' and int(args[1],0) in (32,48),'Unexpected entry')
                    r['a1']-=int(args[1],0)
                elif op in ('li','movi','movi.n'):r[args[0]]=int(args[1],0)&MASK
                elif op in ('mv','mov.n'):r[args[0]]=r[args[1]]
                elif op=='lui':r[args[0]]=(int(args[1],0)<<12)&MASK
                elif op=='auipc':r[args[0]]=(pc+(int(args[1],0)<<12))&MASK
                elif op in ('addi','addi.n'):r[args[0]]=(r[args[1]]+int(args[2],0))&MASK
                elif op in ('add','add.n','sub','or','and','div','divu','quos','quou'):
                    left,right=r[args[1]],r[args[2]]
                    if op in ('add','add.n'):value=left+right
                    elif op=='sub':value=left-right
                    elif op=='or':value=left|right
                    elif op=='and':value=left&right
                    elif op in ('divu','quou'):
                        if not right:
                            if op=='quou':raise BoundaryStop(1)
                            value=MASK
                        else:value=left//right
                    else:
                        require(right!=0,'Unexpected signed zero divisor')
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
                elif op=='l32r':
                    literal=hex(int(args[1],16));require(literal in self.e['literals'],'Unknown literal');r[args[0]]=int(self.e['literals'][literal],0)
                elif op in ('lw','lh','lhu','sw','sh'):
                    m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[1]);require(m is not None,'Bad memory operand')
                    address=(r[m[2]]+int(m[1]))&MASK;width=4 if op in ('lw','sw') else 2
                    if op in ('sw','sh'):write(address,width,r[args[0]])
                    else:
                        value=read(address,width);r[args[0]]=(signed(value,16) if op=='lh' else value)&MASK
                elif op in ('l32i','l32i.n','l16si','l16ui','s16i','s32i','s32i.n'):
                    address=(r[args[1]]+int(args[2],0))&MASK;width=2 if '16' in op else 4
                    if op.startswith('s'):write(address,width,r[args[0]])
                    else:
                        value=read(address,width);r[args[0]]=(signed(value,16) if op=='l16si' else value)&MASK
                elif op in CONDITIONAL:
                    if op=='bnez':take=r[args[0]]!=0
                    elif op=='bnei':take=r[args[0]]!=(int(args[1],0)&MASK)
                    elif op=='bltu':take=r[args[0]]<r[args[1]]
                    else:take=r[args[0]]!=r[args[1]]
                    if take:next_pc=int(args[-1],16)
                elif op=='j':next_pc=int(args[0],16)
                elif op in ('jal','jalr','call8','callx8'):
                    if op in ('jal','call8'):target=int(args[0],16)
                    elif '(' in args[0]:
                        m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[0]);require(m is not None,'Bad call operand');target=(r[m[2]]+int(m[1]))&MASK
                    else:target=r[args[0]]
                    if not s3:target&=~1;r['ra']=next_pc
                    values=[r[f'a{i+(10 if s3 else 0)}'] for i in range(6)]
                    if target in self.kinds:
                        kind=self.kinds[target]
                        result=direct(kind,values,lambda:invoke(target,values,r,depth))
                    else:result=opaque(target,values,r,depth)
                    clobber(r,result)
                elif op=='memw':require(s3 and not args,'Unexpected barrier')
                elif op in ('ret','retw.n'):
                    require((op=='retw.n')==s3,'Wrong return ABI');return r['a2' if s3 else 'a0']&MASK
                else:raise ValueError('Unknown instruction '+op)
                pc=next_pc
        registers=new_registers();args=[]
        if operation in (1,):args=[c[1],signal,reference]
        elif operation==6:args=[signal,reference]
        elif operation in (0,5,8):args=[c[1]]
        registers.update({f'a{i+(2 if s3 else 0)}':v for i,v in enumerate(args)})
        status=0;result=0
        try:
            result=execute(self.entries[operation],registers)
            if operation in (0,1,2,3):result=0
        except BoundaryStop as error:status=error.status;result=0
        return status,result,trace

def default_case(operation):
    return [operation,2,1000,3000,2000,7,1111,2222,31,0,0,4,0x13579bdf,0x77777777,1234,4321]

def cases(chip):
    edges=(0,1,2,39,40,49,50,255,256,1023,4095,8191,8192,32767,32768,65534,65535)
    operations=[0,1,2,4,5,6,7,8]+([3] if chip=='esp32c3' else [])
    for op in operations:
        for mode in range(32):
            for layout in range(16):
                c=default_case(op);c[8:12]=[mode,MASK,MASK,layout];yield c
    # Cover every 16-bit input on each reference axis. Other coordinates vary
    # across the boundary set; this does not enumerate the full Cartesian domain.
    for value in range(65536):
        for axis in (1,2,3):
            c=default_case(1);c[1:4]=[edges[(value+axis+i)%len(edges)] for i in range(3)]
            c[axis]=value;c[11]=value%16;yield c
    for baseline in edges:
        for calibration in edges:
            for delta in (-51,-50,-41,-40,-1,0,1,32767,32768,65535):
                for layout in range(16):
                    c=default_case(1);c[1:4]=[(baseline+delta)&MASK,baseline,calibration];c[11]=layout;yield c
    # Full callback sample halfword, full signed numerator halfword, full
    # offset halfword; mutation/opaque-call modes vary independently below.
    for value in range(65536):
        c=default_case(4);c[4]=value;c[8]=0;c[9]=value&3;c[10]=(value>>2)&3;yield c
        c=default_case(7);c[8]=0;c[14]=value;c[15]=edges[value%len(edges)];yield c
        c=default_case(8);c[8]=0;c[1]=value;c[6]=(value*0x10203041)&MASK;c[7]=MASK^c[6];c[9]=value&3;yield c
    for value in (0,1,2,0x7fffffff,0x80000000,0xfffffffe,MASK):
        for second in (0,1,0x7fffffff,0x80000000,MASK):
            for mode in range(32):
                for mutation in (0,1,2,3,0x55555555,0xaaaaaaaa,MASK):
                    c=default_case(8);c[1]=value;c[6]=value;c[7]=second;c[8:11]=mode,mutation,mutation;yield c
    for count in range(256):
        for seed in (0,65535):
            c=default_case(5);c[1]=count;c[4]=seed;c[8]=0;c[9]=0xaaaaaaaa;yield c
    for count in (0,1,2,3,127,255,256,257,0x10000,0x10001,MASK):
        for mode in (0,31):
            c=default_case(5);c[1]=count;c[8]=mode;c[9]=MASK;c[10]=MASK;yield c
    for op in operations:
        for mode in (0,31):
            for mutation in range(256):
                c=default_case(op);c[8:11]=mode,mutation,mutation^0xa5;yield c
    for op in [2,4,5,6,7,8]+([3] if chip=='esp32c3' else []):
        for mode in (0,31):
            for pattern in (0,0x77777777,0x70000000,0x76543210,0x07000000,0x00070000):
                for seed in (0,MASK,0x13579bdf):
                    c=default_case(op);c[8]=mode;c[12:14]=seed,pattern;yield c

def stream(chip,output):
    data=json.loads(Path(__file__).with_name('original-instructions.json').read_text())
    oracle=Oracle(chip,data[chip]);digest=hashlib.sha256();count=0;coverage=[0]*9;statuses=[0]*3
    for c in cases(chip):
        status,result,trace=oracle.run(c);require(len(trace)%8==0,'Invalid trace shape')
        words=c+[status,result,len(trace)//8]+trace
        packed=struct.pack('<'+'I'*len(words),*words);output.write(packed);digest.update(packed)
        count+=1;coverage[c[0]]+=1;statuses[status]+=1
    require(all(coverage[i] for i in oracle.entries),'Uncovered function')
    return {'cases':count,'operations':coverage,'statuses':statuses,'case_stream_sha256':digest.hexdigest(),
            'fixture_sha256':hashlib.sha256(json.dumps(data[chip],sort_keys=True).encode()).hexdigest()}

def main():
    require(len(sys.argv)==3,'Usage: verify.py esp32c3|esp32s3 output.bin')
    chip=sys.argv[1];require(chip in ('esp32c3','esp32s3'),'Unknown chip')
    with Path(sys.argv[2]).open('wb') as out:result=stream(chip,out)
    expected=json.loads(Path(__file__).with_name('expected-results.json').read_text())[chip]
    require(result==expected,'Oracle results differ from reviewed fixture')
    print(json.dumps({chip:result}))
if __name__=='__main__':main()
