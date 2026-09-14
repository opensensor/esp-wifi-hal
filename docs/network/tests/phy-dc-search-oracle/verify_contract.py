"""Ordered external-memory/callback contract for the two receive DC searches.

The callback estimator/minimum, PBUS, delay, printf, abs and limit helpers are
modeled boundaries. Private stack spills/loads and nonvolatile readonly loads
are excluded; caller buffers, callback arguments/results and table generations
are observed. This does not prove analog, RF or timing equivalence.
"""
import hashlib,json,random
from pathlib import Path
from machine import Machine,decode,require,signed,CONDITIONAL,MASK
HERE=Path(__file__).resolve().parent
COEFF,OUT,STATUS=0x300002,0x310000,0x320000
LOCAL0,LOCAL1=0x500000,0x500100
s16=lambda x:signed(x,16)
s32=lambda x:signed(x)
def shift(x,n):return s32(x)>>(n&31)
def trunc2(x):
 x=s32(x);return (abs(x)//2)*(-1 if x<0 else 1)
class Search(Machine):
 def __init__(self,chip,e):
  self.chip,self.e,self.s3=chip,e,chip=='esp32s3'
  self.program,self.entries=decode(e);self.kinds={v:k for k,v in enumerate(self.entries)}
  self.table=int(e['symbols']['g_phyFuns']['address'],0)
  self.delay=int(e['symbols']['ets_delay_us']['address'],0)
  self.minimum=int(e['symbols']['__opensensor_rx_dc_minimum']['address'],0)
  self.printf=int(e['symbols']['phy_printf']['address'],0)
  self.coarse=int(e['readonly'][0]['address'],0)
  self.formats={int(v['address'],0):i for i,v in enumerate(e['logs'])}
  self.slots={'read':0x1ac if self.s3 else 0x1d0,'force':0x1a8 if self.s3 else 0x1cc,'estimate':0xf8 if self.s3 else 0x10c,'abs':0xec if self.s3 else 0x100,'limit':40}
 def put(self,a,w,v):
  for i in range(w):self.mem[a+i]=(v>>(8*i))&255
 def get(self,a,w):
  if 0x70000000<=a<0x71000000:
   require(w==4 and a%4==0,'Invalid table slot');return a+0x1000000
  require(all(a+i in self.mem for i in range(w)),f'Uninitialized read {a:x}/{w}')
  return sum(self.mem[a+i]<<(8*i) for i in range(w))
 def canonical(self,a):
  for p,tag in self.locals:
   if p<=a<p+12:return tag+a-p
  return a
 def observed(self,a):return 0x300000<=a<0x300020 or OUT<=a<OUT+16 or STATUS<=a<STATUS+4
 def read(self,a,w):
  v=self.get(a,w)
  if self.observed(a):self.trace.append(['read',a,w,v])
  elif not (0x100000<=a<0x110000 or a==self.table or 0x70000000<=a<0x71000000 or self.coarse<=a<self.coarse+6):
   raise ValueError(f'Outside documented memory domain {a:x}/{w}')
  return v
 def write(self,a,w,v):
  v&=(1<<(w*8))-1
  if self.observed(a):self.trace.append(['write',a,w,v])
  else:require(0x100000<=a<0x110000 or a==self.table,'Invalid write')
  self.put(a,w,v)
 def enter(self,kind,sp):
  self.scratch=sp+(16 if self.s3 else 52) if kind==0 else sp+(12 if self.s3 else 56)
  self.second=sp+(0 if self.s3 else 68)
  self.locals=[(self.scratch,LOCAL0)] if kind==0 else [(self.scratch,LOCAL0),(self.second,LOCAL1)]
 def target(self,kind):return self.read(self.read(self.table,4)+self.slots[kind],4)
 def call(self,kind,args,target=None):
  if target is None:target=self.target(kind) if kind in self.slots else {'delay':self.delay,'minimum':self.minimum,'log':self.printf}[kind]
  if kind in self.slots:
   require(target==0x71000000+self.generation*0x1000+self.slots[kind],'Cached or wrong callback target')
  normalized=[self.canonical(x) if kind in ('estimate','minimum') and i==2 else x&MASK for i,x in enumerate(args)]
  if kind=='minimum':normalized[1]=0 # proven unused by the separately tested selector
  self.trace.append(['call',kind,target if kind in self.slots else 0,*normalized])
  if kind=='read':
   result=self.c['state'][self.reads];self.reads+=1
  elif kind in ('estimate','minimum'):
   index=self.estimates;self.estimates+=1
   require(index<32,'Estimate budget exceeded')
   require(args[:2]==[1,self.samples] if kind=='estimate' else args[0]==self.samples,'Estimator scalar ABI')
   self.last_buffer=args[2]
   for i,v in enumerate(self.c['estimates'][index%len(self.c['estimates'])]):self.write(args[2]+4*i,4,v)
   result=0
  elif kind=='abs':
   mode=self.c.get('abs_values')
   result=(mode[self.abs_calls%len(mode)] if mode else abs(s32(args[0])))&MASK;self.abs_calls+=1
  elif kind=='limit':result=max(s32(args[2]),min(s32(args[1]),s32(args[0])))&MASK
  else:result=0
  # Mutations model externally callable helpers retaining caller-buffer access.
  if self.c.get('mutate') and kind in ('force','abs','limit'):
   address=[self.coeff,self.coeff+2,self.out,self.out+4,self.status][self.calls%5]
   width=2 if address in (self.coeff,self.coeff+2) else 1 if address==self.status else 4
   self.write(address,width,self.get(address,width)^(0x1357+self.calls))
  self.calls+=1
  if self.c['table_mutation']:
   self.generation+=1;self.put(self.table,4,0x70000000+self.generation*0x1000)
  self.trace.append(['return',result&MASK]);return s32(result)
 def dispatch(self,target,values,registers,depth):
  if 0x71000000<=target<0x72000000:
   slot=(target-0x71000000)%0x1000
   name=next((k for k,v in self.slots.items() if v==slot),None)
   require(name is not None,'Unknown table callback')
   return self.call(name,values({'read':2,'force':3,'estimate':3,'abs':1,'limit':3}[name]),target)
  if target==self.delay:return self.call('delay',values(1),target)
  if target==self.minimum:return self.call('minimum',values(3),target)
  if target==self.printf:
   a=values(1)[0];require(a in self.formats,'Unknown format');kind=self.formats[a]
   return self.call('log',[kind,*values([3,3,7,1][kind])[1:]],target)
  raise ValueError(f'Unknown helper {target:x}')
 def init(self,c):
  self.c=c;self.mem={};self.locals=[];self.trace=[];self.steps=self.calls=self.reads=self.estimates=self.abs_calls=self.generation=0
  self.visited,self.branches=set(),set();self.last_buffer=None
  self.coeff=COEFF;self.out=OUT;self.status=STATUS
  if c.get('alias')==1:self.coeff=OUT+2
  if c.get('alias')==2:self.status=self.coeff+1
  if c.get('alias')==3:self.status=OUT+8
  for a,n in [(0x300000,32),(OUT,16),(STATUS,4)]:
   for i in range(n):self.put(a+i,1,0xa5)
  for i,v in enumerate(c['coeff']):self.put(self.coeff+2*i,2,v)
  self.put(self.table,4,0x70000000)
  for i,v in enumerate(bytes.fromhex(self.e['readonly'][0]['bytes'])):self.put(self.coarse+i,1,v)
  self.samples=c['samples']&(65535 if self.s3 else MASK)
 def run(self,c,model=False):
  self.init(c)
  if model:
   self.enter(c['kind'],0x10fe00)
   if c['kind']==0:self.general()
   else:self.one_step()
  else:
   r=self.registers();args=([c['samples'],self.coeff,c['delay'],*c['logs']] if c['kind']==0 else [c['policy'],c['mode'],c['samples'],self.coeff,self.out,self.status])
   for i,v in enumerate(args):r[f'a{i+(2 if self.s3 else 0)}']=v&MASK
   self.execute(self.entries[c['kind']],r,c['kind'])
  return self.trace
 def absolute(self,value):return self.call('abs',[value&MASK])
 def general(self):
  c=self.c;state=self.call('read',[1,2]);low=(state&15).bit_count();total=(state&63).bit_count();index=(state>>6)&255
  self.call('force',[2,2,256]);self.call('force',[3,2,256])
  high_threshold=15 if total>2 else 5;low_threshold=5 if total>3 else 2;fine_shift=(low+5 if low else 4)+2
  coeff=[s16(self.read(self.coeff,2)*2),s16(self.read(self.coeff+2,2)*2)]
  verbose,debug=[x&(255 if self.s3 else MASK) for x in c['logs']]
  for phase in range(2):
   if phase:coeff=[512,512]
   threshold=low_threshold if phase else high_threshold
   pointer=self.coeff+4*phase;limit=4 if phase else 12;previous=[0,0]
   for attempt in range(limit):
    for i in range(2):
     target=self.target('force');value=(coeff[i]+1)>>1
     self.write(pointer+2*i,2,value);self.call('force',[2+i,phase+1,value&65535],target)
    self.call('delay',[c['delay']&(65535 if self.s3 else MASK)])
    self.call('estimate',[1,self.samples,self.scratch])
    if debug:
     second=s16(self.read(pointer+2,2));first=s16(self.read(pointer,2));self.call('log',[0,first,second])
     self.call('log',[1,self.read(self.scratch,4),self.read(self.scratch+4,4)])
    if self.absolute(self.read(self.scratch,4))<=threshold and self.absolute(self.read(self.scratch+4,4))<=threshold:break
    if attempt==0:previous=[s32(self.read(self.scratch+4*i,4)) for i in range(2)]
    amount=total+6
    for i in range(2):
     value=self.read(self.scratch+4*i,4)
     if self.absolute(value)>threshold:
      if phase:delta=shift(280*self.read(self.scratch+4*i,4),fine_shift)
      else:
       distance=self.absolute(self.read(self.scratch+4*i,4)-previous[i])
       scaled=self.absolute(trunc2(3*self.read(self.scratch+4*i,4)))
       if scaled<distance:amount=(amount+1)&255
       gain=self.read(self.coarse+index,1);delta=shift(gain*self.read(self.scratch+4*i,4)*6,amount+2)
      coeff[i]=s16(coeff[i]-delta)
    coeff=[min(1022,max(0,x)) for x in coeff]
    previous=[s32(self.read(self.scratch+4*i,4)) for i in range(2)]
   else:attempt=limit
   if verbose:self.call('log',[2,phase+1,total,index,self.read(self.scratch,4),self.read(self.scratch+4,4),attempt])
   if debug:self.call('log',[3])
  if verbose:self.call('log',[3])
 def one_step(self):
  c=self.c;policy=c['policy']&(255 if self.s3 else MASK);mode=c['mode']&(255 if self.s3 else MASK)
  first=s16(self.read(self.coeff,2));second=s16(self.read(self.coeff+2,2))
  for p in [self.scratch,self.second]:
   for i in range(3):self.write(p+4*i,4,0)
  state=self.call('read',[1,2])&255;backup=self.call('read',[0,1])&MASK;gain=(state&63).bit_count()
  threshold=max(1,gain-1) if mode==1 else (10 if self.s3 else 6) if policy else 1
  bank=2 if mode==1 else 1;limit=8 if mode==1 else 16
  self.write(self.status,1,0)
  for attempt in range(limit):
   target=self.target('force');saved=first&65535
   self.write(self.coeff,2,first);self.write(self.coeff+2,2,second);self.call('force',[2,bank,saved],target)
   target=self.target('force');value=self.read(self.coeff+2,2);self.call('force',[3,bank,value],target)
   if mode==1:
    self.call('delay',[10]);self.call('minimum',[self.samples,1,self.out]);score=s32(self.read(self.out+8,4));amount=max(0,gain-1)
   else:
    for v,p in [(0,self.scratch),(32,self.second)]:
     self.call('force',[1,2,v]);self.call('delay',[10]);self.call('minimum',[self.samples,1,p])
    dx=s32(self.read(self.second,4)-self.read(self.scratch,4));dy=s32(self.read(self.second+4,4)-self.read(self.scratch+4,4))
    if self.s3:self.write(self.out+4,4,dy);self.write(self.out,4,dx)
    else:self.write(self.out,4,dx);self.write(self.out+4,4,dy)
    score=max(s32(self.read(self.scratch+8,4)),s32(self.read(self.second+8,4)))
    amount=3 if policy else int(self.absolute(dx)<5)
   changes=[]
   for i in range(2):
    value=self.read(self.out+4*i,4)
    changes.append(s16(shift(self.read(self.out+4*i,4),amount)) if self.absolute(value)>=threshold else 0)
   for i in range(2):
    if changes[i]==0:
     if self.absolute(self.read(self.scratch+4*i,4))>49:changes[i]=s16(shift(self.read(self.scratch+4*i,4),amount))
     else:
      value=s32(self.read(self.out+4*i,4));changes[i]=(value>0)-(value<0)
   if mode!=1:
    if score>44:changes=[0,0]
    elif not self.s3:
     if self.absolute(self.read(self.out,4))<=9:self.absolute(self.read(self.out+4,4))
    if backup>436:changes=[s16(self.call('limit',[x,5,-5])) for x in changes]
   if self.absolute(self.read(self.out,4))<=threshold and self.absolute(self.read(self.out+4,4))<=threshold and score<=45:
    self.write(self.status,1,1);break
   if self.absolute(self.read(self.out,4))>threshold:first=s16(saved-changes[0])
   if self.absolute(self.read(self.out+4,4))>threshold:second=s16(second-changes[1])
   first=min(511,max(0,first));second=min(511,max(0,second))
  for i in range(2):
   v=s16(self.read(self.coeff+2*i,2))
   if not 0<=v<=511:self.write(self.coeff+2*i,2,max(0,min(511,v)))
  for i in range(2):
   target=self.target('force');value=self.read(self.coeff+2*i,2);self.call('force',[2+i,bank,value],target)

def cases(chip):
 rng=random.Random(0x44435343)
 boundary=[-0x80000000,-65537,-32769,-32768,-513,-50,-16,-6,-5,-2,-1,0,1,2,4,5,6,9,10,15,16,44,45,46,49,50,511,1022,32767,32768,65535,0x7fffffff]
 def base(kind):return dict(kind=kind,coeff=[256,256,256,256],state=[0,0],estimates=[[0,0,35]],samples=0x12348001,delay=0x12340007,logs=[0,0],policy=0,mode=1,table_mutation=True)
 for state in range(64):
  for index in range(6):
   c=base(0);c.update(state=[(index<<6)|state,0],estimates=[[0,0,35],[13,-16,48],[-50,60,56]],logs=[state%2,index%2]);yield c
 for x in boundary:
  for y in boundary[::3]:
   c=base(0);c.update(coeff=[x,y,512,-1],state=[(rng.randrange(6)<<6)|rng.randrange(64),0],estimates=[[x,y,56]],logs=[0x100,0x101]);yield c
 for mode in [0,1,2,257]:
  for policy in [0,1,256]:
   for state in [0,1,3,7,15,31,63,255]:
    for score in [35,44,45,46,56]:
     c=base(1);c.update(mode=mode,policy=policy,state=[state,437 if state%2 else 436],estimates=[[rng.choice(boundary),rng.choice(boundary),score],[rng.choice(boundary),rng.choice(boundary),score]]);yield c
 for kind in [0,1]:
  for i in range(400):
   c=base(kind);c.update(coeff=[rng.choice(boundary) for _ in range(4)],state=[(rng.randrange(6)<<6)|rng.randrange(64),rng.choice([0,436,437,MASK])],estimates=[[rng.choice(boundary),rng.choice(boundary),rng.choice([0,35,44,45,46,56,0x80000000])] for _ in range(32)],mode=rng.choice([0,1,2,MASK]),policy=rng.choice([0,1,256]),logs=[rng.choice([0,1,256]),rng.choice([0,1,256])],alias=i%4 if kind==1 else 0,mutate=i%5==0,table_mutation=i%3!=0)
   if i%7==0:c['abs_values']=[rng.choice(boundary) for _ in range(7)]
   yield c

def main():
 manifest=json.loads((HERE/'manifest.json').read_text())
 for name,digest in manifest['tool_sha256'].items():require(hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest,'Changed pinned tool')
 for chip,row in manifest['chips'].items():
  for suffix,key in [('instructions','instructions_sha256'),('baseline','baseline_sha256')]:require(hashlib.sha256((HERE/(chip+'-'+suffix+'.json')).read_bytes()).hexdigest()==row[key],'Changed pinned extraction')
 results={}
 for chip in ['esp32c3','esp32s3']:
  e=json.loads((HERE/(chip+'-instructions.json')).read_text());a=Search(chip,e);b=Search(chip,e)
  pcs,edges=set(),set();count=0;digest=hashlib.sha256()
  for c in cases(chip):
   try:original=a.run(c);reference=b.run(c,True)
   except Exception:
    (HERE/'failure.json').write_text(json.dumps(dict(chip=chip,case=c,original=a.trace,reference=b.trace),indent=2));raise
   if original!=reference:
    (HERE/'failure.json').write_text(json.dumps(dict(chip=chip,case=c,original=original,reference=reference),indent=2))
    for i,(x,y) in enumerate(zip(original,reference)):
     if x!=y:print(chip,count,i,x,y,flush=True);break
    raise ValueError('Contract mismatch')
   count+=1;pcs|=a.visited;edges|=a.branches;digest.update(json.dumps([c,original],separators=(',',':')).encode())
  all_edges={(pc,take) for pc,(_,op,_) in a.program.items() if op in CONDITIONAL for take in [False,True]}
  results[chip]=dict(cases=count,trace_sha256=digest.hexdigest(),instructions=len(a.program),covered_instructions=len(pcs),edges=len(all_edges),covered_edges=len(edges),uncovered_pcs=[hex(pc) for pc in sorted(set(a.program)-pcs)],uncovered_edges=[[hex(pc),t] for pc,t in sorted(all_edges-edges)])
  require(pcs==set(a.program) and edges==all_edges,'Uncovered original branch or instruction')
  print(chip,results[chip],flush=True)
 require(results==json.loads((HERE/'expected-results.json').read_text()),'Changed reference results')
if __name__=='__main__':main()
