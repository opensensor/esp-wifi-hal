#!/usr/bin/env python3
"""Extract remaining bounded IRAM I2C bodies from the same pinned ELF."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
from elftools.elf.elffile import ELFFile

NAMES={
    'esp32c3':['rom1_get_i2c_hostid','rom1_chip_i2c_readReg','rom1_chip_i2c_writeReg',
                'rom1_phy_i2c_init1','phy_i2c_bbtop_wakeup','bias_dreg_i2c_set',
                'bias_dreg_i2c_set.part.0','phy_i2c_enter_critical','phy_i2c_exit_critical'],
    'esp32s3':['ram_get_i2c_hostid','ram_chip_i2c_readReg','ram_chip_i2c_writeReg',
                'ram_phy_i2c_init1','phy_i2c_bbtop_wakeup','ram_set_txcap_reg',
                'phy_i2c_enter_critical','phy_i2c_exit_critical'],
}
CONDITIONAL=('beq','bne','bnei','beqz','beqz.n','bnez','bnez.n','bltu','bgeu','bltui','bltz','bany')


def require(ok,message):
    if not ok:raise ValueError(message)


def extract(chip,path,objdump,baseline):
    require(chip in NAMES,'Unknown chip');raw=path.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==baseline['elf_sha256'],'ELF hash differs')
    elf=ELFFile(io.BytesIO(raw));symbols={s.name:s for s in elf.get_section_by_name('.symtab').iter_symbols()}
    def read(address,size):
        for section in elf.iter_sections():
            start=section['sh_addr']
            if start<=address and address+size<=start+section['sh_size']:
                return section.data()[address-start:address-start+size]
        raise ValueError('Unmapped ELF read')
    functions,literals=[],{}
    for name in NAMES[chip]:
        symbol=symbols[name];start,size=symbol['st_value'],symbol['st_size'];body=read(start,size)
        require(size>0,'Missing function body');pending,program=[start],{}
        while pending:
            address=pending.pop()
            if address in program:continue
            require(start<=address<start+size,'Branch outside function')
            output=subprocess.check_output([objdump,'-d',f'--start-address={address}',
                                            f'--stop-address={start+size}',str(path)],text=True)
            m=re.search(r'^[ \t]*([0-9a-f]+):[ \t]+([0-9a-f]+)[ \t]+(\S+)(?:[ \t]+([^\n]*))?$',output,re.M)
            require(m is not None and int(m[1],16)==address,'Missing instruction')
            encoded,op=m[2],m[3];args=re.split(r'\s*[<#]',m[4] or '')[0].strip();width=len(encoded)//2
            require(width in (2,3,4),'Unsupported width')
            require(int(encoded,16).to_bytes(width,'little')==read(address,width),'Byte mismatch')
            program[address]=f'{address:x}: {encoded} {op}'+(f' {args}' if args else '')
            if op=='l32r':
                literal=int(args.split(',')[1],16);literals[hex(literal)]=hex(int.from_bytes(read(literal,4),'little'))
            if op in ('ret','retw.n'):continue
            if op=='jr':
                require(chip=='esp32c3','Unknown indirect tail call');continue
            if op=='j':
                target=int(args,16)
                if start<=target<start+size:pending.append(target)
                else:require(name=='bias_dreg_i2c_set' and target==symbols['bias_dreg_i2c_set.part.0']['st_value'],
                             'Unknown selected tail call')
                continue
            if op in CONDITIONAL:pending.append(int(args.split(',')[-1],16))
            pending.append(address+width)
        functions.append({'name':name,'address':hex(start),'size_bytes':size,
                          'body_sha256':hashlib.sha256(body).hexdigest(),'code_hex':body.hex(),
                          'instructions':[program[a] for a in sorted(program)]})
    names=['phy_param','g_phyFuns','phy_i2c_init2']+(['rom_i2c_sar2_init_code'] if chip=='esp32c3' else ['memset'])
    recorded={n:{'address':hex(symbols[n]['st_value']),'size_bytes':symbols[n]['st_size']} for n in names}
    return {'elf_sha256':baseline['elf_sha256'],'map_sha256':baseline['map_sha256'],
            'functions':functions,'symbols':recorded,'literals':literals}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('chip',choices=NAMES)
    p.add_argument('elf',type=Path);p.add_argument('objdump');p.add_argument('output',type=Path);a=p.parse_args()
    baseline=json.loads(Path(__file__).parents[2].joinpath('phy-pbus-validation.json').read_text())
    result=extract(a.chip,a.elf,a.objdump,baseline['allocations'][a.chip+'/source-v2'])
    a.output.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
