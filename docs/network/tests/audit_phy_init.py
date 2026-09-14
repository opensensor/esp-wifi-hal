#!/usr/bin/env python3
"""Audit complete live PHY initialization code/state replacement on C3 and S3."""
import argparse,json,re
from pathlib import Path
import audit_phy_allocations as allocations
import audit_phy_temperature as temperature
import audit_phy_tx_gain as previous
import phy_init_ownership as ownership

SELECTED=ownership.FUNCTIONS
ALL_SOURCE_NAMES=set().union(*(set(v.values()) for v in SELECTED.values()))|set(ownership.DATA.values())|{'__opensensor_init_rom_version'}

def check_init(base,symbols,expected):
 if expected not in ('source','vendor'):raise ValueError('Expected initialization source or vendor')
 chip=base['chip'];inputs=base['allocations']['libphy.a']['inputs'];member=[r for r in inputs if r['member']=='phy_init.o']
 if expected=='source':
  if member:raise ValueError('Initialization member phy_init.o still allocated')
  if any(r['member']=='phy_init.o' and r['reported_input_bytes'] for r in base.get('excluded_mergeable_string_inputs',[])):raise ValueError('Initialization mergeable string input remains')
  for old in SELECTED[chip]:ownership.function(base,symbols,old)
  for old in ownership.DATA:ownership.state(base,symbols,old)
  if chip=='esp32c3':
   version=symbols.get('__opensensor_init_rom_version')
   if not (version and version['allocated'] and version['body_contained'] and version['type']=='STT_OBJECT' and version['symbol_size_bytes']==1 and not version['executable'] and version['body_sha256'] is None):raise ValueError('Invalid zero-initialized ROM version state')
   if any(temperature.overlaps(r,version) for r in inputs):raise ValueError('ROM version source overlaps vendor input')
  allowed=set(SELECTED[chip].values())|set(ownership.DATA.values())|({'__opensensor_init_rom_version'} if chip=='esp32c3' else set())
 else:
  allowed=set()
  for old in SELECTED[chip]:
   body=temperature.require_body(symbols,old)
   if not any(temperature.contains(r,body) for r in member):raise ValueError('Retained initialization body lacks member ownership: '+old)
  for old,size in [('phy_param',temperature.STATE_SIZES[chip]),('g_phyFuns',4),('chip7_phy_init_ctrl',42)]:
   body=symbols.get(old)
   if not (body and body['allocated'] and body['body_contained'] and body['type']=='STT_OBJECT' and body['symbol_size_bytes']==size):raise ValueError('Invalid retained initialization state: '+old)
   # S3 common control storage is allocated in the member COMMON input.
   if not any(temperature.contains(r,body) for r in member):raise ValueError('Retained initialization state lacks member ownership: '+old)
 for name in ALL_SOURCE_NAMES-allowed:
  if symbols.get(name) is not None:raise ValueError('Unexpected initialization source symbol: '+name)


def audit(elf_path,map_path,label,expected):
 from elftools.elf.elffile import ELFFile
 if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Label must be a simple artifact identifier')
 prior=previous.audit(elf_path,map_path,label,'source',init_source=(expected=='source'))
 base=allocations.audit(elf_path,map_path,label,exclude_strings=True);chip=base['chip']
 with elf_path.open('rb') as stream:symbols=temperature.inspect_symbols(ELFFile(stream),sorted(ownership.names(chip)|ALL_SOURCE_NAMES))
 check_init(base,symbols,expected);phy=base['allocations']['libphy.a']
 return {'schema':'phy-init-allocation-audit-v1','chip':chip,'label':label,'expect_init':expected,'checks_passed':True,'elf_sha256':base['elf_sha256'],'map_sha256':base['map_sha256'],'method':base['method'],
  'previous_source_gates':{**prior['previous_source_gates'],'tx_gain':True},
  'non_string_allocations':{**prior['non_string_allocations'],'phy_init_member_bytes':phy['members'].get('phy_init.o',0)},
  'selected_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new)} for old,new in SELECTED[chip].items()},
  'state_symbols':{old:{'original_or_alias':symbols[old],'source_symbol':new,'source_body':symbols.get(new)} for old,new in ownership.DATA.items()},
  'allocated_phy_members':phy['members'],'allocated_phy_inputs':phy['inputs'],'input_archives_observed':base['input_archives_observed'],'retained_feature_rom_backups':prior['retained_feature_rom_backups'],
  'limits':['Linked-image ownership does not establish ROM or calibration replacement.','Initial state hashes do not validate runtime calibration data.','Entry placement does not prove transitive flash independence.','Instruction and hardware behavior require separate validation.']}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--elf',type=Path,required=True);p.add_argument('--map',type=Path,required=True);p.add_argument('--label',required=True);p.add_argument('--expect-init',choices=['source','vendor'],required=True)
 a=p.parse_args();print(json.dumps(audit(a.elf,a.map,a.label,a.expect_init),indent=2))
