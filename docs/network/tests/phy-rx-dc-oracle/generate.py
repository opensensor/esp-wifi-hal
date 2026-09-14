"""Encode original-instruction traces for the production Rust host harness."""
import hashlib,json,struct,sys
from pathlib import Path
from verify_contract import DC,cases,HERE,require

CASE_WORDS=133
EVENT={'read':1,'write':2,'call':3,'return':4}

def words(c):
    mode=c.get('abs_mode','abs')
    data=[c['kind'],c.get('sample_count',0),c.get('unused',0),int(c['table_mutation']),int(c.get('output_alias',False)),int(c.get('status_alias',False)),int(mode!='abs'),0 if mode=='abs' else mode&0xffffffff,int(c.get('mutate',False))]
    data += [v&0xffffffff for row in c.get('samples',[[0]*3]*8) for v in row]
    data += [v&0xffffffff for row in c.get('gates',[[0]*2]*8) for v in row]
    for name in ['data','status']:
        field=c.get(name,[]);data += field+[0]*(42-len(field))
    require(len(data)==CASE_WORDS,'Case length')
    return data

def trace_words(trace):
    result=[]
    for kind,*args in trace:
        require(len(args)<8,'Event length')
        result += [EVENT[kind],*[v&0xffffffff for v in args],*[0]*(7-len(args))]
    return result

if __name__=='__main__':
    chip,path=sys.argv[1:];e=HERE/(chip+'-instructions.json');manifest=json.loads((HERE/'manifest.json').read_text())
    require(hashlib.sha256(e.read_bytes()).hexdigest()==manifest['chips'][chip]['instructions_sha256'],'Fixture hash')
    require(hashlib.sha256((HERE/'machine.py').read_bytes()).hexdigest()==manifest['tool_sha256']['machine.py'],'Engine hash')
    oracle=DC(chip,json.loads(e.read_text()));digest=hashlib.sha256();count=0
    with Path(path).open('wb') as f:
        for c in cases(chip):
            trace=oracle.run(c);digest.update(json.dumps([c,trace],separators=(',',':')).encode());encoded=trace_words(trace);data=words(c)+[len(encoded)]+encoded;f.write(struct.pack('<'+'I'*len(data),*data));count+=1
    expected=json.loads((HERE/'expected-results.json').read_text())['chips'][chip]
    require(count==expected['cases'] and digest.hexdigest()==expected['ordered_trace_sha256'],'Original trace digest changed')
    print(chip,count,'original-instruction cases encoded')
