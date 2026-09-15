from pathlib import Path
import hashlib,json,subprocess,tempfile
import verify
ROOT=Path(__file__).resolve().parent;cases=list(verify.cases());records=[]
data=''.join(' '.join(map(str,[c['kind'],*c['args'],c['selector'],c['offset'],c['seed'],*c['registers'],c['policy'],*c['returns'],*sum(c['effects'],[])]))+'\n' for c in cases)
with tempfile.TemporaryDirectory() as temp:
 for opt in (0,2):
  binary=Path(temp)/('host-o'+str(opt));subprocess.run(['rustc','--edition=2021','-C','opt-level='+str(opt),'--cfg','test',str(ROOT.parent/'phy_txiq_search.rs'),'-o',str(binary)],check=True)
  for chip in ('esp32c3','esp32s3'):
   e=json.loads((ROOT/(chip+'-instructions.json')).read_text());output=subprocess.check_output([str(binary),chip],input=data,text=True);rows=[json.loads(l) for l in output.splitlines()];verify.machine.require(len(rows)==len(cases),'Wrong row count')
   for i,(c,row) in enumerate(zip(cases,rows)):
    a=verify.Original(chip,e,c);a.run()
    if row!=[a.trace,a.final()]:
     (ROOT/(chip+'-host-failure.json')).write_text(json.dumps(dict(index=i,case=c,original=a.trace,host=row[0],original_final=a.final(),host_final=row[1]),indent=2)+'\n');raise ValueError(('Rust mismatch',chip,opt,i))
   records.append(dict(chip=chip,optimization=opt,cases=len(rows),trace_matches=True,stdout_sha256=hashlib.sha256(output.encode()).hexdigest()));print(records[-1],flush=True)
