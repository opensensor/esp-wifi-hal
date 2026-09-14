import hashlib,json,struct,sys
from pathlib import Path
from verify_contract import Gain,cases,HERE,require
KINDS=dict(zip(['i2c_read','i2c_write','power','rx_force','tx_force','gain','pbus_force','pbus_read','estimate_start','estimate_stop','gain_write'],range(11)))
KINDS.update(dict(zip(['search','one_step','tx_iq','start_tone','stop_tone','collect','channel','sort'],range(20,28))));KINDS['log']=29
FIELDS=['kind','policy','frequency','logging','start','end','count','middle_count','unused','seed','tx_iq','register','saved','collect','mutate','table_mutation','alias']
WORDS=59;EVENT=48
def words(c):
 v=[int(c[k]) for k in FIELDS]+[len(c['powers']),len(c['coefficients']),len(c['statuses'])]
 v+=c['powers']+[0]*(8-len(c['powers']))
 v += [x for pair in c['coefficients'] for x in pair]+[0]*(24-2*len(c['coefficients']))
 v+=c['statuses']+[0]*(7-len(c['statuses']));require(len(v)==WORDS,'Case width');return [x&0xffffffff for x in v]
def encode(trace):
 out=[]
 for name,*args in trace:
  if name=='call':args[0]=KINDS[args[0]]
  v=[{'read':1,'write':2,'call':3,'return':4,'buffer':5,'buffer_result':6,'status_input':7}[name],*args]
  require(len(v)<=EVENT,'Event width');out.extend(v+[0]*(EVENT-len(v)))
 return [v&0xffffffff for v in out]
if __name__=='__main__':
 chip,path=sys.argv[1:];a=Gain(chip,json.loads((HERE/(chip+'-instructions.json')).read_text()));digest=hashlib.sha256();count=0
 with Path(path).open('wb') as f:
  for c in cases(chip):
   t=a.run(c);digest.update(json.dumps([c,t],separators=(',',':')).encode());v=encode(t);data=words(c)+[len(v)]+v;f.write(struct.pack('<'+'I'*len(data),*data));count+=1
 expected=json.loads((HERE/'expected-results.json').read_text())[chip];require(count==expected['cases'] and digest.hexdigest()==expected['trace_sha256'],'Changed original traces');print(chip,count,'cases encoded',flush=True)
