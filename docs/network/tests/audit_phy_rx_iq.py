"""Check RX-IQ source ownership while retaining calibration search bodies."""
import argparse,json
from pathlib import Path
import audit_phy_rx_controls as previous
import audit_phy_allocations as allocations
import audit_phy_temperature as temperature
SELECTED=dict(zip(['rxiq_get_mis','rxiq_cover_mg_mp'],['__opensensor_rx_iq_mismatch','__opensensor_rx_iq_correct']))
RETAINED={chip:[n for n in names if n not in SELECTED] for chip,names in previous.RETAINED.items()}

def check_iq(base,symbols,expected,rf_iq_source=False):
 if expected not in ('source','vendor'):raise ValueError('Invalid RX-IQ expectation')
 inputs=base['allocations']['libphy.a']['inputs'];member=[r for r in inputs if r['member']=='phy_rx_cal.o']
 if not member:raise ValueError('Calibration search member unexpectedly absent')
 for old,new in SELECTED.items():
  if expected=='source':
   body=temperature.require_body(symbols,new);alias=symbols.get(old)
   if not (alias and alias['address']==body['address'] and (alias.get('absolute') or alias.get('allocated') and alias.get('executable'))):raise ValueError('Wrong RX-IQ alias: '+old)
   if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('RX-IQ source overlaps vendor allocation')
   if temperature.original_sections(inputs,old):raise ValueError('RX-IQ original still allocated: '+old)
  else:
   body=temperature.require_body(symbols,old)
   if not any(temperature.contains(row,body) for row in member):raise ValueError('Wrong retained RX-IQ owner')
   if symbols.get(new) is not None:raise ValueError('Source body in vendor control')
 # These complex calibration routines are explicitly outside this milestone.
 for name in RETAINED[base['chip']]:
  if rf_iq_source and name in ('rfcal_rxiq','get_rfcal_rxiq_data'):continue
  body=temperature.require_body(symbols,name)
  if not any(temperature.contains(row,body) for row in member):raise ValueError('Calibration dependency lost: '+name)

def audit(elf_path,map_path,label,expected,rf_iq_source=False):
 from elftools.elf.elffile import ELFFile
 prior=previous.audit(elf_path,map_path,label,'source',iq_source=(expected=='source'),rf_iq_source=rf_iq_source);base=allocations.audit(elf_path,map_path,label,exclude_strings=True)
 names=set(SELECTED)|set(SELECTED.values())|set(RETAINED[base['chip']])
 with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(names))
 check_iq(base,symbols,expected,rf_iq_source)
 return {**prior,'schema':'phy-rx-iq-allocation-audit-v1','expect_rx_iq':expected,'checks_passed':True,'previous_source_gates':{**prior['previous_source_gates'],'rx_controls':True},'rx_iq_symbols':{old:{'original_or_alias':symbols[old],'source_body':symbols.get(new),'source_symbol':new} for old,new in SELECTED.items()},'limits':prior['limits']+['Only IQ conversion and two-round correction replaced; RX/TX calibration searches, analog callbacks and ROM division remain.']}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--elf',required=True,type=Path);p.add_argument('--map',required=True,type=Path);p.add_argument('--label',required=True);p.add_argument('--expect-iq',choices=['source','vendor'],required=True);a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_iq),indent=2))
