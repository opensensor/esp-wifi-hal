"""Execute the pinned IQ instructions against synthetic hardware boundaries."""
import hashlib,json,struct,sys
from pathlib import Path
from machine import Machine,decode,require,signed,CONDITIONAL,MASK
HERE=Path(__file__).resolve().parent
NAMES=['rxiq_get_mis','rxiq_cover_mg_mp']
MMIO=(0x60006148,0x60006154,0x60006150,0x6000614c,0x60006164)
WIDTH=8

def divide(n,d):
 require(d!=0,'Division by zero reached helper')
 require(not (n==-(1<<63) and d==-1),'Unmodeled ROM division overflow')
 return (abs(n)//abs(d))*(-1 if (n<0)!=(d<0) else 1)

def outputs(c):
 a=0x300000 if c[10]<2 else 0x60006164 if c[10]==2 else 0x220000
 return a,a+(0 if c[10]==1 else 1)
class Oracle(Machine):
 def __init__(self,chip,e):
  self.chip,self.e=chip,e;self.program,_=decode(e);self.visited=set();self.branches=set()
  self.entries={NAMES.index(f['name']):int(f['address'],0) for f in e['functions']};self.kinds={v:k for k,v in self.entries.items()}
  require(set(self.entries)=={0,1},'Function set differs')
  self.table=int(e['symbols']['g_phyFuns']['address'],0)
  self.helpers={int(e['symbols'][n]['address'],0):n for n in ['rxiq_set_reg','phy_printf','__divdi3']}
 def canonical(self,a):
  if self.table<=a<self.table+4:return 0x220000+a-self.table
  for start in reversed(self.locals):
   if start<=a<start+2:return 0x500000+a-start
  return a
 def actual(self,a):return self.table+a-0x220000 if 0x220000<=a<0x220004 else a
 def put(self,a,w,v):
  for i in range(w):self.mem[a+i]=(v>>(i*8))&255
 def get(self,a,w):
  if 0x70000000<=a<0x70400000:
   require(w==4 and a%4==0,'Bad callback-table read');return a+0x1000000
  require(all(a+i in self.mem for i in range(w)),f'Uninitialized {a:x}/{w}')
  return sum(self.mem[a+i]<<(i*8) for i in range(w))
 def event(self,k,*args):
  require(len(args)<WIDTH,'Event width');self.trace.extend([k,*(x&MASK for x in args),*([0]*(WIDTH-1-len(args)))])
 def observed(self,a):
  a=self.canonical(a)
  return a in MMIO or 0x220000<=a<0x220004 or 0x300000<=a<0x300004 or 0x500000<=a<0x500002 or 0x70000000<=a<0x70400000 or 0x60006164<=a<0x60006168
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
  if kind==1:self.locals.append(sp+(0 if self.chip=='esp32s3' else 12))
 def mutate(self):
  if self.c[9]:self.generation+=1;self.put(self.table,4,0x70000000+self.generation*0x1000)
  self.mutations+=1
  if self.c[8]:
   for i,a in enumerate(MMIO):self.put(a,4,self.get(a,4)^((self.c[8]+self.mutations*self.c[11]+i*0x1020304)&MASK))
 def dispatch(self,target,values,r,depth):
  if target in self.kinds:
   require(self.kinds[target]==0,'Unexpected nested correction');args=values(3)
   self.event(7,args[0],self.canonical(args[1]),args[2])
   nested=self.registers((r['a1'] if self.chip=='esp32s3' else r['sp'])-256);base=2 if self.chip=='esp32s3' else 0
   for i,v in enumerate(args):nested[f'a{base+i}']=v
   self.execute(target,nested,0,depth+1);self.event(8);return 0
  helper=self.helpers.get(target)
  if helper=='__divdi3':
   a=values(4);n=signed(a[0]|(a[1]<<32),64);d=signed(a[2]|(a[3]<<32),64);q=divide(n,d)
   self.event(4,*a,q&MASK,(q>>32)&MASK);return q&MASK,(q>>32)&MASK
  if helper=='rxiq_set_reg':
   c,m=values(2);require(m in (0,1),'Invalid coefficient mode');v=signed(c,8 if self.chip=='esp32s3' else 32)
   if m:v=max(-15,min(15,divide(v,2)))*2
   else:v=max(-31,min(31,v))
   result=v&(255 if self.chip=='esp32s3' else MASK);self.event(3,c,m,result);self.mutate();return result
  if helper=='phy_printf':
   a=values(4);require(a[0] in {int(row['address'],0) for row in self.e['logs']},'Unknown format');self.event(6,*a[1:]);self.mutate();return 0
  require(0x71000000<=target<0x71400000,f'Unknown helper {target:x}')
  offset=(target-0x71000000)%0x1000;slots=([0xf0,0xf4] if self.chip=='esp32s3' else [0x104,0x108]);require(offset in slots,'Unknown callback')
  n=2 if offset==slots[0] else 0;args=values(n)
  if n:require(args[0]==1 and args[1]<=65535,'Invalid estimator arguments')
  self.event(5,target,n,*args);self.mutate();return 0
 def run(self,c):
  require(len(c)==12 and all(0<=v<=MASK for v in c),'Invalid case');require(c[0] in self.entries and c[10]<=3,'Invalid entry/output')
  self.c=c;self.mem={};self.trace=[];self.locals=[];self.steps=self.generation=self.mutations=0
  for a,v in zip(MMIO,c[3:8]):self.put(a,4,v)
  self.put(self.table,4,0x70000000);self.put(0x300000,4,0xa5a5a5a5)
  for row in self.e['logs']:require(hashlib.sha256(bytes.fromhex(row['bytes'])).hexdigest()==row['sha256'],'Format hash')
  a,b=(self.actual(x) for x in outputs(c));args=[c[1],a,c[2]] if c[0]==0 else [c[1],a,b,c[2]]
  r=self.registers();base=2 if self.chip=='esp32s3' else 0
  for i,v in enumerate(args):r[f'a{base+i}']=v
  self.execute(self.entries[c[0]],r,c[0]);return self.trace

def cases(chip):
 for kind in (0,1):
  c=[kind,2,1,300,100,20,80,0x81234567,0,1,0,0x13579bdf];yield c
  for index,vals in [(1,[0,1,2,3,7,15,16,31,32,33,255,256,257,MASK]),(2,[0,1,255,256,257,MASK]),(8,[0,1,0xffffffff,0x12345678]),(9,[0,1]),(10,[0,1,2,3])]:
   for v in vals:d=list(c);d[index]=v;yield d
  for mode in (0,2,3,31,32,255):
   for values in [(0,0,0,0),(1,0,0,0),(0x80000000,0,0,0x80000000),(MASK,0,0,0),(0x7fffffff,1,MASK,0x80000000),(0x80000000,0x80000000,0x80000000,0x80000000)]:
    d=list(c);d[1]=mode;d[3:7]=values;yield d
 seed=0x52584951
 def word():
  nonlocal seed
  seed^=(seed<<13)&MASK;seed^=seed>>17;seed^=(seed<<5)&MASK;seed&=MASK;return seed
 for i in range(2048):yield [i%2,word(),word(),word(),word(),word(),word(),word(),word() if i%3 else 0,word()%2,word()%4,word()]

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
