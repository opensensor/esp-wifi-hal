"""Check RX gain-calibration source ownership while retaining the S3 spur bodies."""
import argparse,json
from pathlib import Path
import audit_phy_dc_search as previous
import audit_phy_allocations as allocations
import audit_phy_temperature as temperature
SELECTED={chip:{'set_rx_gain_cal_iq':'__opensensor_rx_gain_cal_iq','set_rx_gain_cal_dc':'__opensensor_rx_gain_cal_dc'} for chip in ('esp32c3','esp32s3')}
RETAINED={chip:[n for n in names if n not in SELECTED[chip]] for chip,names in previous.RETAINED.items()}

def check_rx_gain_cal(base,symbols,expected,spur_source=False):
 if spur_source and base["chip"]!="esp32s3":raise ValueError("Spur transition is S3-only")
 if expected not in ('source','vendor'):raise ValueError('Invalid RX gain-calibration expectation')
 inputs=base['allocations']['libphy.a']['inputs'];member=[r for r in inputs if r['member']=='phy_rx_cal.o']
 if expected=='source' and (base['chip']=='esp32c3' or spur_source):
  if member:raise ValueError('RX calibration member still allocated')
  if any(r['member']=='phy_rx_cal.o' and r['reported_input_bytes'] for r in base.get('excluded_mergeable_string_inputs',[])):raise ValueError('RX calibration strings still allocated')
 elif not member:raise ValueError('Calibration member unexpectedly absent')
 for old,new in SELECTED[base['chip']].items():
  if expected=='source':
   body=temperature.require_body(symbols,new);alias=symbols.get(old)
   if not (alias and alias['address']==body['address'] and (alias.get('absolute') or alias.get('allocated') and alias.get('executable'))):raise ValueError('Wrong RX gain-calibration alias: '+old)
   if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('RX gain-calibration source overlaps vendor allocation')
   if temperature.original_sections(inputs,old):raise ValueError('RX gain-calibration original still allocated: '+old)
  else:
   body=temperature.require_body(symbols,old)
   if not any(temperature.contains(row,body) for row in member):raise ValueError('Wrong retained RX gain-calibration owner')
   if symbols.get(new) is not None:raise ValueError('Source body in vendor control')
 # These complex calibration routines are explicitly outside this milestone.
 for name in RETAINED[base['chip']]:
  if spur_source and name in ('spur_coef_cfg_new','phy_2448m_spur_pwr'):continue
  body=temperature.require_body(symbols,name)
  if not any(temperature.contains(row,body) for row in member):raise ValueError('Calibration dependency lost: '+name)

def audit(elf_path,map_path,label,expected,spur_source=False):
 from elftools.elf.elffile import ELFFile
 prior=previous.audit(elf_path,map_path,label,'source',rx_gain_cal_source=(expected=='source'),spur_source=spur_source);base=allocations.audit(elf_path,map_path,label,exclude_strings=True)
 names=set(SELECTED[base['chip']])|set(SELECTED[base['chip']].values())|set(RETAINED[base['chip']])
 with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(names))
 check_rx_gain_cal(base,symbols,expected,spur_source=spur_source)
 return {**prior,'schema':'phy-rx-gain-cal-allocation-audit-v1','expect_rx_gain_cal':expected,'checks_passed':True,'previous_source_gates':{**prior['previous_source_gates'],'dc_search':True},'rx_gain_cal_symbols':{old:{'original_or_alias':symbols[old],'source_body':symbols.get(new),'source_symbol':new} for old,new in SELECTED[base['chip']].items()},'limits':prior['limits']+['RX gain IQ/DC calibration replaced; S3 spur helpers, transmit calibration and analog/ROM dependencies remain.']}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--elf',required=True,type=Path);p.add_argument('--map',required=True,type=Path);p.add_argument('--label',required=True);p.add_argument('--expect-rx-gain-cal',choices=['source','vendor'],required=True);a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_rx_gain_cal),indent=2))
