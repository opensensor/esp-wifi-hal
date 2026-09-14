"""Check RX-control source ownership while retaining calibration search bodies."""
import argparse,json
from pathlib import Path
import audit_phy_init as previous
import audit_phy_allocations as allocations
import audit_phy_temperature as temperature
SELECTED=dict(zip(['rfrx_sat_rst','phy_force_rx_gain_trig','ram_iq_est_enable','phy_check_rx_sat'],['__opensensor_rx_controls_'+s for s in ['reset','trigger','estimate','check']]))

def check_controls(base,symbols,expected):
 if expected not in ('source','vendor'):raise ValueError('Invalid RX-control expectation')
 inputs=base['allocations']['libphy.a']['inputs'];member=[r for r in inputs if r['member']=='phy_rx_cal.o']
 if not member:raise ValueError('Calibration search member unexpectedly absent')
 for old,new in SELECTED.items():
  if expected=='source':
   body=temperature.require_body(symbols,new);alias=symbols.get(old)
   if not (alias and alias['address']==body['address'] and (alias.get('absolute') or alias.get('allocated') and alias.get('executable'))):raise ValueError('Wrong RX-control alias: '+old)
   if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('RX-control source overlaps vendor allocation')
   if temperature.original_sections(inputs,old):raise ValueError('RX-control original still allocated: '+old)
  else:
   body=temperature.require_body(symbols,old)
   if not any(temperature.contains(row,body) for row in member):raise ValueError('Wrong retained RX-control owner')
   if symbols.get(new) is not None:raise ValueError('Source body in vendor control')
 if expected=='source' and temperature.original_sections(inputs,'rfrx_sat_rst.part.0'):raise ValueError('Split saturation original still allocated')
 # These complex calibration routines are explicitly outside this milestone.
 for name in ['rxiq_get_mis','rxiq_cover_mg_mp','rfcal_rxiq','get_rfcal_rxiq_data','pbus_rx_dco_cal','set_rx_gain_cal_iq','rx_chan_dc_sort','set_rx_gain_cal_dc']:
  body=temperature.require_body(symbols,name)
  if not any(temperature.contains(row,body) for row in member):raise ValueError('Calibration dependency lost: '+name)

def audit(elf_path,map_path,label,expected):
 from elftools.elf.elffile import ELFFile
 prior=previous.audit(elf_path,map_path,label,'source');base=allocations.audit(elf_path,map_path,label,exclude_strings=True)
 names=set(SELECTED)|set(SELECTED.values())|{'rxiq_get_mis','rxiq_cover_mg_mp','rfcal_rxiq','get_rfcal_rxiq_data','pbus_rx_dco_cal','set_rx_gain_cal_iq','rx_chan_dc_sort','set_rx_gain_cal_dc'}
 with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(names))
 check_controls(base,symbols,expected)
 return {**prior,'schema':'phy-rx-controls-allocation-audit-v1','expect_rx_controls':expected,'checks_passed':True,'previous_source_gates':{**prior['previous_source_gates'],'initialization':True},'rx_controls_symbols':{old:{'original_or_alias':symbols[old],'source_body':symbols.get(new),'source_symbol':new} for old,new in SELECTED.items()},'limits':prior['limits']+['Only receive saturation and IQ-estimator controls replaced; RX/TX calibration searches and ROM remain.']}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--elf',required=True,type=Path);p.add_argument('--map',required=True,type=Path);p.add_argument('--label',required=True);p.add_argument('--expect-controls',choices=['source','vendor'],required=True);a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_controls),indent=2))
