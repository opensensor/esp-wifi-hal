"""Check DC-search source ownership while retaining calibration search bodies."""
import argparse,json
from pathlib import Path
import audit_phy_rx_dc as previous
import audit_phy_allocations as allocations
import audit_phy_temperature as temperature
SELECTED={chip:{'pbus_rx_dco_cal':'__opensensor_dc_search_general',('pbus_rx_dco_cal_1step_new' if chip=='esp32c3' else 'pbus_rx_dco_cal_1step'):'__opensensor_dc_search_one_step'} for chip in ('esp32c3','esp32s3')}
RETAINED={chip:[n for n in names if n not in SELECTED[chip]] for chip,names in previous.RETAINED.items()}

def check_dc_search(base,symbols,expected):
 if expected not in ('source','vendor'):raise ValueError('Invalid DC-search expectation')
 inputs=base['allocations']['libphy.a']['inputs'];member=[r for r in inputs if r['member']=='phy_rx_cal.o']
 if not member:raise ValueError('Calibration search member unexpectedly absent')
 for old,new in SELECTED[base['chip']].items():
  if expected=='source':
   body=temperature.require_body(symbols,new);alias=symbols.get(old)
   if not (alias and alias['address']==body['address'] and (alias.get('absolute') or alias.get('allocated') and alias.get('executable'))):raise ValueError('Wrong DC-search alias: '+old)
   if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('DC-search source overlaps vendor allocation')
   if temperature.original_sections(inputs,old):raise ValueError('DC-search original still allocated: '+old)
  else:
   body=temperature.require_body(symbols,old)
   if not any(temperature.contains(row,body) for row in member):raise ValueError('Wrong retained DC-search owner')
   if symbols.get(new) is not None:raise ValueError('Source body in vendor control')
 # These complex calibration routines are explicitly outside this milestone.
 for name in RETAINED[base['chip']]:
  body=temperature.require_body(symbols,name)
  if not any(temperature.contains(row,body) for row in member):raise ValueError('Calibration dependency lost: '+name)

def audit(elf_path,map_path,label,expected):
 from elftools.elf.elffile import ELFFile
 prior=previous.audit(elf_path,map_path,label,'source',dc_search_source=(expected=='source'));base=allocations.audit(elf_path,map_path,label,exclude_strings=True)
 names=set(SELECTED[base['chip']])|set(SELECTED[base['chip']].values())|set(RETAINED[base['chip']])
 with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(names))
 check_dc_search(base,symbols,expected)
 return {**prior,'schema':'phy-dc-search-allocation-audit-v1','expect_dc_search':expected,'checks_passed':True,'previous_source_gates':{**prior['previous_source_gates'],'rx_dc':True},'dc_search_symbols':{old:{'original_or_alias':symbols[old],'source_body':symbols.get(new),'source_symbol':new} for old,new in SELECTED[base['chip']].items()},'limits':prior['limits']+['Receive DC searches replaced; RX gain calibration, S3 spur helpers, transmit calibration and analog/ROM dependencies remain.']}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--elf',required=True,type=Path);p.add_argument('--map',required=True,type=Path);p.add_argument('--label',required=True);p.add_argument('--expect-dc-search',choices=['source','vendor'],required=True);a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_dc_search),indent=2))
