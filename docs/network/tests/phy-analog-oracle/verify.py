#!/usr/bin/env python3
"""Execute pinned RC measurement/calibration instructions at their observable boundaries."""
import hashlib,json,math,re,struct,sys
from pathlib import Path
MASK=0xffffffff
SUPPORTED = {'l32i.n', 'jal', 'l32r', 'beqz', 'l16ui', 's8i', 'mul', 's32i', 'l16si', 'addx8', 'sext', 'callx8', 'sw', 'lbu', 'and', 'lw', 'retw.n', 'auipc', 'call8', 'lui', 'mulsh', 'ret', 'extui', 'lh', 'loop', 'or', 'bltu', 'l32i', 'zext.b', 'sb', 'bnez', 'addx4', 'add.n', 'div', 'addi.n', 'entry', 'movi.n', 'quos', 'sub', 'sh', 'addmi', 'addi', 'jalr', 'beqi', 'moveqz', 'movi', 'li', 'bge', 'add', 'lhu', 'l8ui', 'slli', 'srai', 'bne', 'mv', 'blt', 's16i', 'bltz', 'mov.n', 'j', 'bgei'}
CONDITIONAL = ('bltu','bltz','beqz','bnez','beqi','bge','blt','bne','bgei')

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
            if op in CONDITIONAL or op == 'loop':
                pending.append(int(args[-1], 16))
            pending.append(next_pc)
        require(reached == {a for a in program if start <= a < start+size}, 'Unreachable fixture instruction')
    require(len(starts) == 2 and len(set(starts)) == len(starts), 'Unexpected function count')
    return program, starts



def float_bits(value):return struct.unpack('<Q',struct.pack('<d',value))[0]
def bits_float(value):return struct.unpack('<d',struct.pack('<Q',value))[0]

class Oracle:
    def __init__(self,chip,evidence):
        require(chip in ('esp32c3','esp32s3'),'Unknown chip')
        self.chip,self.e=chip,evidence
        self.program,self.starts=decode(evidence)
        require([f['name'] for f in evidence['functions']]==['get_rc_dout','rc_cal'],'Unexpected functions')
        self.param=int(evidence['symbols']['phy_param']['address'],0)
        self.table=int(evidence['symbols']['g_phyFuns']['address'],0)
        self.delay=int(evidence['symbols']['ets_delay_us']['address'],0)
        self.soft={int(evidence['symbols'][name]['address'],0):i for i,name in enumerate(['__floatsidf','__divdf3','__subdf3','__fixdfsi'])}
        self.constants={}
        for entry in evidence['owned_inputs']:
            if 'bytes' in entry:
                address=int(entry['address'],0)
                for i,b in enumerate(bytes.fromhex(entry['bytes'])):self.constants[address+i]=b
        for entry in evidence['referenced_double_constants']:
            if 'address' in entry:
                for i,b in enumerate(bytes.fromhex(entry['bytes'])):self.constants[int(entry['address'],0)+i]=b
        self.globals=[int(e['address'],0) for e in evidence['owned_data_symbols']]
        require(len(self.globals)==(2 if chip=='esp32c3' else 0),'Unexpected owned data')
        require([x['name'] for x in evidence['owned_data_symbols']]==(['wifi_ht20','wifi_ht40'] if chip=='esp32c3' else []),'Unexpected data names')

    def run(self,c):
        require(len(c)==16 and all(0<=v<=MASK for v in c),'Invalid case words')
        require(c[0]<2 and c[4]<256 and c[5]<65536 and c[6]<65536 and c[7]<1024 and c[8]<1024 and c[9]<2 and c[10]<2 and c[12]<128 and c[15]<128,'Invalid case domain')
        s3=self.chip=='esp32s3';param=self.param;write_slot=0x198 if s3 else 0x1bc;read_slot=write_slot-4
        memory={};trace=[];generation=0;calls=0;soft_calls=0;steps=0
        mode_offset=0x2a5 if s3 else 0x322
        def event(kind,*args):
            require(len(args)<=7,'Oversized event');trace.extend([kind,*(a&MASK for a in args),*([0]*(7-len(args)))])
        def put(address,width,value):
            for i in range(width):memory[address+i]=(value>>(8*i))&255
        def get(address,width):
            require(all(address+i in memory for i in range(width)),f'Uninitialized memory {address:x}/{width}')
            return sum(memory[address+i]<<(8*i) for i in range(width))
        put(param+0x120,4,c[3]);put(param+mode_offset,1,c[4]);put(param+0xf3,1,c[1])
        for i,a in enumerate(self.globals):put(a,2,c[5+i])
        def location(address):
            if address in self.globals:return 0x300000+2*self.globals.index(address)
            require(param<=address<param+self.e['symbols']['phy_param']['size_bytes'],'Unknown parameter address')
            return 0x200000+address-param
        def read(address,width):
            if address==self.table and width==4:
                event(4,generation);return 0x70000000+generation*0x1000
            if 0x70000000<=address<0x70010000 and width==4:
                active,offset=divmod(address-0x70000000,0x1000)
                require(active<=generation and offset in (write_slot,read_slot),'Unknown callback slot')
                event(5,offset,active);return 0x71000000+active*0x1000+offset
            if address in (param+0x120,param+mode_offset,param+0xf3) or address in self.globals:
                require(width==(4 if address==param+0x120 else (2 if address in self.globals else 1)),'Boundary read width')
                value=get(address,width);event(1,location(address),width,value);return value
            if all(address+i in self.constants for i in range(width)):
                return sum(self.constants[address+i]<<(8*i) for i in range(width))
            require(0x100000<=address and address+width<=0x110000,'Unmapped read');return get(address,width)
        def write(address,width,value):
            if address==param+0x120 or param+0x166<=address<=param+0x16e:
                require(width==(4 if address==param+0x120 else 1),'Boundary write width')
                event(2,location(address),width,value&((1<<(width*8))-1));put(address,width,value);return
            require(0x100000<=address and address+width<=0x110000 and width in (2,4),'Non-stack store');put(address,width,value)
        def mutate_state():
            put(param+0x120,4,get(param+0x120,4)^0x01000000)
            put(param+0xf3,1,get(param+0xf3,1)+37)
            put(param+mode_offset,1,get(param+mode_offset,1)^1)
            for a in self.globals:put(a,2,get(a,2)^0x173)
        def opaque(target,args):
            nonlocal generation,calls,soft_calls
            if target==self.delay:
                require(args[0]==100,'Delay changed');event(11,100);return c[11]
            if target in self.soft:
                kind=self.soft[target];left=args[0] if kind==0 else args[0]|args[1]<<32;right=args[2]|args[3]<<32 if kind in (1,2) else 0
                if c[12]&(1<<soft_calls):result=c[13]|(c[14]<<32 if kind!=3 else 0)
                elif kind==0:result=float_bits(float(signed(left)))
                elif kind in (1,2):
                    a,b=bits_float(left),bits_float(right);result=float_bits(a/b if kind==1 else a-b)
                else:
                    value=bits_float(left)
                    require(math.isfinite(value) and -2147483648<=value<2147483648,'Soft conversion outside modeled finite domain')
                    result=int(value)&MASK
                event(12,kind,left&MASK,left>>32,right&MASK,right>>32,result&MASK,result>>32)
                if c[15]&(1<<soft_calls):mutate_state()
                soft_calls+=1;return (result&MASK,result>>32) if kind!=3 else result
            require(0x71000000<=target<0x71010000,'Unknown call target')
            active,slot=divmod(target-0x71000000,0x1000)
            require(active<=generation and slot in (write_slot,read_slot),'Unknown callback target')
            event(6,target,*args[:6 if slot==write_slot else 5]);result=c[2] if slot==read_slot else c[11]
            if c[7]&(1<<calls):generation+=1
            if c[8]&(1<<calls):mutate_state()
            calls+=1;require(calls<=10,'Callback budget exhausted');return result
        def new_registers():
            r={f'a{i}':(0xabc00000+i*0x1001)&MASK for i in range(16)}
            r.update({f's{i}':0xddd00000+i*0x1001 for i in range(12)})
            r.update({f't{i}':0xeee00000+i*0x1001 for i in range(7)})
            r.update(sp=0x110000,ra=0)
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
            nonlocal steps
            require(depth<2,'Call nesting exhausted');loop=None
            while True:
                steps+=1;require(steps<=3000,'Instruction budget exhausted')
                require(pc in self.program,'Unknown branch target')
                next_pc,op,args=self.program[pc]
                if op=='entry':
                    require(s3 and args[0]=='a1' and int(args[1],0) in (32,64),'Unexpected entry')
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
                elif op in ('lw','lh','lhu','lbu','sw','sh','sb'):
                    m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[1]);require(m is not None,'Bad memory operand')
                    address=(r[m[2]]+int(m[1]))&MASK;width=4 if op in ('lw','sw') else (1 if op in ('lbu','sb') else 2)
                    if op in ('sw','sh','sb'):write(address,width,r[args[0]])
                    else:
                        value=read(address,width);r[args[0]]=(signed(value,16) if op=='lh' else value)&MASK
                elif op in ('l32i','l32i.n','l16si','l16ui','s16i','s32i','s32i.n','l8ui','s8i'):
                    address=(r[args[1]]+int(args[2],0))&MASK;width=2 if '16' in op else (1 if op in ('l8ui','s8i') else 4)
                    if op.startswith('s'):write(address,width,r[args[0]])
                    else:
                        value=read(address,width);r[args[0]]=(signed(value,16) if op=='l16si' else value)&MASK
                elif op in CONDITIONAL:
                    left=r[args[0]]
                    if op=='bnez':take=left!=0
                    elif op=='beqz':take=left==0
                    elif op=='bltz':take=signed(left)<0
                    else:
                        right=int(args[1],0)&MASK if op in ('beqi','bgei') else r[args[1]]
                        if op=='beqi':take=left==right
                        elif op=='bltu':take=left<right
                        elif op=='bne':take=left!=right
                        elif op=='blt':take=signed(left)<signed(right)
                        else:take=signed(left)>=signed(right)
                    if take:next_pc=int(args[-1],16)
                elif op=='loop':
                    require(s3 and r[args[0]]==4,'Unexpected loop count')
                    loop=[next_pc,int(args[1],16),r[args[0]]]
                elif op=='j':next_pc=int(args[0],16)
                elif op in ('jal','jalr','call8','callx8'):
                    if op in ('jal','call8'):target=int(args[0],16)
                    elif '(' in args[0]:
                        m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[0]);require(m is not None,'Bad call operand');target=(r[m[2]]+int(m[1]))&MASK
                    else:target=r[args[0]]
                    if not s3:target&=~1;r['ra']=next_pc
                    values=[r[f'a{i+(10 if s3 else 0)}'] for i in range(6)]
                    if target==self.starts[0]:
                        require(c[0]==1 and depth==0,'Unexpected direct helper')
                        event(9,values[0])
                        if c[10]:mutate_state()
                        result=invoke(target,values,r,depth) if c[9] else c[2]
                    else:result=opaque(target,values)
                    clobber(r,result)
                elif op=='memw':require(s3 and not args,'Unexpected barrier')
                elif op in ('ret','retw.n'):
                    require((op=='retw.n')==s3,'Wrong return ABI');return r['a2' if s3 else 'a0']&MASK
                else:raise ValueError('Unknown instruction '+op)
                if loop and next_pc==loop[1]:
                    loop[2]-=1
                    if loop[2]:next_pc=loop[0]
                    else:loop=None
                pc=next_pc
        registers=new_registers()
        if c[0]==0:registers['a2' if s3 else 'a0']=c[1]
        result=execute(self.starts[c[0]],registers)
        inactive=bool(c[0] and c[3]&(1<<23))
        require(calls==(0 if inactive or (c[0]==1 and c[9]==0) else 10),'Unexpected callback count')
        require(soft_calls==(7 if c[0] and not inactive else 0),'Unexpected soft-call count')
        return (result if c[0]==0 else 0),trace

def default_case(operation):return [operation,3,42,0,1,155,355,0,0,1,0,0x13579bdf,0,0,0,0]

def smoke_cases():
    for op in (0,1):
        for selector in (0,1,2,3,4,255,256,257,258,259,MASK):
            for mode in (0,1):
                for sample in (0,42,65535,0x7fffffff,0x80000000,MASK):
                    c=default_case(op);c[1:5]=selector,sample,0,mode;c[7]=1023;c[8]=1023;c[10]=1;c[15]=127;yield c
    for flags in (0,1<<23,MASK):
        for divisor in (0,1,2,65535):
            c=default_case(1);c[3]=flags;c[5]=divisor;c[6]=divisor;c[9]=0;yield c
    for lo,hi in ((0,0),(1,0x3ff00000),(MASK,MASK),(0,0x80000000)):
        c=default_case(1);c[12:15]=127,lo,hi;c[15]=127;yield c

def cases(chip):
    yield from smoke_cases()
    edges=(0,1,2,3,15,31,32,55,56,63,64,127,128,255,256,1023,32767,32768,65535,65536,0x7fffffff,0x80000000,0xfffffff0,MASK)
    for value in range(65536):
        c=default_case(0);c[1]=value;c[2]=edges[value%len(edges)];c[7]=value&1023;c[8]=(value>>6)&1023;yield c
        c=default_case(1);c[2]=value;c[4]=value%256;c[9]=value&1;c[7]=value&1023;c[8]=value&1023;c[15]=value&127;yield c
    if chip=='esp32c3':
        for value in range(65536):
            for axis in (5,6):
                c=default_case(1);c[axis]=value;c[2]=edges[value%len(edges)];c[9]=0;c[10]=1;yield c
    for selector in range(256):
        for mode in (0,1,2,255):
            c=default_case(1);c[1]=selector;c[4]=mode;c[7:11]=1023,1023,1,1;yield c
    for mask in range(1024):
        for sample in (0,0x12345678,MASK):
            c=default_case(0);c[1]=mask;c[2]=sample;c[7]=mask;c[8]=mask^0x155;yield c
            c=default_case(1);c[2]=sample;c[7:11]=mask,mask^0x155,1,1;yield c
    # Exercise low16 narrowing before signed clamping, including scaled i32
    # wrap boundaries. Other coordinates vary, not a full Cartesian search.
    for numerator in (0,1,189,190,309,310,410,0x7fffffff,0x80000000,MASK):
        for delta in range(-8,9):
            sample=((numerator//82)-56+delta)&MASK
            for mode in (0,1):
                c=default_case(1);c[2]=sample;c[4]=mode;c[9]=0;yield c
    for value in range(65536):
        c=default_case(1);c[2]=(value*0x10203041)&MASK;c[9]=0;c[12:15]=127,value,0x3ff00000|(value&0xfffff);c[15]=value&127;yield c
    for bit in range(32):
        for flags in (1<<bit,MASK^(1<<bit)):
            for mode in (0,1):
                c=default_case(1);c[3]=flags;c[4]=mode;c[7:11]=1023,1023,1,1;yield c
    for mask in range(128):
        for value in (-123456.5,-8.0,0.0,1.0,32767.5,65535.5):
            bits=float_bits(value);c=default_case(1);c[12:15]=mask,bits&MASK,bits>>32;c[15]=mask;c[9]=0;yield c

def stream(chip,output):
    data=json.loads(Path(__file__).with_name('original-instructions.json').read_text());oracle=Oracle(chip,data[chip]);digest=hashlib.sha256();count=0;coverage=[0,0]
    for case in cases(chip):
        result,trace=oracle.run(case);require(len(trace)%8==0,'Invalid trace shape')
        words=case+[result,len(trace)//8]+trace;packed=struct.pack('<'+'I'*len(words),*words);output.write(packed);digest.update(packed);count+=1;coverage[case[0]]+=1
    require(all(coverage),'Missing function coverage')
    return {'cases':count,'operations':coverage,'case_stream_sha256':digest.hexdigest(),'fixture_sha256':hashlib.sha256(json.dumps(data[chip],sort_keys=True).encode()).hexdigest()}

def main():
    require(len(sys.argv)==3,'Usage: verify.py chip output.bin');chip=sys.argv[1]
    with Path(sys.argv[2]).open('wb') as out:result=stream(chip,out)
    expected=json.loads(Path(__file__).with_name('expected-results.json').read_text())[chip];require(result==expected,'Oracle results differ from reviewed fixture');print(json.dumps({chip:result}))
if __name__=='__main__':main()
