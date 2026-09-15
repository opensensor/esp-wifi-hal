from pathlib import Path
import hashlib,json,subprocess,tempfile
import verify
ROOT=Path(__file__).resolve().parent
cases=list(verify.cases());records=[]
data=''.join(' '.join(map(str,[c['kind'],c['flags'],c['atten'],c['seed'],*c['returns'],*sum(c['effects'],[])]))+'\n' for c in cases)
with tempfile.TemporaryDirectory() as temp:
 for opt in (0,2):
  binary=Path(temp)/('host-o'+str(opt))
  subprocess.run(['rustc','--edition=2021','-C','opt-level='+str(opt),'--cfg','test',str(ROOT.parent/'phy_txiq_wrappers.rs'),'-o',str(binary)],check=True)
  for chip in ('esp32c3','esp32s3'):
   evidence=json.loads((ROOT/(chip+'-instructions.json')).read_text())
   output=subprocess.check_output([str(binary),chip],input=data,text=True);rows=[json.loads(l) for l in output.splitlines()]
   verify.machine.require(len(rows)==len(cases),'Wrong row count')
   for i,(case,row) in enumerate(zip(cases,rows)):
    a=verify.Original(chip,evidence,case);a.run();verify.machine.require(row==[a.trace,a.final()],('Rust mismatch',chip,opt,i))
   records.append(dict(chip=chip,optimization=opt,cases=len(rows),trace_matches=True,stdout_sha256=hashlib.sha256(output.encode()).hexdigest()))
print(json.dumps(records,indent=2))
