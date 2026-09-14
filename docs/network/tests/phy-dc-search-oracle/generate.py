import json,struct,sys,hashlib
from pathlib import Path
from verify_contract import Search,cases,HERE,require
KINDS={'read':0,'force':1,'estimate':2,'abs':3,'limit':4,'delay':5,'minimum':6,'log':7}
WORDS=121

def words(c):
 values=[c['kind'],c['samples'],c['delay'],*c['logs'],c['policy'],c['mode'],int(c['table_mutation']),c.get('alias',0),int(c.get('mutate',False)),*c['state'],len(c['estimates']),len(c.get('abs_values',[])),*c['coeff']]
 values += [v for row in c['estimates'] for v in row]+[0]*(96-3*len(c['estimates']))
 values += c.get('abs_values',[])+[0]*(7-len(c.get('abs_values',[])))
 require(len(values)==WORDS,'Case encoding');return [v&0xffffffff for v in values]
def encode(trace):
 values=[]
 for kind,*args in trace:
  if kind=='call':args[0]=KINDS[args[0]]
  row=[{'read':1,'write':2,'call':3,'return':4}[kind],*args];require(len(row)<=12,'Event encoding');values+=row+[0]*(12-len(row))
 return [v&0xffffffff for v in values]
if __name__=='__main__':
 chip,path=sys.argv[1:];a=Search(chip,json.loads((HERE/(chip+'-instructions.json')).read_text()));count=0;digest=hashlib.sha256()
 with Path(path).open('wb') as f:
  for c in cases(chip):
   trace=a.run(c);digest.update(json.dumps([c,trace],separators=(',',':')).encode());events=encode(trace);data=words(c)+[len(events)]+events
   f.write(struct.pack('<'+'I'*len(data),*data));count+=1
 expected=json.loads((HERE/'expected-results.json').read_text())[chip]
 require(count==expected['cases'] and digest.hexdigest()==expected['trace_sha256'],'Changed original traces')
 print(chip,count,'cases encoded',flush=True)
