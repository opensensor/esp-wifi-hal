"""Private preparation: ordered TX IQ helper boundaries, not analog behavior."""
from pathlib import Path
import hashlib,json,random
import machine
M=0xffffffff
signed=machine.signed
ROOT=Path(__file__).resolve().parent
REGS=(0x60006040,0x60006050)
OUT=0x200000
TABLES=(0x210000,0x210100)
CALLS=(0x220000,0x220100)

class Boundary:
 def __init__(self,chip,e,c):
  self.chip,self.e,self.case=chip,e,c
  self.memory={};self.trace=[];self.calls=0;self.sample=0;self.limit=0
  self.table=int(e['symbols']['g_phyFuns']['address'],0)
  for a,v in zip(REGS,c['registers']):self.put(a,4,v)
  for a in range(OUT,OUT+8):self.put(a,1,0xa5)
  self.put(self.table,4,TABLES[0])
  for a,v in zip(TABLES,CALLS):self.put(a+40,4,v)
 def put(self,a,w,v):
  for i in range(w):self.memory[a+i]=(v>>(8*i))&255
 def get(self,a,w):return sum(self.memory.get(a+i,0)<<(8*i) for i in range(w))
 def where(self,a,w):
  if 0x100000<=a and a+w<=0x110000:return None
  if a in REGS and w==4:return ['reg',a]
  if OUT<=a and a+w<=OUT+8:return ['out',a-OUT]
  if a==self.table and w==4:return ['table']
  if a in [v+40 for v in TABLES] and w==4:return ['slot',TABLES.index(a-40)]
  raise ValueError(('unknown location',hex(a),w))
 def read(self,a,w):
  v=self.get(a,w);where=self.where(a,w)
  if where is not None:self.trace.append(['read',w,where,v])
  return v
 def write(self,a,w,v):
  v&=(1<<(8*w))-1;where=self.where(a,w)
  if where is not None:self.trace.append(['write',w,where,v])
  self.put(a,w,v)
 def helper(self,name,args):
  args=[v&M for v in args]
  if name=='phy_printf':
   machine.require(args[0]==int(self.e['logs'][0]['address'],0),'wrong format pointer');args=args[1:]
  self.trace.append(['call',name,args])
  if name in ('txtone_linear_pwr','get_power_db'):
   result=self.case['samples'][self.sample];self.sample+=1
  elif name.startswith('limit'):
   result=self.case['limits'][self.limit];self.limit+=1
  else:result=0xabcdef00
  effect=self.case['effects'][self.calls];self.calls+=1
  for a,v in zip(REGS,effect[:2]):self.put(a,4,v)
  for i,v in enumerate(effect[2:4]):self.put(OUT+2*i,2,v)
  self.put(self.table,4,TABLES[effect[4]&1])
  self.trace.append(['effect',effect]);return result&M
 def final(self):return [*[self.get(a,4) for a in REGS],self.get(OUT,4),self.get(OUT+4,4),self.get(self.table,4)]

class Original(Boundary,machine.Machine):
 def __init__(self,chip,e,c):
  Boundary.__init__(self,chip,e,c);self.program,self.starts=machine.decode(e);self.kinds=dict(zip(self.starts,(0,1)))
  self.steps=0;self.visited=set();self.branches=set()
  self.helpers={int(e['symbols'][n]['address'],0):n for n in ['ets_delay_us','txtone_linear_pwr','start_tx_tone_step','get_power_db','phy_printf']}
  self.helpers.update({a:'limit'+str(i) for i,a in enumerate(CALLS)})
 def enter(self,kind,stack):machine.require(0x100000<=stack<0x110000,'bad stack')
 def dispatch(self,target,values,r,depth):
  name=self.helpers[target];arity={'ets_delay_us':1,'txtone_linear_pwr':0,'start_tx_tone_step':6,'get_power_db':1,'phy_printf':6,'limit0':3,'limit1':3}[name]
  return self.helper(name,values(arity))
 def run(self):
  r=self.registers();base=2 if self.chip=='esp32s3' else 0
  for i,v in enumerate(self.case['args']):r['a'+str(base+i)]=v&M
  result=self.execute(self.starts[self.case['kind']],r,self.case['kind'])
  if self.case['kind']==1:self.trace.append(['return',result&M])

class Model(Boundary):
 def run(self):
  args=self.case['args'];s3=self.chip=='esp32s3'
  if self.case['kind']==0:
   select,neg,offset,out1,out2=args
   if s3:select&=255;offset=signed(offset,16)
   fields=(((select<<26)|((((-neg)&M)<<10)&0x3fc00)|(signed(offset)>>2)|0x2c0000)&0xfffffff)
   old=self.read(REGS[0],4);self.write(REGS[0],4,(old&0xf0000000)|fields)
   old=self.read(REGS[1],4);self.write(REGS[1],4,(old&~3)|(offset&3))
   self.helper('ets_delay_us',[2]);sample=self.helper('txtone_linear_pwr',[]);self.write(out1,2,sample)
   old=self.read(REGS[0],4);self.write(REGS[0],4,(old&0xf0ffffff)|((((~select&1)|(select<<3))<<24)&0xf000000))
   self.helper('ets_delay_us',[2]);sample=self.helper('txtone_linear_pwr',[]);self.write(out2,2,sample)
   return
  tone,atten,target,offset,debug=args
  if s3:tone=signed(tone,16);atten=signed(atten,8);target&=255;offset&=65535;debug&=255
  else:tone=signed(tone);atten=signed(atten);target=signed(target)
  prev_atten=prev_sample=0
  for iteration in range(6):
   self.helper('start_tx_tone_step',[1,tone,atten&255,0,0,0])
   if s3:self.helper('ets_delay_us',[2])
   p=signed(signed(self.helper('get_power_db',[offset]))>>2,16)
   delta=signed(p-target,16)
   if iteration and prev_atten<atten and prev_sample<p:atten=signed(prev_atten-20,16)
   if debug:self.helper('phy_printf',[self.case['log_address'],iteration,atten,p,target,delta])
   if ((delta+3)&65535)<=6:result=atten;break
   if s3:
    adjustment=delta if delta>0 else -(abs(delta*3)//4)
   else:
    table=self.read(self.table,4);address=self.read(table+40,4)
    raw=self.helper('limit'+str(CALLS.index(address)),[delta,20,-20]);short=signed(raw,16)
    adjustment=raw if short>0 else -(abs(short*3)//4)
   result=signed(atten+adjustment,16)
   if result<0:result=0;break
   if result>120:result=120;break
   prev_atten,prev_sample=atten,p;atten=result
  self.trace.append(['return',result&M])

def cases():
 rng=random.Random(8193)
 def case(kind,args,samples=None,limits=None):
  return dict(kind=kind,args=[a&M for a in args],registers=[rng.getrandbits(32) for _ in range(2)],samples=[v&M for v in (samples or [rng.getrandbits(32) for _ in range(6)])],limits=[v&M for v in (limits or [rng.randint(-20,20) for _ in range(6)])],effects=[[rng.getrandbits(32),rng.getrandbits(32),rng.getrandbits(16),rng.getrandbits(16),rng.randrange(2)] for _ in range(32)])
 for i in range(512):
  vals=[0,1,2,3,127,128,255,256,32767,32768,65535,0x7fffffff,0x80000000,M]
  yield case(0,[rng.choice(vals),rng.choice(vals),rng.choice(vals),OUT,OUT if i%3==0 else OUT+2])
 for debug in (0,1,256):
  for target in (0,50,255,-3,32767):
   for atten in (0,40,120,-128,127):
    for seq in ([0]*6,[1]*6,[-1]*6,[4]*6,[-4]*6,[8,12,16,20,24,28],[-8,-12,-16,-20,-24,-28],[8,-10,15,-20,25,-30]):
     yield case(1,[128,atten,target,4,debug],[(target+d)*4 for d in seq],[d if abs(d)<=20 else 20 for d in seq])
 for _ in range(512):yield case(1,[rng.getrandbits(32),rng.randrange(121),rng.randrange(256),rng.getrandbits(32),rng.randrange(2)])

 for debug in (0,1):
  for atten in (20,40,110):
   for seq in ([10,2,0,0,0,0],[4,200,0,0,0,0],[-4,-1000,0,0,0,0],[10,0,0,0,0,0],[4,5,6,7,8,9]):
    yield case(1,[128,atten,50,4,debug],[(50+d)*4 for d in seq],[max(-20,min(20,d)) for d in seq])

if __name__=='__main__':
 records={}
 for chip in ('esp32c3','esp32s3'):
  e=json.loads((ROOT/(chip+'-instructions.json')).read_text());program,_=machine.decode(e);visited=set();branches=set();digest=hashlib.sha256()
  log={'esp32c3':0x3c00a3b8,'esp32s3':0x3c004e73}[chip]
  for n,c in enumerate(cases(),1):
   c['log_address']=log;a,b=Original(chip,e,c),Model(chip,e,c)
   a.run();b.run()
   if [a.trace,a.final()]!=[b.trace,b.final()]:
    (ROOT/(chip+'-model-failure.json')).write_text(json.dumps(dict(index=n,case=c,original=a.trace,model=b.trace,original_final=a.final(),model_final=b.final()),indent=2)+'\n')
    raise ValueError((chip,n,'model mismatch'))
   visited|=a.visited;branches|=a.branches;digest.update(json.dumps([c,a.trace,a.final()],separators=(',',':')).encode()+b'\n')
  edges={(pc,t) for pc,(_,op,_) in program.items() if op in machine.CONDITIONAL for t in (False,True)}
  row=dict(cases=n,instructions=len(program),covered=len(visited),edges=len(edges),covered_edges=len(branches),uncovered_pcs=[hex(v) for v in sorted(set(program)-visited)],uncovered_edges=[[hex(pc),t] for pc,t in sorted(edges-branches)],trace_sha256=digest.hexdigest());records[chip]=row;print(chip,row,flush=True)
 expected=json.loads((ROOT/'expected-results.json').read_text())
 machine.require(records==expected,'Original coverage or corpus digest differs')
 machine.require(all(r['instructions']==r['covered'] and r['edges']==r['covered_edges'] for r in records.values()),'Original coverage incomplete')
