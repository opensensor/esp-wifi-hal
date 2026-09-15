#!/usr/bin/env python3
"""Execute pinned receive DC-search instructions with ordered state and callback traces."""
import hashlib,json,re,struct,sys
from pathlib import Path
MASK=0xffffffff
SUPPORTED = {'sub', 'sh', 'bltu', 'l32r', 'addi.n', 'add.n', 'movi.n', 'l8ui', 'j', 'sw', 'bnez.n', 'mov.n', 'l16ui', 's16i', 'l16si', 'slli', 'li', 'srli', 'l32i.n', 'jal', 'call8', 'movi', 'sext', 'and', 'beq', 's32i.n', 'lw', 'blti', 'bge', 's8i', 'lb', 'bnei', 'jr', 'div', 'l32i', 'bne', 'or', 'entry', 'lhu', 'lh', 'auipc', 'mv', 'beqz', 'lui', 'jalr', 'extui', 'mulsh', 'retw.n', 'addmi', 'bgez', 'bltz', 'lbu', 'blt', 'bnez', 'callx8', 'add', 'addi', 'zext.b', 'beqz.n', 'memw', 'ret', 'srai', 'sb', 's32i'}
SUPPORTED.update({'moveqz','nop.n','bany'})
SUPPORTED.update({'movnez', 'mul16u', 'addx8', 'addx4', 'beqi', 'bbsi', 'quos', 'loop', 'snez', 'mul', 'ori', 'andi', 'addx2', 'mull'})
CONDITIONAL = ('beqi','bbsi','beq','bne','beqz','beqz.n','bnez','bnez.n','bltz','bgez','blt','bltu','bge','bnei','blti')

def require(ok, message):
    if not ok:
        raise ValueError(message)

def signed(value, width=32):
    value &= (1 << width)-1
    return value-(1 << width) if value >> (width-1) else value

SUPPORTED |= {'slti','sgtz'}
SUPPORTED |= {'sll','ssl','xor','not','jx','bgeu','movgez'}
CONDITIONAL += ('bgeu', 'bgei', 'bltui', 'bgeui', 'bgtz', 'blez')
SUPPORTED |= {'neg','mulsh','mull','sltiu','seqz','sltu','slt','bgei','bltui','bgeui','bgtz','blez','srl','sra','xori','subx2','subx4','subx8','mulhu','mulh','movsp','max','min','sltz','movltz','ssr'}
SUPPORTED |= {'mul16s', 'mul16u', 'maxu', 'src'}
SUPPORTED |= {'bbci','bnone','rem','remu','divu','muluh','minu'}
CONDITIONAL += ('bbci','bnone','bany')
def decode(evidence):
    program, starts = {}, []
    for function in evidence['functions']:
        start, size = int(function['address'], 0), function['size_bytes']
        body = bytes.fromhex(function['code_hex'])
        require(len(body) == size, 'Code size differs')
        require(hashlib.sha256(body).hexdigest() == function['body_sha256'], 'Code hash differs')
        starts.append(start)
        covered = set()
        for line in function['instructions']:
            match = re.fullmatch(r'([0-9a-f]+): ([0-9a-f]+) (\S+)(?: (.*))?', line)
            require(match is not None, 'Malformed instruction')
            address, raw, op, args = match.groups()
            require(op in SUPPORTED, 'Unsupported instruction '+op)
            address, width = int(address, 16), len(raw)//2
            require(width in (2, 3, 4) and start <= address and address+width <= start+size,
                    'Instruction out of range')
            offsets = set(range(address-start, address-start+width))
            require(not covered.intersection(offsets) and address not in program, 'Overlapping instruction')
            covered.update(offsets)
            require(int(raw, 16).to_bytes(width, 'little') == body[address-start:address-start+width],
                    'Instruction bytes differ')
            program[address] = (address+width, op, [a.strip() for a in (args or '').split(',') if a.strip()])
        # Reachability, not sequential decoding: literals/padding following
        # returns must not be interpreted as instructions.
        require(all(body[i] == 0 for i in set(range(size))-covered), 'Unrecorded nonzero code')
        pending, reached = [start], set()
        while pending:
            address = pending.pop()
            if address in reached:
                continue
            require(address in program, 'Unknown branch target')
            reached.add(address)
            next_pc, op, args = program[address]
            if op in ('ret', 'retw.n', 'jr', 'jx'):
                continue
            if op == 'j':
                target = int(args[0], 16)
                if not start <= target < start+size:
                    require(target in {int(s['address'],0) for s in [*evidence['symbols'].values(),*evidence['functions']]}, 'Unknown tail target')
                    continue
                pending.append(target)
                continue
            if op in CONDITIONAL or op == 'loop':
                pending.append(int(args[-1], 16))
            pending.append(next_pc)
        require(reached == {a for a in program if start <= a < start+size}, 'Unreachable fixture instruction')
    internal = evidence.get('internal_reference_helpers', [])
    require(len(starts) == 2 + len(internal) and len(set(starts)) == len(starts), 'Unexpected function count')
    require(starts[2:] == internal, 'Unexpected internal reference bodies')
    return program, starts


class Machine:
    def registers(self,sp=0x10ff00):
        s3=self.chip=='esp32s3'
        r={f'a{i}':0xabc00000+i*0x1001 for i in range(16)}
        r.update({f's{i}':0xddd00000+i*0x1001 for i in range(12)});r.update({f't{i}':0xeee00000+i*0x1001 for i in range(7)});r.update(sp=sp,ra=0,zero=0)
        if s3:r['a1']=sp
        return r
    def clobber(self,r,value):
        s3=self.chip=='esp32s3'
        for key in ([f'a{i}' for i in range(8,16)] if s3 else [f'a{i}' for i in range(8)]+[f't{i}' for i in range(7)]):r[key]=0xdeadbeef
        r.pop('left_shift',None);r.pop('right_shift',None);r.pop('sar',None)
        if isinstance(value,tuple):
            require(len(value)==2,'Invalid wide return');r['a10' if s3 else 'a0']=value[0]&MASK;r['a11' if s3 else 'a1']=value[1]&MASK
        else:r['a10' if s3 else 'a0']=value&MASK
    def execute(self,pc,r,kind,depth=0):
        s3=self.chip=='esp32s3'
        read,write,get=self.read,self.write,self.get
        require(depth<12,'Call depth exhausted');loop=None
        try:
            while True:
                self.steps+=1;require(self.steps<=500000,'Instruction budget exhausted');require(pc in self.program,f'Unknown PC {pc:x}')
                self.visited.add(pc);next_pc,op,args=self.program[pc]
                if op=='entry':
                    require(s3 and args[0]=='a1' and int(args[1],0)%16==0,'Unexpected entry');r['a1']-=int(args[1],0);self.enter(kind,r['a1'])
                elif op in ('li','movi','movi.n'):r[args[0]]=int(args[1],0)&MASK
                elif op in ('mv','mov.n','movsp'):r[args[0]]=r[args[1]]
                elif op in ('seqz','snez','sltz','neg'):r[args[0]]=(int(r[args[1]]==0) if op=='seqz' else int(r[args[1]]!=0) if op=='snez' else int(signed(r[args[1]])<0) if op=='sltz' else -r[args[1]])&MASK
                elif op=='sgtz':
                    require(not s3,'Wrong signed-greater-than-zero ABI');r[args[0]]=int(signed(r[args[1]])>0)
                elif op=='slti':
                    immediate=int(args[2],0);require(not s3 and -2048<=immediate<=2047,'Invalid signed immediate comparison')
                    r[args[0]]=int(signed(r[args[1]])<immediate)
                elif op=='sltiu':r[args[0]]=int(r[args[1]]<(int(args[2],0)&MASK))
                elif op=='lui':r[args[0]]=(int(args[1],0)<<12)&MASK
                elif op=='auipc':r[args[0]]=(pc+(int(args[1],0)<<12))&MASK
                elif op in ('addi','addi.n','addmi'):
                    r[args[0]]=(r[args[1]]+int(args[2],0))&MASK
                    if not s3 and args[0]=='sp' and int(args[2],0)<0:self.enter(kind,r['sp'])
                elif op in ('add','add.n','addx2','addx4','addx8','mul','sub','and','or','xor','div','mull','mulsh','sltu','slt','subx2','subx4','subx8','mulhu','mulh','max','min','rem','remu','divu','muluh','minu','maxu'):
                    left,right=r[args[1]],r[args[2]]
                    if op in ('add','add.n'):value=left+right
                    elif op.startswith('addx'):value=int(op[-1])*left+right
                    elif op in ('mul','mull'):value=left*right
                    elif op in ('mulsh','mulh'):value=(signed(left)*signed(right))>>32
                    elif op=='sub':value=left-right
                    elif op=='and':value=left&right
                    elif op=='or':value=left|right
                    elif op=='xor':value=left^right
                    elif op=='sltu':value=int(left<right)
                    elif op=='slt':value=int(signed(left)<signed(right))
                    elif op.startswith('subx'):value=int(op[-1])*left-right
                    elif op in ('mulhu','muluh'):value=(left*right)>>32
                    elif op=='minu':value=min(left,right)
                    elif op=='maxu':value=max(left,right)
                    elif op=='divu':value=MASK if right==0 else left//right
                    elif op=='remu':value=left if right==0 else left%right
                    elif op=='rem':
                        left,right=signed(left),signed(right);q=0 if right==0 else (abs(left)//abs(right))*(-1 if (left<0)!=(right<0) else 1);value=left-q*right
                    elif op=='max':value=max(signed(left),signed(right))
                    elif op=='min':value=min(signed(left),signed(right))
                    else:
                        left,right=signed(left),signed(right);value=MASK if right==0 else (abs(left)//abs(right))*(-1 if (left<0)!=(right<0) else 1)
                    r[args[0]]=value&MASK
                elif op in ('mul16s','mul16u'):
                    left,right=r[args[1]]&65535,r[args[2]]&65535
                    if op=='mul16s':left,right=signed(left,16),signed(right,16)
                    r[args[0]]=(left*right)&MASK
                elif op in ('andi','ori'):
                    value=int(args[2],0)&MASK;r[args[0]]=r[args[1]]&value if op=='andi' else r[args[1]]|value
                elif op in ('moveqz','movnez'):
                    if (r[args[2]]==0)==(op=='moveqz'):r[args[0]]=r[args[1]]
                elif op=='not':r[args[0]]=(~r[args[1]])&MASK
                elif op in ('slli','srli','srai'):
                    value=r[args[1]];amount=int(args[2],0);r[args[0]]=((value<<amount) if op=='slli' else (signed(value)>>amount) if op=='srai' else value>>amount)&MASK
                elif op=='xori':r[args[0]]=(r[args[1]]^int(args[2],0))&MASK
                elif op=='ssr':require(s3,'Wrong shift ABI');r['right_shift']=r[args[0]]&31;r['sar']=r[args[0]]&31
                elif op in ('srl','sra'):
                    amount=r['right_shift'] if s3 else r[args[2]]&31;r[args[0]]=((signed(r[args[1]]) if op=='sra' else r[args[1]])>>amount)&MASK
                elif op=='ssl':require(s3,'Wrong shift ABI');r['left_shift']=r[args[0]]&31;r['sar']=32-(r[args[0]]&31)
                elif op=='src':
                    require(s3 and 'sar' in r,'Missing SAR');r[args[0]]=(((r[args[1]]<<32)|r[args[2]])>>r['sar'])&MASK
                elif op=='sll':
                    require(not s3 or 'left_shift' in r,'Missing shift state');amount=r['left_shift'] if s3 else r[args[2]]&31;r[args[0]]=(r[args[1]]<<amount)&MASK
                elif op=='zext.b':r[args[0]]=r[args[1]]&255
                elif op=='extui':r[args[0]]=(r[args[1]]>>int(args[2],0))&((1<<int(args[3],0))-1)
                elif op=='sext':r[args[0]]=signed(r[args[1]],int(args[2],0)+1)&MASK
                elif op in ('movgez','movltz'):
                    if (signed(r[args[2]])>=0)==(op=='movgez'):r[args[0]]=r[args[1]]
                elif op=='l32r':
                    literal=hex(int(args[1],16));require(literal in self.e['literals'],'Unknown literal');r[args[0]]=int(self.e['literals'][literal],0)
                elif op in ('lw','lh','lhu','lbu','lb','sw','sh','sb'):
                    m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[1]);require(m is not None,'Bad memory operand');a=(r[m[2]]+int(m[1]))&MASK;w=4 if op in ('lw','sw') else 1 if op in ('lbu','lb','sb') else 2
                    if op in ('sw','sh','sb'):write(a,w,r[args[0]])
                    else:
                        value=read(a,w);r[args[0]]=(signed(value,w*8) if op in ('lb','lh') else value)&MASK
                elif op in ('l32i','l32i.n','s32i','s32i.n','l8ui','s8i','l16si','l16ui','s16i'):
                    a=(r[args[1]]+int(args[2],0))&MASK;w=2 if '16' in op else 1 if op in ('l8ui','s8i') else 4
                    if op.startswith('s'):write(a,w,r[args[0]])
                    else:
                        value=read(a,w);r[args[0]]=(signed(value,16) if op=='l16si' else value)&MASK
                elif op in CONDITIONAL:
                    left=r[args[0]]
                    if op in ('beqz','beqz.n'):take=left==0
                    elif op in ('bnez','bnez.n'):take=left!=0
                    elif op=='bltz':take=signed(left)<0
                    elif op=='bgez':take=signed(left)>=0
                    elif op=='bgtz':take=signed(left)>0
                    elif op=='blez':take=signed(left)<=0
                    elif op in ('bbsi','bbci'):take=bool(left&(1<<int(args[1],0)))==(op=='bbsi')
                    elif op in ('bnone','bany'):take=((left&r[args[1]])==0)==(op=='bnone')
                    else:
                        right=int(args[1],0)&MASK if op in ('beqi','bnei','blti','bgei','bltui','bgeui') else r[args[1]]
                        if op in ('beq','beqi'):take=left==right
                        elif op in ('bne','bnei'):take=left!=right
                        elif op in ('bltu','bltui'):take=left<right
                        elif op in ('blt','blti'):take=signed(left)<signed(right)
                        elif op in ('bge','bgei'):take=signed(left)>=signed(right)
                        elif op in ('bgeu','bgeui'):take=left>=right
                        else:raise ValueError('Unsupported conditional '+op)
                    self.branches.add((pc,take))
                    if take:next_pc=int(args[-1],16)
                elif op=='loop':
                    require(s3 and 0<r[args[0]]<=255,'Unexpected loop count');loop=[next_pc,int(args[1],16),r[args[0]]]
                elif op=='j' and int(args[0],16) in self.program and int(args[0],16) not in self.kinds:next_pc=int(args[0],16)
                elif op in ('j','jr','jal','jalr','call8','callx8'):
                    tail=op in ('j','jr')
                    if op in ('j','jal','call8'):target=int(args[0],16)
                    elif '(' in args[0]:
                        m=re.fullmatch(r'(-?\d+)\((\w+)\)',args[0]);require(m is not None,'Bad call operand');target=(r[m[2]]+int(m[1]))&MASK
                    else:target=r[args[0]]
                    if not s3:
                        target&=~1
                        if not tail:r['ra']=next_pc
                    def values(n):
                        return [r[f'a{i+10}'] if i<6 else get(r['a1']+(i-6)*4,4) for i in range(n)] if s3 else [r[f'a{i}'] if i<8 else get(r['sp']+(i-8)*4,4) for i in range(n)]
                    value=self.dispatch(target,values,r,depth)
                    self.clobber(r,value)
                    if tail:return value
                elif op=='nop.n':pass
                elif op=='memw':require(s3 and not args,'Unexpected memory barrier')
                elif op in ('ret','retw.n'):require((op=='retw.n')==s3,'Wrong return ABI');return r['a2' if s3 else 'a0']
                else:raise ValueError('Unknown instruction '+op)
                if loop and next_pc==loop[1]:
                    loop[2]-=1
                    if loop[2]:next_pc=loop[0]
                    else:loop=None
                r['zero']=0;pc=next_pc
        finally:pass
