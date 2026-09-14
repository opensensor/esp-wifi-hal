"""Ordered RX gain-calibration boundary model and original instruction oracle.

Observe MMIO, parameter/caller memory, callback targets, scalars and pointer
contents. Exclude compiler-private stack traffic and fixed readonly memcpy.
Already reconstructed helpers remain separately verified boundaries.
"""
import hashlib,json,random
from pathlib import Path
from machine import Machine,decode,require,signed,MASK,CONDITIONAL
HERE=Path(__file__).resolve().parent
CODES,IQ,DC,CHANNELS=0x300000,0x310000,0x320000,0x330000
COEFF,OUTPUT,STATUS=0x500000,0x500100,0x500200
PARAM=0x230000
s16=lambda v:signed(v,16)
s32=lambda v:signed(v)
class Gain(Machine):
 def __init__(self,chip,e):
  self.chip,self.e,self.s3=chip,e,chip=='esp32s3';self.program,self.entries=decode(e);self.kinds={v:i for i,v in enumerate(self.entries)}
  self.symbols={n:int(s['address'],0) for n,s in e['symbols'].items()};self.param=self.symbols['phy_param'];self.table=self.symbols['g_phyFuns']
  self.slots={'i2c_read':0x194 if self.s3 else 0x1b8,'i2c_write':0x198 if self.s3 else 0x1bc,'power':36,'rx_force':72 if self.s3 else 84,'tx_force':68 if self.s3 else 80,'gain':28,'pbus_force':0x1a8 if self.s3 else 0x1cc,'pbus_read':0x1ac if self.s3 else 0x1d0,'estimate_start':0xf0 if self.s3 else 0x104,'estimate_stop':0xf4 if self.s3 else 0x108,'gain_write':0x1b8 if self.s3 else 0x1dc}
  names={'search':'pbus_rx_dco_cal','one_step':'pbus_rx_dco_cal_1step' if self.s3 else 'pbus_rx_dco_cal_1step_new','tx_iq':'txiq_set_reg','start_tone':'start_tx_tone_step','stop_tone':'stop_tx_tone','collect':'get_rfcal_rxiq_data','channel':'chip_v7_set_chan_ana','sort':'rx_chan_dc_sort','log':'phy_printf'}
  self.direct={k:self.symbols[n] for k,n in names.items()};self.formats={int(v['address'],0):i for i,v in enumerate(e['logs'])}
 def put(self,a,w,v):
  for i in range(w):self.mem[a+i]=(v>>(8*i))&255
 def get(self,a,w):
  require(w in (1,2,4) and a%w==0,f'Unaligned read {a:x}/{w}')
  if 0x70000000<=a<0x71000000:
   require(w==4,'Wrong table width');return a+0x1000000
  require(all(a+i in self.mem for i in range(w)),f'Uninitialized read {a:x}/{w}')
  return sum(self.mem[a+i]<<(i*8) for i in range(w))
 def canonical(self,a):
  for p,n,tag in self.locals:
   if p<=a<p+n:return tag+a-p
  if self.param<=a<self.param+1024:return PARAM+a-self.param
  return a
 def observed(self,a):return self.param<=a<self.param+1024 or CODES<=a<CHANNELS+256 or 0x60000000<=a<0x60020000
 def read(self,a,w):
  v=self.get(a,w)
  if self.observed(a):self.trace.append(['read',self.canonical(a),w,v])
  else:require(0x100000<=a<0x110000 or a==self.table or 0x70000000<=a<0x71000000 or any(int(t['address'],0)<=a<a+w<=int(t['address'],0)+t['size_bytes'] for t in self.e['readonly']),f'Undocumented read {a:x}/{w}')
  return v
 def write(self,a,w,v):
  require(w in (1,2,4) and a%w==0,f'Unaligned write {a:x}/{w}')
  v&=(1<<(w*8))-1
  if self.observed(a):self.trace.append(['write',self.canonical(a),w,v])
  else:require(0x100000<=a<0x110000 or a==self.table,'Undocumented write')
  self.put(a,w,v)
 def enter(self,kind,sp):
  if kind==0:self.coeff=sp+(16 if self.s3 else 56);self.output,self.status=None,None
  else:self.coeff=sp+(38 if self.s3 else 72);self.output=sp+(16 if self.s3 else 88);self.status=sp+(0 if self.s3 else 100)
  self.locals=[(self.coeff,8 if kind==0 else 4,COEFF)]
  if kind==1:self.locals += [(self.output,12,OUTPUT),(self.status,14 if self.s3 else 42,STATUS)]
 def target(self,kind):return self.read(self.read(self.table,4)+self.slots[kind],4)
 def call(self,kind,args,target=None):
  if target is None:target=self.target(kind) if kind in self.slots else self.direct[kind]
  if kind in self.slots:require(target==0x71000000+self.generation*0x1000+self.slots[kind],'Cached callback target')
  pointers={'search':{1},'one_step':{3,4,5},'sort':{0,1}}.get(kind,set())
  norm=[self.canonical(v) if i in pointers else v&MASK for i,v in enumerate(args)]
  self.trace.append(['call',kind,target if kind in self.slots else 0,*norm])
  result=0
  if kind=='i2c_read':result=self.c['saved']
  elif kind=='pbus_read':result=(0x12340000+self.calls*0x171)&MASK
  elif kind=='estimate_start':
   value=self.c['powers'][self.estimates%len(self.c['powers'])];self.estimates+=1
   self.put(0x60006164,4,value)
  elif kind=='collect':result=(self.c['collect']+self.collections*0x12345)&MASK;self.collections+=1
  elif kind=='search':
   require(args[0]==4000 and args[2:]==[10,0,0],'General-search scalar ABI')
   self.trace.append(['buffer',COEFF,*[self.get(args[1]+2*i,2) for i in range(2)]])
   for i in range(4):self.write(args[1]+2*i,2,(self.calls*31+i*53)&65535)
   self.trace.append(['buffer_result',COEFF,*[self.get(args[1]+2*i,2) for i in range(4)]])
  elif kind=='one_step':
   require(args[2]==2048,'One-step sample ABI')
   self.trace.append(['buffer',COEFF,self.get(args[3],2),self.get(args[3]+2,2)])
   x,y=self.c['coefficients'][self.searches%len(self.c['coefficients'])];status=self.c['statuses'][self.searches%len(self.c['statuses'])];self.searches+=1
   self.write(args[3],2,x);self.write(args[3]+2,2,y)
   for i in range(3):self.write(args[4]+4*i,4,0x12340000+self.searches+i)
   self.write(args[5],1,status)
   self.trace.append(['buffer_result',COEFF,x&65535,y&65535,status&255])
  elif kind=='sort':
   require(all(args[1]+i in self.mem for i in range(14 if self.s3 else 42)),'Sort consumed uninitialized channel statuses')
   self.trace.append(['status_input',*[self.get(args[1]+i,1) for i in range(14 if self.s3 else 42)]])
  # Mutate externally visible memory between calls to detect cached input loads,
  # accidental references and reordered volatile reads. Private helper buffers
  # change only through their explicit ABI above.
  if self.c['mutate']:
   a,w=[(self.codes+2,1),(self.iq+44,4),(self.dc+4,2),(self.param+0x14c,2),(0x6000607c,4)][self.calls%5]
   self.write(a,w,self.get(a,w)^(0x1357+self.calls))
  self.calls+=1
  if self.c['table_mutation']:
   self.generation+=1;self.put(self.table,4,0x70000000+self.generation*0x1000)
  self.trace.append(['return',result&MASK]);return result&MASK
 def dispatch(self,target,values,r,depth):
  if self.s3 and target==self.symbols['memcpy']:
   dest,src,n=values(3);require(n in (5,7,10),'Unexpected constant copy')
   for i in range(n):self.put(dest+i,1,self.get(src+i,1))
   return dest
  if 0x71000000<=target<0x72000000:
   slot=(target-0x71000000)%0x1000;kind=next((k for k,v in self.slots.items() if v==slot),None);require(kind is not None,'Unknown callback')
   arity={'i2c_read':5,'i2c_write':6,'power':1,'rx_force':1,'tx_force':1,'gain':3,'pbus_force':3,'pbus_read':2,'estimate_start':2,'estimate_stop':0,'gain_write':1}[kind]
   return self.call(kind,values(arity),target)
  kind=next((k for k,v in self.direct.items() if v==target),None);require(kind is not None,f'Unknown direct helper {target:x}')
  if kind=='log':
   address=values(1)[0];require(address in self.formats,'Unknown format');i=self.formats[address];return self.call('log',[i,*values([9,7][i])[1:]],target)
  return self.call(kind,values({'search':5,'one_step':6,'tx_iq':2,'start_tone':6,'stop_tone':1,'collect':3,'channel':1,'sort':2}[kind]),target)
 def init(self,c):
  self.c=c;self.mem={};self.locals=[];self.trace=[];self.steps=self.calls=self.generation=self.estimates=self.collections=self.searches=0;self.visited,self.branches=set(),set()
  self.codes,self.iq,self.dc,self.channels=CODES,IQ,DC,CHANNELS
  if c['alias']==1:self.codes=IQ+40
  elif c['alias']==2:self.dc=IQ+40
  elif c['alias']==3:self.channels=IQ+32
  for p,n in [(CODES,256),(IQ,256),(DC,256),(CHANNELS,256),(self.param,1024)]:
   for i in range(n):self.put(p+i,1,(i*7+c['seed'])&255)
  self.put(self.param+0x14c,2,c['tx_iq']);self.put(self.table,4,0x70000000)
  for a in [0x6000607c,0x60006164,0x60006160,0x6000615c]:self.put(a,4,c['register']^(a&255))
  for row in self.e['readonly']:
   for i,v in enumerate(bytes.fromhex(row['bytes'])):self.put(int(row['address'],0)+i,1,v)
 def run(self,c,model=False):
  validate_case(self.chip,c)
  self.init(c)
  args=[c['policy'],c['frequency'],self.iq,c['logging']] if c['kind']==0 else [c['policy'],c['start'],c['end'],self.codes,self.iq,self.dc,self.channels,c['count'],c['middle_count'],c['unused']]
  if model:
   self.enter(c['kind'],0x10fe00)
   if c['kind']==0:self.iq_model()
   else:self.dc_model()
  else:
   r=self.registers()
   for i,v in enumerate(args[:(4 if c['kind']==0 else 10 if self.s3 else 8)]):
    if i<(6 if self.s3 else 8):r[f'a{i+(2 if self.s3 else 0)}']=v&MASK
    else:self.put(r['a1' if self.s3 else 'sp']+4*(i-(6 if self.s3 else 8)),4,v)
   self.execute(self.entries[c['kind']],r,c['kind'])
  return self.trace
 def update(self,a,mask,value):self.write(a,4,(self.read(a,4)&mask)|value)
 def i2c(self,value=None):return self.call('i2c_read' if value is None else 'i2c_write',[103,0 if self.s3 else 1,3,2,2]+([] if value is None else [value]))
 def iq_model(self):
  c=self.c;policy=c['policy']&(255 if self.s3 else MASK);logging=c['logging']&(255 if self.s3 else MASK);freq=(s16(c['frequency']) if self.s3 else c['frequency'])&MASK;saved=0
  if policy:saved=self.i2c();self.i2c(0)
  self.call('power',[1]);self.call('rx_force',[1]);self.call('tx_force',[1])
  self.update(0x6000607c,MASK,0x8000000);self.update(0x6000607c,0xefffffff,0);self.update(0x6000607c,0xffffefff,0)
  packed=self.read(self.param+0x14c,2);self.call('tx_iq',[signed(packed>>6,5)&MASK,1]);self.call('tx_iq',[signed(packed,6)&MASK,0])
  self.write(self.coeff,2,256);self.write(self.coeff+2,2,256)
  gains=[63,31,15,7,3,1,0]
  for phase in range(2):
   coarse=phase+2;fine=24;selected=0
   for attempt in range(4):
    selected=gains[coarse];self.call('gain',[selected,260,[128,160][phase]])
    self.call('search',[4000,self.coeff,10,0,0]);self.call('pbus_force',[1,1,497]);self.call('pbus_force',[1,1,505]);self.call('start_tone',[1,freq,fine&255,0,0,0]);self.call('estimate_start',[1,1023])
    power=s32(self.read(0x60006164,4))>>7
    if logging:
     first=self.call('pbus_read',[5,1]);second=self.call('pbus_read',[1,2]);x=s32(self.read(0x6000615c,4))>>16;y=s32(self.read(0x60006160,4))>>16
     self.call('log',[0,power,16384,131072,first,second,fine,x,y])
    self.call('estimate_stop',[]);self.call('stop_tone',[1])
    if power>131072:
     if coarse<6:coarse+=1
     else:fine=s16(fine+20)
    elif power<16384:
     if coarse>0:coarse-=1
     else:fine=s16(fine-20)
    else:break
    fine=max(0,min(120,fine))
   if logging:self.call('log',[1,selected,260,fine,[128,160][phase],phase,2])
   result=self.call('collect',[freq,fine&255,logging]);self.write(self.iq+phase*2,2,result)
  if policy:self.i2c(saved)
  self.call('power',[0]);self.update(0x6000607c,MASK,0x10000000);self.update(0x6000607c,MASK,4096)
 def dc_model(self):
  c=self.c;policy=c['policy']&(255 if self.s3 else MASK);mode=c['start']&(255 if self.s3 else MASK);end=c['end']&(255 if self.s3 else MASK);count=c['count']&(255 if self.s3 else MASK)
  self.call('rx_force',[1]);self.call('tx_force',[1]);self.call('channel',[14])
  if not self.s3:self.write(self.param+0x1f2,1,14)
  saved=0
  if policy:saved=self.i2c();self.i2c(0)
  while mode<end:
   iterations=7 if mode==2 else 1
   columns=count if mode==0 else (c['middle_count']&255 if self.s3 else 4) if mode==1 else 1 if self.s3 else 3
   if mode in (0,1):self.write(self.coeff,2,256);self.write(self.coeff+2,2,256)
   iq_index=0 if policy else 9;dc_index=0;channel_index=0
   for channel in range(iterations):
    if mode==2:
     self.call('channel',[2*(channel+1)])
     if policy:self.i2c(0)
    for col in range(columns):
     if mode==0:gain=self.read(self.codes+col,1)<<8
     elif mode==1:gain=(([0,1,5,13,29][col]<<3)|(self.read(self.codes+2,1)<<8))&65535
     else:gain=self.read(self.codes+count-1 if self.s3 else self.codes+count+col-3,1)<<8
     self.call('gain_write',[gain])
     if mode==1:
      t=self.target('pbus_force');v=self.read(self.iq+46,2);self.call('pbus_force',[2,1,v],t)
      t=self.target('pbus_force');v=self.read(self.iq+44,2);self.call('pbus_force',[3,1,v],t)
     elif mode==2:
      t=self.target('pbus_force');v=self.read(self.dc+6,2);self.call('pbus_force',[2,2,v],t)
      t=self.target('pbus_force');v=self.read(self.dc+4,2);self.call('pbus_force',[3,2,v],t)
      packed=self.read(self.iq+44,4);self.write(self.coeff,2,packed>>16);self.write(self.coeff+2,2,packed)
     else:self.call('pbus_force',[2,2,256]);self.call('pbus_force',[3,2,256])
     status=self.status+(channel_index*2 if self.s3 else channel*columns*2+col)
     self.call('one_step',[policy,mode,2048,self.coeff,self.output,status])
     x=self.read(self.coeff,2);y=self.read(self.coeff+2,2);packed=((x<<16)|s16(y))&MASK
     if mode==1:self.write(self.dc+dc_index*4,4,packed);dc_index=(dc_index+1)&255
     elif mode==0:self.write(self.iq+iq_index*4,4,packed);iq_index=(iq_index+1)&255
     else:
      first=channel_index*2 if self.s3 else channel*columns*2+col;second=first+(1 if self.s3 else columns)
      self.write(self.channels+first*4,4,packed);self.write(self.channels+second*4,4,packed)
      self.write(status+(1 if self.s3 else columns),1,self.read(status,1))
      if self.s3:channel_index=(channel_index+1)&255
   mode=(mode+1)&255
  if policy:self.i2c(saved)
  else:self.call('sort',[self.channels,self.status])
  self.call('rx_force',[0]);self.call('tx_force',[0])

def validate_case(chip,c):
 require(chip in ('esp32c3','esp32s3'),'Unknown chip')
 require(c['kind'] in (0,1),'Unknown operation')
 if c['kind']==0:return
 mask=255 if chip=='esp32s3' else MASK
 start,end,count,policy=[c[k]&mask for k in ['start','end','count','policy']]
 require(start<=2 and end<=4 and count<=9,'Outside bounded stage/count ABI')
 if chip=='esp32s3':require((c['middle_count']&255)<=5,'Middle count exceeds the five-entry coefficient table')
 if start<=2 and end>=3:require(count>=(1 if chip=='esp32s3' else 3),'Gain-code tail precedes caller buffer')
 if not policy:require(start<=2 and end>=3,'Channel sort requires all channel statuses initialized')

def cases(chip):
 s3=chip=='esp32s3';rng=random.Random(0x52474341)
 def base(kind):return dict(kind=kind,policy=1,frequency=0x12348001,logging=1,start=0,end=3,count=9,middle_count=4,unused=0xabcd0123,seed=23,tx_iq=0x7ff,register=0x12345678,saved=0x76543210,collect=0x98765432,powers=[16384<<7],coefficients=[[256,256]],statuses=[1],mutate=False,table_mutation=True,alias=0)
 powers=[-(1<<31),-128,0,(16384<<7)-1,16384<<7,131072<<7,(131072<<7)+128,(1<<31)-1]
 for p in powers:
  for policy in [0,1,256,0xffffffff]:
   for logging in [0,1,256]:
    for iq in [0,31,32,63,15<<6,16<<6,0xffff]:
     c=base(0);c.update(policy=policy,logging=logging,tx_iq=iq,powers=[p]);yield c
 for i in range(256):
  c=base(0);c.update(policy=rng.getrandbits(32),logging=rng.choice([0,1,256]),frequency=rng.getrandbits(32),tx_iq=rng.randrange(65536),powers=[rng.choice(powers) for _ in range(8)],alias=i%4,mutate=i%3==0,table_mutation=i%5!=0,collect=rng.getrandbits(32),register=rng.getrandbits(32));yield c
 for start,end in [(0,0),(1,1),(2,1),(0,1),(1,2),(2,3),(0,3),(0,4)]:
  for policy in [0,1,256]:
   if (policy&(255 if s3 else MASK))==0 and not (start<=2 and end>=3):continue
   for count in [0,3,5,9]:
    if count==0 and start<=2 and end>=3:continue
    for middle in ([0,1,4,5] if s3 else [4]):
     c=base(1);c.update(start=start,end=end,policy=policy,count=count,middle_count=middle,coefficients=[[0x8000,0xffff],[0xffff,0],[511,256]],statuses=[0,1,2]);yield c
 for i in range(400):
  c=base(1);policy=rng.choice([0,1,256]);start,end=rng.choice([(0,3),(2,3),(0,4),(0,1),(1,2)])
  if (policy&(255 if s3 else MASK))==0 and end<3:end=3
  c.update(start=start,end=end,policy=policy,count=rng.choice([3,5,9]),middle_count=rng.randrange(6),alias=i%4,mutate=i%3==0,table_mutation=i%5!=0,coefficients=[[rng.randrange(65536),rng.randrange(65536)] for _ in range(12)],statuses=[rng.randrange(3) for _ in range(7)],seed=rng.randrange(256));yield c

def iq_range_proof():
 # Enumerate every high/low/in-range estimator decision for the complete four
 # attempts, without selecting concrete power values. Fine is register-private;
 # helpers receive values, not its address. No callback can change this state.
 inputs=[];maxima=[]
 for phase in range(2):
  states={(phase+2,24)}
  for attempt in range(4):
   following=set()
   for coarse,fine in states:
    require(0<=coarse<=6 and 0<=fine<=44,'IQ state invariant')
    for high in [False,True]:
     nc,nf=coarse,fine
     if high:
      if coarse<6:nc+=1
      else:nf+=20
     elif coarse>0:nc-=1
     else:nf-=20
     inputs.append(nf);following.add((nc,max(0,min(120,nf))))
   states=following
  maxima.append(max(f for _,f in states))
 require(min(inputs)==-16 and max(inputs)==44 and maxima==[24,44],'Changed exhaustive IQ range proof')
 return dict(unclamped_min=-16,unclamped_max=44,phase_final_max=maxima)

def main():
 manifest=json.loads((HERE/'manifest.json').read_text())
 for name,digest in manifest['tool_sha256'].items():require(hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest,'Changed pinned tool')
 for chip,row in manifest['chips'].items():
  for suffix,key in [('baseline','baseline_sha256'),('instructions','instructions_sha256')]:require(hashlib.sha256((HERE/(chip+'-'+suffix+'.json')).read_bytes()).hexdigest()==row[key],'Changed pinned extraction')
 results={}
 for chip in ['esp32c3','esp32s3']:
  e=json.loads((HERE/(chip+'-instructions.json')).read_text());a,b=Gain(chip,e),Gain(chip,e);pcs=set();edges=set();digest=hashlib.sha256();count=0
  for c in cases(chip):
   try:x=a.run(c);y=b.run(c,True)
   except Exception:
    (HERE/'failure.json').write_text(json.dumps(dict(chip=chip,index=count,case=c,original=a.trace,reference=b.trace),indent=2));raise
   if x!=y:
    (HERE/'failure.json').write_text(json.dumps(dict(chip=chip,index=count,case=c,original=x,reference=y),indent=2))
    for i,(u,v) in enumerate(zip(x,y)):
     if u!=v:print(chip,count,i,u,v,flush=True);break
    raise ValueError('Contract mismatch')
   pcs|=a.visited;edges|=a.branches;digest.update(json.dumps([c,x],separators=(',',':')).encode());count+=1
  all_edges={(pc,t) for pc,(_,op,_) in a.program.items() if op in CONDITIONAL for t in [False,True]}
  results[chip]=dict(cases=count,instructions=len(a.program),covered_instructions=len(pcs),edges=len(all_edges),covered_edges=len(edges),uncovered_pcs=[hex(p) for p in sorted(set(a.program)-pcs)],uncovered_edges=[[hex(p),t] for p,t in sorted(all_edges-edges)],trace_sha256=digest.hexdigest());print(chip,results[chip],flush=True)
  iq_range_proof()
  excluded_pcs={0x42042180} if chip=='esp32c3' else set();excluded_edges={(0x4204217c,False)} if chip=='esp32c3' else set()
  require(pcs==set(a.program)-excluded_pcs and edges==all_edges-excluded_edges,'Uncovered original code beyond the bounded IQ upper-clamp proof')
 require(results==json.loads((HERE/'expected-results.json').read_text()),'Changed reference results')
if __name__=='__main__':main()
