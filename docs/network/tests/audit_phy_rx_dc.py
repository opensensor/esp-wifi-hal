"""Check RX-DC source ownership while retaining calibration search bodies."""
import argparse,json
from pathlib import Path
import audit_phy_rf_iq as previous
import audit_phy_allocations as allocations
import audit_phy_temperature as temperature
SELECTED={chip:{('rxdc_est_min_new' if chip=='esp32c3' else 'rxdc_est_min'):'__opensensor_rx_dc_minimum','rx_chan_dc_sort':'__opensensor_rx_dc_sort'} for chip in ('esp32c3','esp32s3')}
RETAINED={chip:[n for n in names if n not in SELECTED[chip]] for chip,names in previous.RETAINED.items()}

def check_rx_dc(base,symbols,expected,dc_search_source=False,rx_gain_cal_source=False):
 if expected not in ('source','vendor'):raise ValueError('Invalid RX-DC expectation')
 inputs=base['allocations']['libphy.a']['inputs'];member=[r for r in inputs if r['member']=='phy_rx_cal.o']
 if not member and not (rx_gain_cal_source and base['chip']=='esp32c3'):raise ValueError('Calibration search member unexpectedly absent')
 for old,new in SELECTED[base['chip']].items():
  if expected=='source':
   body=temperature.require_body(symbols,new);alias=symbols.get(old)
   if not (alias and alias['address']==body['address'] and (alias.get('absolute') or alias.get('allocated') and alias.get('executable'))):raise ValueError('Wrong RX-DC alias: '+old)
   if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('RX-DC source overlaps vendor allocation')
   if temperature.original_sections(inputs,old):raise ValueError('RX-DC original still allocated: '+old)
  else:
   body=temperature.require_body(symbols,old)
   if not any(temperature.contains(row,body) for row in member):raise ValueError('Wrong retained RX-DC owner')
   if symbols.get(new) is not None:raise ValueError('Source body in vendor control')
 # These complex calibration routines are explicitly outside this milestone.
 for name in RETAINED[base['chip']]:
  if rx_gain_cal_source and name in ('set_rx_gain_cal_iq','set_rx_gain_cal_dc'):continue
  if dc_search_source and name in ('pbus_rx_dco_cal', 'pbus_rx_dco_cal_1step_new' if base['chip']=='esp32c3' else 'pbus_rx_dco_cal_1step'):continue
  body=temperature.require_body(symbols,name)
  if not any(temperature.contains(row,body) for row in member):raise ValueError('Calibration dependency lost: '+name)

def audit(elf_path,map_path,label,expected,dc_search_source=False,rx_gain_cal_source=False):
 from elftools.elf.elffile import ELFFile
 prior=previous.audit(elf_path,map_path,label,'source',rx_dc_source=(expected=='source'),dc_search_source=dc_search_source,rx_gain_cal_source=rx_gain_cal_source);base=allocations.audit(elf_path,map_path,label,exclude_strings=True)
 names=set(SELECTED[base['chip']])|set(SELECTED[base['chip']].values())|set(RETAINED[base['chip']])
 with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(names))
 check_rx_dc(base,symbols,expected,dc_search_source,rx_gain_cal_source=rx_gain_cal_source)
 return {**prior,'schema':'phy-rx-dc-allocation-audit-v1','expect_rx_dc':expected,'checks_passed':True,'previous_source_gates':{**prior['previous_source_gates'],'rf_iq':True},'rx_dc_symbols':{old:{'original_or_alias':symbols[old],'source_body':symbols.get(new),'source_symbol':new} for old,new in SELECTED[base['chip']].items()},'limits':prior['limits']+['DC estimate selection and channel filling replaced; receive DC/gain searches, transmit calibration and analog/ROM dependencies remain.']}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--elf',required=True,type=Path);p.add_argument('--map',required=True,type=Path);p.add_argument('--label',required=True);p.add_argument('--expect-rx-dc',choices=['source','vendor'],required=True);a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_rx_dc),indent=2))
