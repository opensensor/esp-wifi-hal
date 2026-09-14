"""Execute original RX-control instructions; compare ordered hardware boundaries."""
import hashlib,json,struct,sys
from pathlib import Path
from machine import Machine,decode,require,CONDITIONAL,MASK
HERE=Path(__file__).resolve().parent
NAMES=['rfrx_sat_rst','phy_force_rx_gain_trig','ram_iq_est_enable','phy_check_rx_sat','rfrx_sat_rst.part.0']
MMIO=(0x6001c068,0x6001c05c,0x6001c02c,0x60006140,0x60006144,0x60006174,0x6001c08c)
class Oracle(Machine):
 def __init__(self,chip,e):
  self.chip,self.e=chip,e;self.program,_=decode(e);self.visited=set();self.branches=set()
  self.entries={NAMES.index(f['name']):int(f['address'],0) for f in e['functions']};self.kinds={v:k for k,v in self.entries.items()}
  require(set(self.entries)==set(range(4 if chip=='esp32s3' else 5)),'Function set differs')
  self.param=int(e['symbols']['phy_param']['address'],0);self.table=int(e['symbols']['g_phyFuns']['address'],0);self.delay=int(e['symbols']['ets_delay_us']['address'],0)
  self.extent=740 if chip=='esp32s3' else 848;self.count=736 if chip=='esp32s3' else 842;self.flag=730 if chip=='esp32s3' else 844
 def canonical(self,a):
  if self.param<=a<self.param+self.extent:return 0x200000+a-self.param
  if a==self.table:return 0x220000
  for start in reversed(self.locals):
   if start<=a<start+8:return 0x500000+a-start
  return a
 def put(self,a,w,v):
  for i in range(w):self.mem[a+i]=(v>>(i*8))&255
 def get(self,a,w):
  if 0x70000000<=a<0x70400000:
   require(w==4 and a%4==0,'Bad callback-table read');return a+0x1000000
  require(all(a+i in self.mem for i in range(w)),f'Uninitialized {a:x}/{w}')
  return sum(self.mem[a+i]<<(i*8) for i in range(w))
 def event(self,k,*args):
  require(len(args)<=5,'Event width');self.trace.extend([k,*(x&MASK for x in args),*([0]*(5-len(args)))])
 def observed(self,a):return self.param<=a<self.param+self.extent or a==self.table or a in MMIO or 0x70000000<=a<0x70400000
 def read(self,a,w):
  if a==0x60006174:
   v=(self.c[3]&~0x10000)|(0x10000 if self.polls>=self.c[4] else 0);self.polls+=1;self.put(a,4,v)
  if a==0x6001c08c:
   level=(self.c[5]+self.samples*self.c[6])&127;self.samples+=1;self.put(a,4,(self.c[3]&~0x7f000)|(level<<12))
  v=self.get(a,w)
  if self.observed(a):
   self.event(1,self.canonical(a),w,v)
   if a in MMIO and self.c[9]:self.put(a,w,v^self.c[9])
  else:require(0x100000<=a<0x110000 or any(int(r['address'],0)<=a<a+w<=int(r['address'],0)+r['size_bytes'] for r in self.e['readonly']),'Unmapped read')
  return v
 def write(self,a,w,v):
  v&=(1<<(8*w))-1
  if self.observed(a):self.event(2,self.canonical(a),w,v)
  else:require(0x100000<=a<0x110000,'Unmapped write')
  self.put(a,w,v)
 def enter(self,kind,sp):
  if kind==3:self.locals.append(sp+(0 if self.chip=='esp32s3' else 8))
 def mutate(self):
  if self.c[7]:self.generation+=1;self.put(self.table,4,0x70000000+self.generation*0x1000)
  if self.c[8]:self.put(self.param+self.count,2,self.c[8])
  if self.c[10]:
   for a in MMIO:self.put(a,4,self.get(a,4)^self.c[10])
 def dispatch(self,target,values,r,depth):
  if target in self.kinds:
   kind=self.kinds[target];require(kind in (1,4),'Unexpected nested function')
   if kind==1:self.event(3)
   nested=self.registers((r['a1'] if self.chip=='esp32s3' else r['sp'])-256)
   self.execute(target,nested,kind,depth+1)
   if kind==1:self.event(4)
   return 0
  if target==self.delay:
   a=values(1);require(a[0] in (1,5),'Unexpected delay');self.event(5,a[0]);self.mutate();return 0
  require(0x71000000<=target<0x71400000,f'Unknown helper {target:x}')
  offset=(target-0x71000000)%0x1000;slots=([0x1b0,0x1c0,0x1cc,0x1b4] if self.chip=='esp32s3' else [0x1d4,0x1e4,0x1f0,0x1d8]);require(offset in slots,'Unknown callback')
  n=1 if offset in slots[1:3] else 0;args=values(n)
  if offset==slots[2]:
   # Record the consumed private bytes regardless of compiler initialization width.
   self.event(7,self.get(args[0],4),self.get(args[0]+4,4))
  self.event(6,target,n,*(self.canonical(a) for a in args));self.mutate();return 0
 def run(self,c):
  require(len(c)==12 and all(0<=v<=MASK for v in c),'Invalid case');require(c[0] in self.entries,'Unknown entry');require(c[4]<=512,'Unbounded completion fixture')
  self.c=c;self.mem={};self.trace=[];self.locals=[];self.steps=self.polls=self.samples=self.generation=0
  for i in range(self.extent):self.put(self.param+i,1,c[3]+i*17)
  self.put(self.table,4,0x70000000)
  for a in MMIO:self.put(a,4,c[3]^a)
  for row in self.e['readonly']:
   raw=bytes.fromhex(row['bytes']);require(hashlib.sha256(raw).hexdigest()==row['sha256'],'Readonly hash')
   for i,v in enumerate(raw):self.put(int(row['address'],0)+i,1,v)
  r=self.registers();base=2 if self.chip=='esp32s3' else 0;r[f'a{base}']=c[1];r[f'a{base+1}']=c[2]
  self.execute(self.entries[c[0]],r,c[0]);return self.trace

def cases(chip):
 for kind in range(4 if chip=='esp32s3' else 5):
  c=[kind,1,8192,0x12345678,3,69,1,0,0,0,0,0];yield c
  for index,values in [(1,[0,1,255,256,257,0x80000000,MASK]),(2,[0,1,32767,32768,65535,MASK]),(3,[0,MASK,0x80000000,0x55555555]),(4,[0,1,2,100,512]),(5,[0,68,69,70,127]),(6,[0,1,63,127]),(7,[0,1]),(8,[0,1,65534,65535]),(9,[0x80000000,MASK]),(10,[0x12345678,MASK])]:
   for v in values:d=list(c);d[index]=v;yield d
 for kind in (2,3):
  for level in (0,69,70,127):
   for polls in (0,1,2,100):yield [kind,1,8192,0x12345678,polls,level,0,1,65535,0xffffffff,0,0]
 seed=0x52584331
 def word():
  nonlocal seed
  seed^=(seed<<13)&MASK;seed^=seed>>17;seed^=(seed<<5)&MASK;seed&=MASK;return seed
 for i in range(512):
  c=[i%4,word(),word(),word(),word()%33,word()%128,word()%128,word()%2,word()&65535,word(),word(),0];yield c

def write_cases(chip,e,path):
 o=Oracle(chip,e);digest=hashlib.sha256();count=0
 with path.open('wb') as f:
  for c in cases(chip):
   trace=o.run(c);raw=struct.pack('<'+'I'*(13+len(trace)),*c,len(trace),*trace);f.write(raw);digest.update(raw);count+=1
 missing=set(o.program)-o.visited;require(not missing,'Uncovered PCs: '+repr(sorted(hex(a) for a in missing)))
 edges={(pc,b) for pc,(_,op,_) in o.program.items() if op in CONDITIONAL for b in (False,True)};require(not edges-o.branches,'Uncovered edges: '+repr(edges-o.branches))
 return dict(cases=count,sha256=digest.hexdigest(),instructions=len(o.program),conditional_edges=len(edges))
if __name__=='__main__':
 chip,path=sys.argv[1:];e=json.loads((HERE/'original-instructions.json').read_text())[chip];result=write_cases(chip,e,Path(path));print(chip,json.dumps(result))
 expected=HERE/'expected-results.json'
 if expected.exists():require(result==json.loads(expected.read_text())[chip],'Case digest/coverage changed')
