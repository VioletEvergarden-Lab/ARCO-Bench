"""Independent event replay of all stored references and deterministic plans."""
from collections import Counter
from study_common import HERE,read
from continuous_engine import Engine,quality

if __name__=='__main__':
    counts=Counter()
    for p in sorted((HERE/'networks/tasks').glob('NET_*.json')):
        eng=Engine(read(p));ref=read(HERE/'networks/references'/p.name)
        rs=eng.verify(ref['decisions']);assert rs['admissible'],(p.stem,rs['errors']);assert quality(rs['objective'],ref['objective']);counts['reference']+=1
        c=read(HERE/'networks/candidates'/p.name)
        for src in ('G','R4'):
            ds=c[src]['decisions'] if src=='G' else c[src]['result']['decisions'];score=eng.verify(ds)
            assert score['admissible'],(p.stem,src,score['errors'])
            assert quality(score['objective'],c[src]['score']['objective'])
            assert quality(score['objective'],ref['objective'])==c[src]['quality']
            counts[src]+=1;counts[src+'_quality']+=c[src]['quality']
    print(dict(counts))
