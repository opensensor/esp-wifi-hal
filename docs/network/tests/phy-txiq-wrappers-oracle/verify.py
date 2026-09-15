"""Ordered TX IQ wrapper boundaries; helpers are adversarial stubs, not RF models."""
from pathlib import Path
import hashlib,json,random
import machine
ROOT=Path(__file__).resolve().parent
M=0xffffffff
PARAM=0x200000
SCRATCH=0x210000
TABLES=(0x310000,0x310400)
def callback(table,version,write): return 0x320000+table*256+version*32+write*16

class Boundary:
 def __init__(self,chip,e,c):
  self.chip,self.e,self.case=chip,e,c
  self.param=int(e['symbols']['phy_param']['address'],0)
  self.table=int(e['symbols']['g_phyFuns']['address'],0)
  self.extent=740 if chip=='esp32s3' else 848
  self.read_slot,self.write_slot=(0x188,0x190) if chip=='esp32s3' else (0x1ac,0x1b4)
  self.memory={};self.trace=[];self.calls=0;self.analog=[0xa5a5a5a5,0x5a5a5a5a];self.scratch=None
  for i in range(self.extent):self.put(self.param+i,1,c['seed']+17*i)
  self.put(self.param+288,4,c['flags']);self.put(self.param+216,1,c['atten'])
  self.put(self.table,4,TABLES[0]);self.slots(0)
 def slots(self,version):
  for i,table in enumerate(TABLES):
   for w,offset in enumerate((self.read_slot,self.write_slot)):self.put(table+offset,4,callback(i,version,w))
 def put(self,a,w,v):
  for i in range(w):self.memory[a+i]=(v>>(8*i))&255
 def get(self,a,w):
  machine.require(all(a+i in self.memory for i in range(w)),('uninitialized memory read',hex(a),w))
  return sum(self.memory[a+i]<<(8*i) for i in range(w))
 def where(self,a,w):
  if 0x100000<=a and a+w<=0x110000:return None
  if self.param<=a and a+w<=self.param+self.extent:return ['param',a-self.param]
  if a==self.table and w==4:return ['table']
  for i,t in enumerate(TABLES):
   for offset in (self.read_slot,self.write_slot):
    if a==t+offset and w==4:return ['slot',i,offset]
  raise ValueError(('unknown location',hex(a),w))
 def read(self,a,w):
  where=self.where(a,w);v=self.get(a,w)
  if where is not None:self.trace.append(['read',w,where,v])
  return v
 def write(self,a,w,v):
  where=self.where(a,w);v&=(1<<(w*8))-1
  if where is not None:self.trace.append(['write',w,where,v])
  self.put(a,w,v)
 def output(self,a,w):
  machine.require(a%2==0,'Unaligned output')
  if self.param<=a and a+w<=self.param+self.extent:return PARAM+a-self.param
  machine.require(self.stack<=a and a+w<=0x10ff00,'Scratch exceeds active frame')
  machine.require(w==8,'Unexpected scratch output extent')
  self.scratch=a
  return SCRATCH
 def helper(self,name,args):
  args=[v&M for v in args];n=self.calls
  machine.require(n<7,'Too many helper calls')
  effect=self.case['effects'][n];result=self.case['returns'][n]
  if name=='rfcal_txiq':
   machine.require(len(args)==6 and args[0]==0,'Invalid calibration ABI')
   raw1,raw2=args[1:3];args[1]=self.output(raw1,8);args[2]=self.output(raw2,2)
  self.trace.append(['call',name,args])
  if name.startswith('write'):
   machine.require(args[:2]==[103,0 if self.chip=='esp32s3' else 1] and args[2] in (28,29),'Invalid analog write')
   self.analog[args[2]-28]=args[3]
  elif name.startswith('read'):
   machine.require(args[:2]==[103,0 if self.chip=='esp32s3' else 1] and args[2] in (28,29),'Invalid analog read')
  else:
   machine.require(name=='rfcal_txiq','Unknown helper')
   # Output-only scratch contract: two halfwords per outer pass, twice.
   for i in range(4):self.put(raw1+2*i,2,effect[4]+i*257)
   self.put(raw2,2,effect[4]>>16)
  self.put(self.param+288,4,effect[0]);self.put(self.param+216,1,effect[1])
  self.put(self.table,4,TABLES[effect[2]&1]);self.slots(effect[3]&1)
  self.trace.append(['effect',effect]);self.calls+=1
  return result
 def final(self):
  return [[self.get(self.param+i,1) for i in range(self.extent)],self.get(self.table,4),
          [self.get(t+o,4) for t in TABLES for o in (self.read_slot,self.write_slot)],self.analog]

class Original(Boundary,machine.Machine):
 def __init__(self,chip,e,c):
  Boundary.__init__(self,chip,e,c);self.program,self.starts=machine.decode(e);self.kinds=dict(zip(self.starts,(0,1)))
  self.steps=0;self.visited=set();self.branches=set();self.stack=0x10ff00
  self.helpers={int(e['symbols']['rfcal_txiq']['address'],0):'rfcal_txiq'}
  for i in range(2):
   for v in range(2):
    for w in range(2):self.helpers[callback(i,v,w)]=('write' if w else 'read')+str(i*2+v)
 def enter(self,kind,stack):
  machine.require(0x100000<=stack<0x10ff00 and stack%16==0,'Invalid frame');self.stack=stack
 def dispatch(self,target,values,r,depth):
  machine.require(target in self.helpers,('Unknown call target',hex(target)))
  name=self.helpers[target];n=6 if name=='rfcal_txiq' else 4 if name.startswith('write') else 3
  return self.helper(name,values(n))
 def run(self):
  r=self.registers();saved=r.copy();kind=self.case['kind']
  self.execute(self.starts[kind],r,kind)
  if self.chip=='esp32c3':
   machine.require(all(r[k]==saved[k] for k in ['sp','ra']+[f's{i}' for i in range(12)]),'C3 callee ABI changed')
  else:machine.require(r['a1']==self.stack,'S3 frame changed before window return')

class Model(Boundary):
 def run(self):
  p=self.param;s3=self.chip=='esp32s3';kind=self.case['kind'];bit=11 if kind else 14
  if self.read(p+288,4)&(1<<bit):return
  if not kind:
   initial=max(machine.signed(self.read(p+216,1),8),0)
   self.helper('rfcal_txiq',[0,p+0x124,p+0x14c,128,initial,0])
   self.stack=0x10fe00
   self.helper('rfcal_txiq',[0,self.stack,p+0x162,128,max(initial-20,0),2])
  else:
   def analog(reg,value=None):
    t=self.read(self.table,4);w=int(value is not None);offset=self.write_slot if w else self.read_slot
    ptr=self.read(t+offset,4);i=(ptr-0x320000)//256;v=((ptr-0x320000)%256)//32
    machine.require(ptr==callback(i,v,w),'Wrong callback slot')
    return self.helper(('write' if w else 'read')+str(i*2+v),[103,0 if s3 else 1,reg]+([] if value is None else [value]))
   first=analog(28);second=analog(29);analog(28,0);analog(29,0)
   code=machine.signed(self.read(p+216,1)+(0 if s3 else 20),8)
   self.helper('rfcal_txiq',[0,p+0x182,p+0x180,32,code,1])
   flags=self.read(p+288,4)
   if s3:self.write(p+288,4,flags|(1<<bit))
   table=self.read(self.table,4)
   if not s3:self.write(p+288,4,flags|(1<<bit))
   ptr=self.read(table+self.write_slot,4);i=(ptr-0x320000)//256;v=((ptr-0x320000)%256)//32
   self.helper('write'+str(i*2+v),[103,0 if s3 else 1,28,first]);analog(29,second)
   return
  self.write(p+288,4,self.read(p+288,4)|(1<<bit))

def cases():
 rng=random.Random(90214)
 for kind in range(2):
  bit=11 if kind else 14
  for flag in (0,1<<bit,M^(1<<bit),M):
   for attenuation in range(256):
    # Both entry bytes and Bluetooth's post-callback byte cover all 256 values.
    effects=[[rng.getrandbits(32),rng.randrange(256),rng.randrange(2),rng.randrange(2),rng.getrandbits(32)] for _ in range(7)]
    effects[3][1]=attenuation
    yield dict(kind=kind,flags=flag,atten=attenuation,seed=rng.getrandbits(32),returns=[rng.getrandbits(32) for _ in range(7)],effects=effects)

def verify():
 records={}
 for chip in ('esp32c3','esp32s3'):
  e=json.loads((ROOT/(chip+'-instructions.json')).read_text());program,_=machine.decode(e)
  visited=set();branches=set();digest=hashlib.sha256()
  for n,c in enumerate(cases(),1):
   a,b=Original(chip,e,c),Model(chip,e,c);a.run();b.run()
   machine.require([a.trace,a.final()]==[b.trace,b.final()],('model mismatch',chip,n,a.trace,b.trace))
   visited|=a.visited;branches|=a.branches;digest.update(json.dumps([c,a.trace,a.final()],separators=(',',':')).encode()+b'\n')
  edges={(pc,t) for pc,(_,op,_) in program.items() if op in machine.CONDITIONAL for t in (False,True)}
  row=dict(cases=n,instructions=len(program),covered=len(visited),edges=len(edges),covered_edges=len(branches),
           uncovered_pcs=[hex(v) for v in sorted(set(program)-visited)],uncovered_edges=[[hex(pc),t] for pc,t in sorted(edges-branches)],trace_sha256=digest.hexdigest())
  machine.require(visited==set(program) and branches==edges,('Original coverage incomplete',row));records[chip]=row
 return records
if __name__=='__main__':
 records=verify();machine.require(records==json.loads((ROOT/'expected-results.json').read_text()),'Corpus digest differs');print(json.dumps(records,indent=2))
