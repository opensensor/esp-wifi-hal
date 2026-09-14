#!/usr/bin/env python3
"""Run original initialization instructions against explicit memory/call boundaries."""
from pathlib import Path
import hashlib,json,struct
from machine import Machine,decode,require,signed,CONDITIONAL,MASK
HERE=Path(__file__).resolve().parent
CONTRACTS=json.loads((HERE/'contracts.json').read_text())
MMIO=(0x6000e130,0x60006110,0x6001cd0c,0x60007050)

def arguments(c):
    kind=c[0];p=0x200000;input=0x300000;data=0x310000;reference=0x320000
    if c[20]==1:input=data
    elif c[20]==2:input=p+240
    elif c[20]==3:reference=data+300
    if kind==11 and c[1]:input=0
    return {0:[],1:[],2:[input],3:[data,c[3]],4:[data,c[2]],5:[data],6:[data,reference,c[2]],7:[data],8:[c[2],data,input,c[3]],9:[],10:[],11:[input,data,c[2]],12:[],13:[input],14:[],15:[],16:[],17:[]}[kind]

class Oracle(Machine):
    def __init__(self,chip,e):
        self.chip,self.e,self.spec=chip,e,CONTRACTS[chip]
        self.program,_=decode(e);self.visited=set();self.branches=set()
        fn={f['name']:int(f['address'],0) for f in e['functions']}
        require(set(fn)=={v['name'] for v in self.spec['functions'].values()},'Unexpected function names')
        self.entries={int(k):fn[v['name']] for k,v in self.spec['functions'].items()};self.kinds={v:k for k,v in self.entries.items()}
        self.extent=740 if chip=='esp32s3' else 848
        self.param=int(e['symbols']['phy_param']['address'],0)
        require(e['symbols']['phy_param']['size_bytes']==self.extent,'Parameter extent differs')
        self.regions=[(self.param,self.extent,0x200000),(int(e['symbols']['chip7_phy_init_ctrl']['address'],0),42,0x210000),(int(e['symbols']['g_phyFuns']['address'],0),4,0x220000)]
        if chip=='esp32c3':self.regions.append((self.spec['version_state'],1,0x230000))
        self.addresses={};self.helper_addresses={}
        for name,ident in self.spec['symbol_ids'].items():
            a=int(e['symbols'][name]['address'],0);self.addresses[a]=0x760000+ident*16
        for key,row in self.spec['helpers'].items():self.helper_addresses[int(e['symbols'][row['name']]['address'],0)]=(int(key),row)
        for kind,a in self.entries.items():self.addresses[a]=0x750000+kind*16
        for row in e['readonly']:
            data=bytes.fromhex(row['bytes']);require(len(data)==row['size_bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'],'Readonly hash differs')
            self.regions.append((int(row['address'],0),len(data),0x240000))
    def canonical(self,a):
        a&=MASK
        if a in self.addresses:return self.addresses[a]
        for start,size,base in reversed(self.regions+self.locals):
            if start<=a<start+size:return base+a-start
        return a
    def real(self,a):
        for start,size,base in self.regions:
            if base<=a<base+size:return start+a-base
        return a
    def event(self,k,*args):
        require(len(args)<=15,'Event extent');self.trace.extend([k,*(x&MASK for x in args),*([0]*(15-len(args)))])
    def put(self,a,w,v):
        for i in range(w):self.mem[(a+i)&MASK]=(v>>(i*8))&255
    def get(self,a,w):
        if 0x70000000<=a<0x70400000 and all(a+i not in self.mem for i in range(w)):
            require(w==4 and a%4==0,'Bad slot width');return 0x71000000+a-0x70000000
        require(all(a+i in self.mem for i in range(w)),f'Uninitialized {a:x}/{w}')
        return sum(self.mem[a+i]<<(i*8) for i in range(w))
    def observed(self,a,w):
        a=self.canonical(a)
        return 0x200000<=a and a+w<=0x200000+self.extent or 0x210000<=a and a+w<=0x21002a or a in (0x220000,0x230000) or any(b<=a and a+w<=b+1024 for b in (0x300000,0x310000,0x320000)) or 0x70000000<=a<0x70400000 or a in MMIO
    def change(self):self.put(self.param+self.c[8],1,self.get(self.param+self.c[8],1)^self.c[9])
    def mutate(self):
        if self.c[12]&(1<<(self.calls%32)):self.change()
        if self.c[13]&(1<<(self.calls%32)):
            self.generation+=1;self.put(self.real(0x220000),4,0x70000000+self.generation*0x1000)
        self.calls+=1
    def read(self,a,w):
        v=self.get(a,w)
        if self.observed(a,w):
            self.event(1,self.canonical(a),w,self.canonical(v))
            if self.c[10]&(1<<(self.reads%32)):self.change()
            self.reads+=1
        else:require(0x100000<=a<0x110000 or 0x240000<=self.canonical(a)<0x240024 or 0x500000<=a<0x508000,f'Unmapped read {a:x}')
        return v
    def write(self,a,w,v):
        v&=(1<<(8*w))-1
        observed=self.observed(a,w)
        if observed:self.event(2,self.canonical(a),w,self.canonical(v))
        else:require(0x100000<=a<0x110000 or 0x500000<=a<0x508000,f'Unmapped write {a:x}')
        self.put(a,w,v)
        if observed:
            if self.c[11]&(1<<(self.writes%32)):self.change()
            self.writes+=1
    def bind(self,start,size,tag):self.locals.append((start,size,0x500000+tag*0x1000))
    def enter(self,kind,sp):
        s3=self.chip=='esp32s3'
        if kind==13:self.bind(sp,28,0)
        elif kind==2:self.bind(sp+(0 if s3 else 12),20,1)
        elif kind==1:self.bind(sp+(0 if s3 else 8),8,2)
        elif kind==6:self.bind(sp+(2 if s3 else 8),2,3);self.bind(sp+(0 if s3 else 12),2,4)
        elif kind==11:self.bind(sp+(0 if s3 else 96),128,5);self.bind(sp+(128 if s3 else 0),96,6)
    def copy(self,d,s,n):
        require(n in (8,14,236,244),'Unexpected memcpy extent')
        # libc has memory-only effects. Private stack initialization may be
        # inlined; consumed bytes remain checked by the instruction interpreter.
        if self.observed(d,n):self.event(7,self.canonical(d),self.canonical(s),n)
        require(d+n<=s or s+n<=d,'Overlapping memcpy')
        for i in range(n):self.put(d+i,1,self.get(s+i,1))
    def clear(self,d,n):
        require(n in (20,128),'Unexpected memset extent')
        if self.observed(d,n):self.event(8,self.canonical(d),n)
        for i in range(n):self.put(d+i,1,0)
    def snapshot(self,a,n):
        # Only private input storage is summarized. Shared accesses retain their
        # ordered width/value events; no observer mutations occur in snapshots.
        if not 0x500000<=self.canonical(a)<0x508000:return
        for offset in range(0,n,12):
            payload=[self.get(a+i,1) for i in range(offset,min(offset+12,n))]
            self.event(11,self.canonical(a)+offset,len(payload),*payload)
    def child(self,kind,args,r,depth):
        if kind==2:self.snapshot(args[0],77)
        if kind==6 and args[2]:self.snapshot(args[1],93)
        # Both original check bodies ignore argument 2 (the init pointer).
        # LLVM legitimately leaves that outgoing register unspecified.
        self.event(3,kind,*(0 if kind==8 and i==2 else self.canonical(v) for i,v in enumerate(args)))
        if self.c[17]&(1<<kind):
            # Closed local implementations have finite result ranges; LLVM may
            # propagate those ranges across their non-inlined ABI wrappers.
            value=self.c[18]%({6:46,8:2,14:8}.get(kind,1))
            if kind==6 and not args[2]:
                for i in range(93):self.put(args[1]+i,1,self.c[14]+i*13)
            self.mutate()
        else:
            nested=self.registers((r['a1'] if self.chip=='esp32s3' else r['sp'])-256)
            for i,v in enumerate(args):nested[f'a{i+(2 if self.chip=="esp32s3" else 0)}']=v
            value=self.execute(self.entries[kind],nested,kind,depth+1)
            if not self.spec['functions'][str(kind)]['returns']:value=0
        self.event(4,kind,value);return value
    def dispatch(self,target,values,r,depth):
        if target in self.kinds:
            kind=self.kinds[target];return self.child(kind,values(self.spec['functions'][str(kind)]['arity']),r,depth)
        if target in self.helper_addresses:
            ident,row=self.helper_addresses[target];name=row['name'];args=values(row['arity']);ret=0
            if name=='memcpy':self.copy(*args);return args[0]
            if name=='memset':require(args[1]==0,'Unexpected memset byte');self.clear(args[0],args[2]);return args[0]
            self.event(5,ident,*(self.canonical(v) for v in args))
            if name=='phy_get_romfuncs':ret=0x70000000+self.generation*0x1000
            elif name=='chip726_phyrom_version_num':ret=self.c[22]
            elif name=='phy_get_rf_cal_version':ret=self.c[3]
            elif name=='get_iq_value':
                # Explicit helper boundary; independent synthetic outputs, not a
                # second implementation of this previously validated member.
                for i in range(2):self.put(args[0]+i,1,(args[1]>>(i*8))^(args[2]*0x51)^self.c[14])
            self.mutate();self.event(6,ident,ret);return ret
        require(0x71000000<=target<0x71400000,f'Unknown call {target:x}')
        generation,offset=divmod(target-0x71000000,0x1000)
        require(str(offset) in self.spec['slots'],'Unknown slot '+hex(offset))
        args=values(self.spec['slots'][str(offset)])
        if offset==(0x1cc if self.chip=='esp32s3' else 0x1f0):self.snapshot(args[0],8)
        self.event(9,target,*(self.canonical(v) for v in args));ret=0
        if offset==(0x98 if self.chip=='esp32s3' else 0xa4):ret=self.get(args[0],4)
        elif offset==(0xec if self.chip=='esp32s3' else 0x100):ret=(self.c[14]+self.calls*self.c[15])&MASK if self.c[26] else abs(signed(args[0]))&MASK
        elif offset==(0x160 if self.chip=='esp32s3' else 0x184):ret=(self.c[14]+self.calls*self.c[15])&MASK
        self.mutate();self.event(10,target,ret);return ret
    def run(self,c):
        require(len(c)==48 and all(0<=v<=MASK for v in c),'Invalid case words');require(c[0] in self.entries,'Unknown function')
        require(c[8]<self.extent,'Invalid mutation offset')
        self.c=c;self.mem={};self.trace=[];self.locals=[];self.calls=self.reads=self.writes=self.steps=self.generation=0
        for i in range(self.extent):self.put(self.param+i,1,c[4]+i*17)
        for a,size in [(0x210000,42),(0x220000,4),(0x230000,1)]:
            if a==0x230000 and self.chip=='esp32s3':continue
            for i in range(size):self.put(self.real(a)+i,1,c[4]+i*7)
        self.put(self.real(0x220000),4,0x70000000)
        for b in (0x300000,0x310000,0x320000):
            for i in range(1024):self.put(b+i,1,(c[21] if b==0x320000 else c[4])+i*17)
        for offset,value,width in [(288,c[5],4),(229,c[6],1),(162,c[2],1),(170,c[7],1),(498,c[7],1),(525,c[7],1),(286,c[7],1),(674 if self.chip=='esp32s3' else 799,c[7],1),(675 if self.chip=='esp32s3' else 800,c[7],1),(679 if self.chip=='esp32s3' else 804,c[7],1)]:self.put(self.param+offset,width,value)
        if self.chip=='esp32s3':self.put(self.param+729,1,c[7])
        for row in self.e['readonly']:
            for i,v in enumerate(bytes.fromhex(row['bytes'])):self.put(int(row['address'],0)+i,1,v)
        for a in MMIO:self.put(a,4,c[23] if a==0x60007050 else c[5]^a)
        self.put(0x310000,4,c[3]);checksum=(~sum(self.get(0x310000+i,4) for i in range(0,self.extent+12,4)))&MASK
        self.put(0x310000+self.extent+12,4,checksum^(c[16]&MASK))
        r=self.registers();args=[self.real(a) for a in arguments(c)]
        for i,v in enumerate(args):r[f'a{i+(2 if self.chip=="esp32s3" else 0)}']=v
        value=self.execute(self.entries[c[0]],r,c[0]);value=value if self.spec['functions'][str(c[0])]['returns'] else 0
        return value,self.trace

def default_case(kind):
    c=[0]*48;c[0]=kind;c[2]=1;c[3]=0x23456789;c[4]=33;c[6]=0;c[7]=1;c[8]=229;c[9]=1;c[14]=0x125;c[17]=(1<<18)-1;c[21]=73;c[22]=1
    return c

def cases(chip):
    for kind in map(int,CONTRACTS[chip]['functions']):
        yield default_case(kind)
        axes=[(4,[0,1,127,128,255]),(5,[0,MASK,0x10000,0x80000,0x100020]),(6,[0,1,255]),(7,[0,1,2,7,16,127,128,255]),(22,[0,1,255,256,257,MASK]),(3,[0,1,255,256,0x12345678,MASK])]
        if kind in (4,6,8,11,9):axes.append((2,[0,1,2,16,17,18,255,256,257,MASK]))
        if kind in (2,6,8,11,13):axes.append((20,[0,1,2,3]))
        if kind==11:axes.extend([(1,[0,1]),(18,[0,1,255]),(17,[(1<<18)-1-(1<<2),(1<<18)-1-(1<<8),(1<<18)-1-(1<<6)])])
        if kind in (2,8,15):axes.append((17,[0]))
        if kind==8:axes.append((16,[0,1,0x80000000,MASK]))
        if kind==6:axes.extend([(26,[0,1]),(14,[0,1,4,5,0x80000000,MASK])])
        if kind==14:axes.append((23,[v<<21 for v in range(8)]+[MASK]))
        axes.extend([(12,[1,2,4,MASK]),(13,[1,2,4,MASK])])
        if kind not in (4,8):axes.extend([(10,[1,2,4,MASK]),(11,[1,2,4,MASK])])
        for index,values in axes:
            for v in values:
                c=default_case(kind);c[index]=v;yield c

    # Joint axes cover comparison thresholds and independent initialization status.
    for result in (0,1,4,5,127,0x80000000,MASK):
        c=default_case(6);c[26]=1;c[14]=result;yield c
    for mode in (0,1,2,16,17,255,256,257,MASK):
        for status in (0,1,255):
            c=default_case(11);c[2]=mode;c[18]=status;yield c
    for kind in (2,4,5,6,8,11,13,16,17):
        if str(kind) not in CONTRACTS[chip]['functions']:continue
        for offset in (162,229,286,288,498,525,674 if chip=='esp32s3' else 799):
            for mask_index in (10,11,12):
                c=default_case(kind);c[8]=offset;c[9]=255;c[mask_index]=MASK;yield c


    # Whole local initialization composition, with callbacks installed by the ROM
    # getter left as synthetic slot boundaries. RF/BB execute their actual bodies.
    for mode in (0,1,2,16,17,255,256,257):
        for cold in (0,1):
            for null in (0,1):
                for checksum in (0,1):
                    c=default_case(11);c[2]=mode;c[6]=cold;c[1]=null;c[16]=checksum;c[17]=1
                    yield c
    # Fixed xorshift seed, covering combinations of byte/sign/version boundaries,
    # state mutations and callback-table reloads reproducibly on both chips.
    seed=0x70687931
    kinds=list(map(int,CONTRACTS[chip]['functions']))
    def next_word():
        nonlocal seed
        seed^=(seed<<13)&MASK;seed^=seed>>17;seed^=(seed<<5)&MASK;seed&=MASK;return seed
    for _ in range(512):
        c=default_case(kinds[next_word()%len(kinds)])
        for i in (2,3,4,5,6,7,9,12,13,14,15,16,18,21,22,23,26):c[i]=next_word()
        c[1]=next_word()%2;c[20]=next_word()%4
        c[8]=(162,229,286,288,498,525,674 if chip=='esp32s3' else 799)[next_word()%7]
        if c[0] not in (4,8):c[10]=next_word();c[11]=next_word()
        yield c

def write_cases(chip,e,path,coverage=True):
    o=Oracle(chip,e);digest=hashlib.sha256();count=0
    with path.open('wb') as stream:
        for c in cases(chip):
            try:result,trace=o.run(c)
            except Exception as error:raise RuntimeError(f'Case {count}: {c}') from error
            raw=struct.pack('<'+'I'*(50+len(trace)),*c,result,len(trace),*trace);stream.write(raw);digest.update(raw);count+=1
    missing=set(o.program)-o.visited;edges={(pc,b) for pc,(_,op,_) in o.program.items() if op in CONDITIONAL for b in (False,True)}
    result={'cases':count,'sha256':digest.hexdigest(),'instructions':len(o.program),'visited':len(o.visited),'edges':len(edges),'visited_edges':len(o.branches),'missing_instructions':[hex(x) for x in sorted(missing)],'missing_edges':[(hex(pc),b) for pc,b in sorted(edges-o.branches)]}
    if coverage:require(not missing and not edges-o.branches,'Incomplete coverage '+str(result))
    return result
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('chip',choices=CONTRACTS);p.add_argument('output',type=Path);p.add_argument('--diagnostic',action='store_true');a=p.parse_args()
    raw=(HERE/'original-instructions.json').read_bytes();base=json.loads((HERE/'baselines.json').read_text())[a.chip];e=json.loads(raw)[a.chip]
    require(hashlib.sha256(raw).hexdigest()==base['fixture_sha256'],'Fixture hash differs')
    require(e['elf_sha256']==base['elf_sha256'] and e['map_sha256']==base['map_sha256'],'Baseline differs')
    result=write_cases(a.chip,e,a.output,not a.diagnostic)
    if not a.diagnostic:require(result==json.loads((HERE/'expected-results.json').read_text())[a.chip],'Case stream or coverage differs')
    print(json.dumps(result,indent=2))
