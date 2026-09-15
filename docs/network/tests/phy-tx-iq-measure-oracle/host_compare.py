from pathlib import Path
import hashlib,json,subprocess,tempfile
import verify
TEMP=tempfile.TemporaryDirectory();OUT=Path(TEMP.name)
ROOT=Path(__file__).resolve().parent;cases=list(verify.cases());records=[]
text=''.join(' '.join(map(str,[c['kind'],*c['args'],*c['registers'],*c['samples'],*c['limits'],*sum(c['effects'],[])]))+'\n' for c in cases)
for opt in (0,2):
 binary=OUT/('host-o'+str(opt));subprocess.run(['rustc','--edition=2021','-C','opt-level='+str(opt),'--cfg','test',str(ROOT.parent/'phy_tx_iq_measure.rs'),'-o',str(binary)],check=True)
 for chip in ('esp32c3','esp32s3'):
  e=json.loads((ROOT/(chip+'-instructions.json')).read_text());output=subprocess.check_output([str(binary),chip],input=text,text=True);rows=[json.loads(l) for l in output.splitlines()];verify.machine.require(len(rows)==len(cases), "Wrong row count")
  for i,(case,row) in enumerate(zip(cases,rows)):
   c=dict(case,log_address=0x3c00a3b8 if chip=='esp32c3' else 0x3c004e73);a=verify.Original(chip,e,c);a.run()
   verify.machine.require(row==[a.trace,a.final()],(chip,opt,i))
  records.append(dict(chip=chip,optimization=opt,cases=len(rows),trace_matches=True,stdout_sha256=hashlib.sha256(output.encode()).hexdigest()))
TEMP.cleanup();print(records)
