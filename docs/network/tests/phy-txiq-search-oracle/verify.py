"""Ordered TX IQ boundaries with adversarial helpers; no analog behavior model."""
from pathlib import Path
import hashlib,json,random
import machine
ROOT=Path(__file__).resolve().parent
M=0xffffffff
OUT=0x200000
TABLES=(0x310000,0x310800)
REGS=(0x60006040,0x6000607c)
S=machine.signed
KINDS=('abs','loopback','pbus_write','pbus_read','dco')
def slots(chip):return (0xec,36,0x1a8,0x1ac,0x1cc) if chip=='esp32s3' else (0x100,36,0x1cc,0x1d0,0x1f0)
def cb(table,version,kind):return 0x500000+table*4096+version*256+kind*16

class Boundary:
 def __init__(self,chip,e,c):
  self.chip,self.e,self.case=chip,e,c
  self.param=int(e['symbols']['phy_param']['address'],0);self.table=int(e['symbols']['g_phyFuns']['address'],0)
  self.extent=740 if chip=='esp32s3' else 848
  self.memory={};self.trace=[];self.calls=0;self.abs_calls=0;self.samples=[];self.coefficients=None;self.stack=0x10ff00
  for i in range(self.extent):self.put(self.param+i,1,c['seed']+17*i)
  self.put(self.param+162,1,c['selector']);self.put(self.param+832,2,c['offset']) if chip=='esp32c3' else None
  for i,a in enumerate(REGS):self.put(a,4,c['registers'][i])
  self.output_effect(c['seed']);self.put(self.table,4,TABLES[0]);self.set_slots(0)
 def put(self,a,w,v):
  for i in range(w):self.memory[a+i]=(v>>(8*i))&255
 def get(self,a,w):
  machine.require(all(a+i in self.memory for i in range(w)),('uninitialized memory',hex(a),w))
  return sum(self.memory[a+i]<<(8*i) for i in range(w))
 def set_slots(self,version):
  for i,t in enumerate(TABLES):
   for k,o in enumerate(slots(self.chip)):self.put(t+o,4,cb(i,version,k))
 def output_effect(self,seed):
  for i in range(32):self.put(OUT+i,1,seed+17*i)
 def where(self,a,w):
  if a in self.samples and w==2:return ['sample',self.samples.index(a)]
  if self.coefficients is not None and self.coefficients<=a and a+w<=self.coefficients+2:return ['coefficient',a-self.coefficients]
  if 0x100000<=a and a+w<=0x110000:return None
  if OUT<=a and a+w<=OUT+32:return ['out',a-OUT]
  if a in REGS and w==4:return ['reg',a]
  if self.param<=a and a+w<=self.param+self.extent:return ['param',a-self.param]
  if a==self.table and w==4:return ['table']
  for i,t in enumerate(TABLES):
   for o in slots(self.chip):
    if a==t+o and w==4:return ['slot',i,o]
  raise ValueError(('unknown memory',hex(a),w))
 def read(self,a,w):
  loc=self.where(a,w);v=self.get(a,w)
  if loc is not None:self.trace.append(['read',w,loc,v])
  return v
 def write(self,a,w,v):
  loc=self.where(a,w);v&=(1<<(8*w))-1
  if loc is not None:self.trace.append(['write',w,loc,v])
  self.put(a,w,v)
 def stack_buffer(self,a,w,alignment):
  machine.require(self.stack<=a and a+w<=0x10ff00 and a%alignment==0,('Invalid stack buffer',hex(a),w,alignment))
 def user_buffer(self,a,w,alignment):machine.require(OUT<=a and a+w<=OUT+32 and a%alignment==0,'Invalid caller buffer')
 def helper(self,name,args):
  args=[v&M for v in args];n=self.calls;machine.require(n<48,'Helper budget exhausted')
  effect=self.case['effects'][n];ret=self.case['returns'][n]
  if name=='txiq_get_mis_pwr':
   machine.require(len(args)==5,'Bad measurement arity');self.samples=args[3:5]
   for a in self.samples:self.stack_buffer(a,2,2)
   machine.require(self.samples[0]!=self.samples[1],'Measurement outputs unexpectedly alias')
   args=args[:3]+[0x220000,0x220002]
  if name=='txiq_cover':
   machine.require(len(args)==3,'Bad cover arity');self.stack_buffer(args[2],2,1);self.coefficients=args[2];args=args[:2]+[0x230000]
  if name=='txdc_cal_v70' or name.startswith('dco'):self.user_buffer(args[0],8,2)
  self.trace.append(['call',name,args])
  if name.startswith('abs'):
   policy=self.case['policy']
   if policy==0:ret=abs(S(args[0]))&M
   elif policy==1:ret=0
   elif policy==2:ret=2
   elif policy==3:ret=0 if self.abs_calls%2==0 else 2
   self.abs_calls+=1
  for a,v in zip(REGS,effect[:2]):self.put(a,4,v)
  self.put(self.param+162,1,effect[2])
  if self.chip=='esp32c3':self.put(self.param+832,2,effect[2]>>16)
  self.output_effect(effect[3]);self.put(self.table,4,TABLES[effect[4]&1]);self.set_slots((effect[4]>>1)&1)
  for i,a in enumerate(self.samples):self.put(a,2,effect[5]>>(16*i))
  if self.coefficients is not None:
   self.put(self.coefficients,1,effect[5]);self.put(self.coefficients+1,1,effect[5]>>16)
  self.trace.append(['effect',effect]);self.calls+=1;return ret&M
 def final(self):
  return [[self.get(a,4) for a in REGS],[self.get(OUT+i,1) for i in range(32)],
          self.get(self.param+162,1),self.get(self.param+832,2) if self.chip=='esp32c3' else 0,
          self.get(self.table,4),[self.get(t+o,4) for t in TABLES for o in slots(self.chip)]]

class Original(Boundary,machine.Machine):
 def __init__(self,chip,e,c):
  Boundary.__init__(self,chip,e,c);self.program,self.starts=machine.decode(e);self.kinds=dict(zip(self.starts,(0,1)));self.visited=set();self.branches=set();self.steps=0
  names=['txiq_set_reg','txiq_get_mis_pwr','txdc_cal_v70','get_power_atten','txcal_debuge_mode','txcal_work_mode']
  self.helpers={int(e['symbols'][n]['address'],0):n for n in names};self.helpers[self.starts[0]]='txiq_cover'
  for t in range(2):
   for v in range(2):
    for k,name in enumerate(KINDS):self.helpers[cb(t,v,k)]=name+str(t*2+v)
 def enter(self,kind,stack):machine.require(0x100000<=stack<0x10ff00 and stack%16==0,'Invalid frame');self.stack=stack
 def dispatch(self,target,values,r,depth):
  machine.require(target in self.helpers,('Unknown call',hex(target)))
  name=self.helpers[target]
  if name.startswith(('abs','loopback','dco')):arity=1
  elif name.startswith('pbus_write'):arity=3
  elif name.startswith('pbus_read'):arity=2
  else:arity={'txiq_set_reg':2,'txiq_get_mis_pwr':5,'txdc_cal_v70':1,'get_power_atten':5,'txcal_debuge_mode':0,'txcal_work_mode':0,'txiq_cover':3}[name]
  return self.helper(name,values(arity))
 def run(self):
  r=self.registers();saved=r.copy();base=2 if self.chip=='esp32s3' else 0
  for i,v in enumerate(self.case['args'][:3 if self.case['kind']==0 else 6]):r['a'+str(base+i)]=v&M
  self.execute(self.starts[self.case['kind']],r,self.case['kind'])
  if self.chip=='esp32c3':machine.require(all(r[k]==saved[k] for k in ['sp','ra']+[f's{i}' for i in range(12)]),'C3 callee ABI changed')
  else:machine.require(r['a1']==self.stack,'S3 frame changed')

def quotient(n,d):machine.require(d!=0,'Zero denominator');return (abs(n)//abs(d))*(-1 if (n<0)!=(d<0) else 1)
class Model(Boundary):
 def live(self,k,args):
  t=self.read(self.table,4);p=self.read(t+slots(self.chip)[k],4);return self.indirect(p,k,args)
 def indirect(self,p,k,args):
  for t in range(2):
   for v in range(2):
    if p==cb(t,v,k):return self.helper(KINDS[k]+str(t*2+v),args)
  raise ValueError('Invalid callback')
 def run(self):
  if self.case['kind']==0:self.search()
  else:self.calibrate()
 def search(self):
  s3=self.chip=='esp32s3';atten,tone,out=self.case['args'][:3]
  if s3:atten&=255;tone=S(tone,16)
  reduced=max(S(atten-12,8),0);first=second=sum1=sum2=0;self.stack=0x10fe00
  for i in range(7):
   first=self.helper('txiq_set_reg',[S(first,8) if s3 else first,1]);first=first&255 if s3 else first
   second=self.helper('txiq_set_reg',[S(second,8) if s3 else second,0]);second=second&255 if s3 else second
   self.helper('txiq_get_mis_pwr',[1,reduced,tone,self.stack,self.stack+2])
   if s3:x=S(self.read(self.stack,2),16);y=S(self.read(self.stack+2,2),16)
   else:y=S(self.read(self.stack+2,2),16);x=S(self.read(self.stack,2),16)
   den=min(x,y) or 1;correction=((quotient((y-x)*2048,den)+16)>>5)&255;self.write(out,1,correction)
   self.helper('txiq_get_mis_pwr',[0,atten,tone,self.stack,self.stack+2]);x=S(self.read(self.stack,2),16);y=S(self.read(self.stack+2,2),16)
   den=S(x+y,16) or 1;correction=((quotient((x-y)*4096,den)+16)>>5)&255
   if s3:self.write(out+1,1,correction);delta=self.read(out,1)
   else:delta=self.read(out,1);self.write(out+1,1,correction)
   if i<3:first=S(first-delta,8);second=S(second-correction,8)
   else:
    sum1=S(sum1+delta,8);sum2=S(sum2+correction,8)
    if S(self.live(0,[S(delta,8)]))<=1:
     t=self.read(self.table,4);d=S(self.read(out+1,1),8);p=self.read(t+slots(self.chip)[0],4)
     if S(self.indirect(p,0,[d]))<=1:break
    if i==6:first=S(first-((sum1+2)>>2),8);second=S(second-((sum2+2)>>2),8)
  self.helper('txiq_set_reg',[S(first,8) if s3 else first,1]);self.helper('txiq_set_reg',[S(second,8) if s3 else second,0])
  if s3:self.write(out,1,first);self.write(out+1,1,second)
  else:self.write(out+1,1,second);self.write(out,1,first)
 def calibrate(self):
  s3=self.chip=='esp32s3';initial,dc,iq,tone,atten,mode=self.case['args'];self.stack=0x10fe00
  target=56 if s3 else 30 if ((self.read(self.param+162,1)-16)&255)<=1 else 56
  if s3:initial&=65535;mode&=255;tone&=255;atten=S(atten,8)
  else:tone=S(tone,16)
  self.write(REGS[1],4,self.read(REGS[1],4)|0x800);self.write(REGS[1],4,self.read(REGS[1],4)&~0x1000);self.helper('txcal_debuge_mode',[])
  self.live(2,[1,2,initial])
  if mode==1:
   t=self.read(self.table,4);w=self.read(t+slots(self.chip)[2],4);r=self.read(t+slots(self.chip)[3],4)
   value=self.indirect(r,3,[1,1]);self.indirect(w,2,[1,1,(value|2)&65535])
   if s3:self.live(2,[4,2,24])
  if mode==2:self.live(1,[1]);self.helper('txdc_cal_v70',[dc])
  else:self.live(4,[dc])
  offset=224 if s3 else self.read(self.param+832,2);saved=self.read(REGS[0],4)
  code=self.helper('get_power_atten',[tone,atten,target,offset,0]);self.helper('txiq_cover',[code&255,tone,self.stack]);self.helper('txcal_work_mode',[])
  for i,limit in ((0,15),(1,31)):
   value=S(self.read(self.coefficients+i,1),8)
   if value>limit:self.write(self.coefficients+i,1,limit)
   elif value< -limit:self.write(self.coefficients+i,1,-limit)
  x=self.read(self.coefficients,1);y=self.read(self.coefficients+1,1);self.write(iq,2,((x&31)<<6)|(y&63));self.write(REGS[0],4,saved)
  if mode==2:self.live(1,[0])
  self.write(REGS[1],4,self.read(REGS[1],4)|0x1000)

def cases():
 rng=random.Random(90215)
 def new(kind,args,pair=None,policy=4,selector=None):
  effects=[[rng.getrandbits(32),rng.getrandbits(32),rng.getrandbits(32),rng.getrandbits(32),rng.randrange(4),rng.getrandbits(32) if pair is None else (pair[0]&65535)|((pair[1]&65535)<<16)] for _ in range(48)]
  return dict(kind=kind,args=[v&M for v in args],selector=rng.randrange(256) if selector is None else selector,offset=rng.randrange(65536),seed=rng.getrandbits(32),registers=[rng.getrandbits(32) for _ in range(2)],policy=policy,returns=[rng.getrandbits(32) for _ in range(48)],effects=effects)
 codes=[-1,0,11,12,127,128,139,140,255,256,0x7fffffff,0x80000000]
 pairs=[(0,0),(1,1),(0,1),(1,0),(-1,1),(1,-1),(-32768,32767),(32767,-32768),(32767,32767),(-32768,-32768),(-1,-2),(-2,-1)]
 for policy in range(5):
  for code in codes:
   for pair in pairs:yield new(0,[code,rng.getrandbits(32),OUT,0,0,0],pair,policy)
 for code in range(256):yield new(0,[code,rng.getrandbits(32),OUT,0,0,0])
 for mode in (0,1,2,3,256,257,258,M):
  for selector in (0,15,16,17,18,255):
   for pair in [(0,0),(-15,-31),(15,31),(-16,-32),(16,32),(-128,127),(127,-128),(1,-1)]:
    yield new(1,[rng.getrandbits(32),OUT,OUT+rng.choice([0,2,6,8]),rng.getrandbits(32),rng.getrandbits(32),mode],pair,selector=selector)
 for i in range(256):yield new(1,[rng.getrandbits(32),OUT,OUT+rng.choice([0,2,6,8]),i,i,rng.choice([0,1,2,M])],selector=i)

def verify():
 records={}
 for chip in ('esp32c3','esp32s3'):
  e=json.loads((ROOT/(chip+'-instructions.json')).read_text());program,_=machine.decode(e);visited=set();branches=set();digest=hashlib.sha256()
  for n,c in enumerate(cases(),1):
   a,b=Original(chip,e,c),Model(chip,e,c)
   try:
    a.run();b.run();machine.require([a.trace,a.final()]==[b.trace,b.final()],('Model mismatch',chip,n))
   except Exception:
    (ROOT/(chip+'-model-failure.json')).write_text(json.dumps(dict(index=n,case=c,original=a.trace,model=b.trace,original_final=a.final(),model_final=b.final()),indent=2)+'\n');raise
   visited|=a.visited;branches|=a.branches;digest.update(json.dumps([c,a.trace,a.final()],separators=(',',':')).encode()+b'\n')
  edges={(pc,t) for pc,(_,op,_) in program.items() if op in machine.CONDITIONAL for t in (False,True)}
  row=dict(cases=n,instructions=len(program),covered=len(visited),edges=len(edges),covered_edges=len(branches),uncovered_pcs=[hex(v) for v in sorted(set(program)-visited)],uncovered_edges=[[hex(pc),t] for pc,t in sorted(edges-branches)],trace_sha256=digest.hexdigest())
  machine.require(visited==set(program) and branches==edges,('Incomplete coverage',chip,row));records[chip]=row;print(chip,row,flush=True)
 return records
if __name__=='__main__':machine.require(verify()==json.loads((ROOT/'expected-results.json').read_text()),'Corpus digest changed')
