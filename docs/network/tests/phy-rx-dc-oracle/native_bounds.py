"""Sound finite-set propagation for C3's redundant candidate-range edge.

Values outside 0..15 collapse to unknown. Unknown branches take both paths;
unknown writes and ABI caller-clobbers lose information. Consequently the
reachable edge set is an overapproximation, never a coverage-based exclusion.
"""
from collections import deque

def prove(program, start, end):
    tracked=('a0','a1','s9')
    todo=deque([(start,(None,None,None))]);seen=set();edges=set();values={}
    def narrow(v): return v if v is not None and 0<=v<=15 else None
    while todo:
        pc,state=todo.popleft()
        if (pc,state) in seen:continue
        seen.add((pc,state))
        if not start<=pc<end:raise ValueError('Unexpected bound-proof exit')
        nxt,op,args=program[pc]
        # Reject unfamiliar control flow instead of treating it as a write.
        supported={'ret','j','beq','bne','bltu','bgeu','blt','bge','beqz','bnez',
                   'jalr','sw','sh','sb','li','mv','addi','add','lui','lw','lbu',
                   'seqz','zext.b','slli','srai','sub','and'}
        if op not in supported:raise ValueError('Unsupported bound-proof opcode: '+op)
        if op=='jalr' and (len(args)!=1 or not args[0].isidentifier() or args[0]=='zero'):
            raise ValueError('Unsupported bound-proof call convention')
        r=dict(zip(tracked,state));out=r.copy()
        def get(k):return 0 if k=='zero' else r.get(k)
        def add(a,b):return None if a is None or b is None else (a+b)&0xffffffff
        values.setdefault(pc,set()).add(r['s9'])
        if op in ('ret','jr'):continue
        if op=='j':todo.append((int(args[0],16),state));continue
        if op in ('beq','bne','bltu','bgeu','blt','bge','beqz','bnez'):
            a=get(args[0]);b=0 if op in ('beqz','bnez') else get(args[1])
            if a is None or b is None:choices=(False,True)
            else:
                value={'beq':a==b,'bne':a!=b,'beqz':a==b,'bnez':a!=b,'bltu':a<b,'blt':a<b,'bgeu':a>=b,'bge':a>=b}[op]
                choices=(value,)
            for take in choices:
                edges.add((pc,take));todo.append((int(args[-1],16) if take else nxt,state))
            continue
        if op in ('jalr','jal'):
            out['a0']=out['a1']=None # C ABI preserves s9
        elif op in ('sw','sh','sb'):pass
        elif args and args[0] in tracked:
            dest=args[0];value=None
            if op=='li':value=int(args[1],0)&0xffffffff
            elif op=='mv':value=get(args[1])
            elif op=='addi':value=add(get(args[1]),int(args[2],0))
            elif op=='add':value=add(get(args[1]),get(args[2]))
            out[dest]=narrow(value)
        todo.append((nxt,tuple(out[k] for k in tracked)))
        if len(seen)>100000:raise ValueError('Bound proof state limit')
    candidates=[]
    for pc,(_,op,args) in program.items():
        if start<=pc<end and op=='bltu' and args[:2]==['a1','s9']:
            states=[s for p,s in seen if p==pc]
            if states and all(s[1]==14 and s[2] is not None and s[2]<=14 for s in states) and (pc,True) not in edges:
                candidates.append({'address':hex(pc),'taken':True,'reason':'Candidate index starts at zero, advances only below 14, and exits at 14; ABI preserves s9. Finite abstract execution proves 14 < s9 impossible.','candidate_values':sorted(values[pc]),'abstract_states':len(seen)})
    if len(candidates)!=1:raise ValueError('Expected one independently proved redundant range edge')
    return candidates
