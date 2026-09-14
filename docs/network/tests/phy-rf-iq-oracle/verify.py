"""Execute RF-IQ instructions; synthetic tone/IQ/absolute-value boundaries.

Class 0 admits all output bytes for conservative interface coverage. Class 1
restricts corrections to the proven -31..31 range, without claiming to execute
the analog estimator or the preceding IQ implementation inside this oracle.
"""
import hashlib,json,struct,sys
from pathlib import Path
from machine import Machine,decode,require,signed,CONDITIONAL,MASK
HERE=Path(__file__).resolve().parent
NAMES=['rfcal_rxiq','get_rfcal_rxiq_data']
MMIO=0x6000607c
CASE_WORDS=20
def output(c):return [0x300000,MMIO,0x220000][c[8]]
def difference(value,mode):
 return [abs(signed(value)),MASK,256,0x80000000,2][mode]
class Oracle(Machine):
 def __init__(self,chip,e):
  self.chip,self.e=chip,e;self.program,_=decode(e);self.visited=set();self.branches=set()
  self.entries={NAMES.index(f['name']):int(f['address'],0) for f in e['functions']};self.kinds={v:k for k,v in self.entries.items()}
  require(set(self.entries)=={0,1},'Function set differs')
  self.table=int(e['symbols']['g_phyFuns']['address'],0)
  self.helpers={int(e['symbols'][n]['address'],0):n for n in ['rxiq_cover_mg_mp','start_tx_tone_step','stop_tx_tone','phy_printf']}
 def canonical(self,a):
  if self.table<=a<self.table+4:return 0x220000+a-self.table
  return self.locals.get(a,a)
 def actual(self,a):return self.table+a-0x220000 if 0x220000<=a<0x220004 else a
 def put(self,a,w,v):
  for i in range(w):self.mem[a+i]=(v>>(i*8))&255
 def get(self,a,w):
  if 0x70000000<=a<0x70400000:
   require(w==4 and a%4==0,'Bad callback-table read');return a+0x1000000
  require(all(a+i in self.mem for i in range(w)),f'Uninitialized {a:x}/{w}')
  return sum(self.mem[a+i]<<(i*8) for i in range(w))
 def event(self,k,*args):
  require(len(args)<8,'Event width');self.trace.extend([k,*(x&MASK for x in args),*([0]*(7-len(args)))])
 def observed(self,a):
  a=self.canonical(a)
  return MMIO<=a<MMIO+4 or 0x220000<=a<0x220004 or 0x300000<=a<0x300004 or a in (0x500000,0x500001,0x500100,0x500101) or 0x70000000<=a<0x70400000
 def read(self,a,w):
  v=self.get(a,w)
  if self.observed(a):self.event(1,self.canonical(a),w,v)
  else:require(0x100000<=a<0x110000,'Unmapped read')
  return v
 def write(self,a,w,v):
  v&=(1<<(8*w))-1
  if self.observed(a):self.event(2,self.canonical(a),w,v)
  else:require(0x100000<=a<0x110000,'Unmapped write')
  self.put(a,w,v)
 def enter(self,kind,sp):
  if kind==1:
   a=sp+(0 if self.chip=='esp32s3' else 12);self.locals.update({a:0x500000,a+1:0x500001})
  else:
   a,b=(sp+1,sp) if self.chip=='esp32s3' else (sp+14,sp+15);self.locals.update({a:0x500100,b:0x500101})
 def mutate(self):
  self.mutations+=1
  if self.c[7]:self.generation+=1;self.put(self.table,4,0x70000000+self.generation*0x1000)
  if self.c[6]:self.put(MMIO,4,self.get(MMIO,4)^((self.c[6]+self.mutations*self.c[18])&MASK))
 def dispatch(self,target,values,r,depth):
  if target in self.kinds:
   require(self.kinds[target]==0,'Unexpected nested collection');args=values(5)
   self.event(7,args[0],args[1],args[2],self.canonical(args[3]),args[4])
   nested=self.registers((r['a1'] if self.chip=='esp32s3' else r['sp'])-256);base=2 if self.chip=='esp32s3' else 0
   for i,v in enumerate(args):nested[f'a{base+i}']=v
   self.execute(target,nested,0,depth+1);self.event(8);return 0
  helper=self.helpers.get(target)
  if helper=='start_tx_tone_step':
   a=values(6);require(a[0]==1 and a[3:]==[0,0,0],'Unexpected tone arguments');self.event(3,*a);self.mutate();return 0
  if helper=='stop_tx_tone':
   a=values(1);require(a==[1],'Unexpected stop argument');self.event(5,*a);self.mutate();return 0
  if helper=='rxiq_cover_mg_mp':
   a=values(4);require(self.sample_index<4,'Too many samples');m,p=self.c[10+self.sample_index*2:12+self.sample_index*2];self.sample_index+=1
   self.event(4,a[0],self.canonical(a[1]),self.canonical(a[2]),a[3],m,p)
   self.put(a[1],1,m);self.put(a[2],1,p);self.mutate();return 0
  if helper=='phy_printf':
   a=values(4);require(a[0] in {int(row['address'],0) for row in self.e['logs']},'Unknown format');self.event(6,*a[1:]);self.mutate();return 0
  require(0x71000000<=target<0x71400000,f'Unknown helper {target:x}')
  require((target-0x71000000)%0x1000==(0xec if self.chip=='esp32s3' else 0x100),'Unknown callback')
  a=values(1)[0];v=difference(a,self.c[9]);self.event(9,target,a,v);self.mutate();return v
 def run(self,c):
  require(len(c)==CASE_WORDS and all(0<=v<=MASK for v in c),'Invalid case');require(c[0] in self.entries and c[8]<=2 and c[9]<=4 and c[19]<=1,'Invalid case mode')
  require(all(v<=255 for v in c[10:18]),'Invalid sample byte')
  if c[19]:require(all(-31<=signed(v,8)<=31 for v in c[10:18]),'Out-of-range bounded case')
  self.c=c;self.mem={};self.trace=[];self.locals={};self.steps=self.generation=self.mutations=self.sample_index=0
  self.put(MMIO,4,c[5]);self.put(self.table,4,0x70000000);self.put(0x300000,4,0xa5a5a5a5)
  for row in self.e['logs']:require(hashlib.sha256(bytes.fromhex(row['bytes'])).hexdigest()==row['sha256'],'Format hash')
  args=[c[1],c[2],c[3],self.actual(output(c)),c[4]] if c[0]==0 else [c[2],c[3],c[4]]
  r=self.registers();base=2 if self.chip=='esp32s3' else 0
  for i,v in enumerate(args):r[f'a{base+i}']=v
  result=self.execute(self.entries[c[0]],r,c[0])
  if c[0]==1:self.event(10,result)
  return self.trace

def cases(chip):
 base=[1,14,0x12348001,0x123401,1,0xabcdef12,0x12345678,1,0,0,0,0,0,0,0,0,0,0,0x13579bdf,0]
 for kind in (0,1):
  c=list(base);c[0]=kind;yield c
  for index,vals in [(1,[0,1,14,255,256,257,MASK]),(2,[0,1,32767,32768,65535,65536,MASK]),(3,[0,255,256,257,MASK]),(4,[0,1,255,256,257,MASK]),(5,[0,MASK]),(6,[0,MASK]),(7,[0,1]),(8,[0,1,2]),(9,range(5))]:
   for v in vals:d=list(c);d[index]=v;yield d
 for m in [-128,-127,-64,-32,-31,-30,-2,-1,0,1,2,30,31,32,63,126,127]:
  for p in [-128,-32,-31,-1,0,1,31,32,127]:
   for sequence in [[m,p]*4,[0,0,m,p,m,p,m,p],[0,0,15,-15,m,p,m,p],[m,p,-m,-p,m,p,-m,-p]]:
    d=list(base);d[10:18]=[v&255 for v in sequence];yield d
 seed=0x52464951
 def word():
  nonlocal seed
  seed^=(seed<<13)&MASK;seed^=seed>>17;seed^=(seed<<5)&MASK;seed&=MASK;return seed
 for bounded in (0,1):
  for i in range(2048):
   d=[i%2,word(),word(),word(),word() if i%3 else 0,word(),word() if i%3 else 0,word()%2,word()%3,word()%5]
   d.extend([((word()%63)-31)&255 if bounded else word()&255 for _ in range(8)]);d.extend([word(),bounded]);yield d
 # Explicit converging boundary values and signed ties under the bounded contract.
 for m in [-31,-30,-2,-1,0,1,2,30,31]:
  for p in [-31,-30,-2,-1,0,1,2,30,31]:
   for seq in [[m,p]*4,[0,0,m,p,m,p,m,p],[0,0,15,-15,m,p,m,p]]:
    d=list(base);d[10:18]=[v&255 for v in seq];d[19]=1;yield d

def write_cases(chip,e,path):
 o=Oracle(chip,e);digest=hashlib.sha256();count=0;coverage={}
 with path.open('wb') as f:
  for c in cases(chip):
   o.visited=set();o.branches=set();trace=o.run(c);raw=struct.pack('<'+'I'*(CASE_WORDS+1+len(trace)),*c,len(trace),*trace);f.write(raw);digest.update(raw);count+=1
   row=coverage.setdefault(c[19],dict(cases=0,pcs=set(),edges=set()));row['cases']+=1;row['pcs']|=o.visited;row['edges']|=o.branches
 edges={(pc,b) for pc,(_,op,_) in o.program.items() if op in CONDITIONAL for b in (False,True)}
 require(coverage[0]['pcs']==set(o.program),'Uncovered conservative PCs: '+repr(set(o.program)-coverage[0]['pcs']))
 require(coverage[0]['edges']==edges,'Uncovered conservative edges: '+repr(edges-coverage[0]['edges']))
 return dict(cases=count,sha256=digest.hexdigest(),instructions=len(o.program),conditional_edges=len(edges),coverage={str(k):dict(cases=v['cases'],instructions=len(v['pcs']),conditional_edges=len(v['edges']),uncovered_pcs=[hex(a) for a in sorted(set(o.program)-v['pcs'])],uncovered_edges=[[hex(a),b] for a,b in sorted(edges-v['edges'])]) for k,v in coverage.items()})
if __name__=='__main__':
 chip,path=sys.argv[1:];e=json.loads((HERE/'original-instructions.json').read_text())[chip];result=write_cases(chip,e,Path(path));print(chip,json.dumps(result))
 expected=HERE/'expected-results.json'
 if expected.exists():require(result==json.loads(expected.read_text())[chip],'Case digest/coverage changed')
