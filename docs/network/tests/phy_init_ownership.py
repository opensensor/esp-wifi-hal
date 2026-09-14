"""Explicit initialization ownership transitions for the earlier strict gates."""
import hashlib,json
from pathlib import Path
import audit_phy_temperature as temperature

COMMON={'phy_get_romfunc_addr':'callbacks','rf_init':'rf','register_chipv7_phy_init_param':'init_param','phy_set_mac_data':'mac_data','phy_rfcal_data_sub':'transfer','rf_cal_data_recovery':'recovery','phy_rfcal_data_check_value':'check_value','rf_cal_data_backup':'backup','phy_rfcal_data_check':'check','bb_init':'bb','register_chipv7_phy':'register'}
FUNCTIONS={
 'esp32c3':{**COMMON,'rf_cal_level_check':'level','get_txcap_data':'txcap','ram1_phy_wakeup_init':'wakeup','ram1_phy_close_rf':'close'},
 'esp32s3':{**COMMON,'pwr_limit_force':'power_limits','esp_phy_efuse_get_chip_ver_pkg':'package','get_chip_version':'chip_version','ram_phy_wakeup_init':'wakeup','ram_phy_close_rf':'close'},
}
FUNCTIONS={chip:{old:'__opensensor_init_'+suffix for old,suffix in names.items()} for chip,names in FUNCTIONS.items()}
DATA={'phy_param':'__opensensor_init_parameters','chip7_phy_init_ctrl':'__opensensor_init_control','g_phyFuns':'__opensensor_init_table'}
INITIAL=Path(__file__).resolve().parent/'phy-init-oracle/initial-state.json'
def names(chip):return set(FUNCTIONS[chip])|set(FUNCTIONS[chip].values())|set(DATA)|set(DATA.values())|({'__opensensor_init_rom_version'} if chip=='esp32c3' else set())
def alias(old,new):return bool(old and new and old['address']==new['address'] and (old.get('absolute') or old.get('allocated')))
def function(base,symbols,old):
 new=FUNCTIONS[base['chip']][old];body=temperature.require_body(symbols,new);inputs=base['allocations']['libphy.a']['inputs']
 if not (alias(symbols.get(old),body) and (symbols[old].get('absolute') or symbols[old].get('executable'))):raise ValueError('Incorrect initialization alias: '+old)
 if any(temperature.overlaps(row,body) for row in inputs):raise ValueError('Initialization source overlaps vendor input: '+new)
 if temperature.original_sections(inputs,old):raise ValueError('Original initialization function still allocated: '+old)
 if old.endswith(('phy_wakeup_init','phy_close_rf')):
  a=int(body['address'],0)
  if not 0x40370000<=a<a+body['symbol_size_bytes']<=0x403e0000:raise ValueError('Initialization entry is outside IRAM: '+old)
 return body

def state(base,symbols,old):
 chip=base['chip'];new=DATA[old];body=symbols.get(new);size={'phy_param':temperature.STATE_SIZES[chip],'g_phyFuns':4,'chip7_phy_init_ctrl':42}[old];alignment=1 if old=='chip7_phy_init_ctrl' else 4
 if not (body and body['allocated'] and body['body_contained'] and body['type']=='STT_OBJECT' and not body['executable'] and body['symbol_size_bytes']==size and int(body['address'],0)%alignment==0):raise ValueError('Invalid initialization state: '+old)
 if not alias(symbols.get(old),body):raise ValueError('Incorrect initialization state alias: '+old)
 if any(temperature.overlaps(row,body) for row in base['allocations']['libphy.a']['inputs']):raise ValueError('Initialization state overlaps vendor input: '+old)
 expected=json.loads(INITIAL.read_text())[chip]['sha256'] if old=='phy_param' else hashlib.sha256(bytes(size)).hexdigest()
 if not (body['body_sha256']==expected or old!='phy_param' and body['body_sha256'] is None):raise ValueError('Initialization data defaults differ: '+old)
 return body
