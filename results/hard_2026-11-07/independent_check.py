import json,random,subprocess,sys,glob,os,concurrent.futures as cf
from collections import Counter
sp=sys.argv[1]; py=sys.executable
def run(*a): return subprocess.run([py,'-m',*a],capture_output=True,text=True)
jobs=[]
for f in glob.glob('build/llm_hard/reports/siemens_scl+rockwell_st+public_st/candidates/claude-sonnet-5-5/*/llm_repair_r0.fbt'):
    n=f.split('/')[-2]; d=glob.glob(f'corpus_hard/*/{n}')[0]
    ref=d+'/reference.st' if os.path.exists(d+'/reference.st') else d+'/program.st'
    jobs.append((n,f,d,ref))
for f in glob.glob('build/llm_hard/reports/ecc_persistent/candidates/claude-sonnet-5-5/*/llm_repair_r0.fbt'):
    n=f.split('/')[-2]; d='corpus/'+n; jobs.append(('ecc_'+n,f,d,d+'/program.st'))
def check(j):
    name,f,d,ref=j; stims=sorted(x for x in glob.glob(d+'/*stimulus*.json') if 'pairing' not in x)
    tun=json.load(open(d+'/stimulus.json')); rng=random.Random(20261107); pool=tun['scans']; keys=list(pool[0]); cur=dict(pool[0]); rows=[]
    for i in range(1200):
        for k in keys:
            if rng.random()<0.03: cur[k]=pool[rng.randrange(len(pool))][k]
        rows.append(dict(cur))
    rp=f'{sp}/{name}.rand.json'; json.dump({'scan_ms':tun['scan_ms'],'scans':rows},open(rp,'w')); res={}
    for s in stims+[rp]:
        tag=os.path.basename(s).replace('.json','').replace(name+'.','')
        a=run('st2fb.forte_run','--fbt',f,'--stimulus',s,'--out',f'{sp}/{name}.{tag}.f.json')
        b=run('st2fb.reference_run','--st',ref,'--stimulus',s,'--out',f'{sp}/{name}.{tag}.m.json')
        if a.returncode or b.returncode: res[tag]=f'rc {a.returncode}/{b.returncode} {(a.stderr+b.stderr)[-150:]}'; continue
        run('st2fb.compare',f'{sp}/{name}.{tag}.m.json',f'{sp}/{name}.{tag}.f.json','--out',f'{sp}/{name}.{tag}.r.json')
        r=json.load(open(f'{sp}/{name}.{tag}.r.json')); res[tag]=(r['equal'],r['divergences'],r['scans_compared'])
    return name,res
bad=0
with cf.ThreadPoolExecutor(4) as ex:
    for name,res in ex.map(check,sorted(jobs)):
        ok=all(isinstance(v,tuple) and v[0] for v in res.values()); bad+=not ok
        print(name,'ALLEQUAL' if ok else res, {k:v[2] for k,v in res.items() if isinstance(v,tuple)} if ok else '')
print('programs not fully equal:',bad)
def mutate(j):
    name,f,d,ref=j; md=f'{sp}/mut/{name}'; os.makedirs(md,exist_ok=True)
    run('st2fb.mutate','fbt',f,'--count','5','--seed','61499','--out-dir',md)
    stim=d+'/heldout_stimulus.json'; rf=f'{sp}/{name}.heldout_stimulus.m.json'; o=[]
    for m in sorted(glob.glob(md+'/*.fbt')):
        out=m+'.json'; a=run('st2fb.forte_run','--fbt',m,'--stimulus',stim,'--out',out)
        if a.returncode: o.append((os.path.basename(m),'nonzero')); continue
        c=run('st2fb.compare',rf,out,'--out',out+'.r'); o.append((os.path.basename(m),'killed' if c.returncode==1 else 'survived'))
    return name,o
tot=Counter()
with cf.ThreadPoolExecutor(4) as ex:
    for name,o in ex.map(mutate,sorted(jobs)):
        c=Counter(k for _,k in o); tot+=c; print('MUT',name,dict(c),[n for n,k in o if k=='survived'])
print('MUT TOTAL',dict(tot))
