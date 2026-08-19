#!/usr/bin/env python3
"""Backfill: recorre TODOS los ficheros diarios del DTCC y construye indices_history.json
   con niveles OBSERVADOS reales (sin reconstruir). Descargas en paralelo + caché local."""
import json, csv, io, zipfile, urllib.request, collections, statistics as st, datetime as dt, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import fetch_credit_indices as F   # reutiliza META, level_for, hy_price_to_spread, _num

CACHE='cache'

def dl(entry):
    fn=entry['fileName']; path=os.path.join(CACHE, fn)
    if os.path.exists(path) and os.path.getsize(path)>200:
        raw=open(path,'rb').read()
    else:
        try:
            req=urllib.request.Request(entry['fullFilePath'], headers=F.UA)
            raw=urllib.request.urlopen(req, timeout=90).read()
            open(path,'wb').write(raw)
        except Exception as ex:
            return (entry, None, str(ex))
    return (entry, raw, None)

def process(entry, raw):
    try:
        z=zipfile.ZipFile(io.BytesIO(raw))
        rows=list(csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]),'utf-8')))
    except Exception:
        return None
    fdate=F.file_date(entry); out={}
    for upi,meta in F.META.items():
        lv=F.level_for(rows, upi, fdate)
        if not lv: continue
        pt={'d':fdate.isoformat(),'v':lv['value']}
        if meta['kind']=='price': pt['sd']=F.hy_price_to_spread(lv['value'])
        out.setdefault(meta['key'], pt)
    return (fdate.isoformat(), out)

def main():
    idx=F.get_index()
    print(f"Ficheros a procesar: {len(idx)}")
    t0=time.time(); results=[]; done=0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs=[ex.submit(dl, e) for e in idx]
        for fut in as_completed(futs):
            entry, raw, err = fut.result(); done+=1
            if err or raw is None:
                continue
            pr=process(entry, raw)
            if pr: results.append(pr)
            if done%50==0: print(f"  {done}/{len(idx)}  ({time.time()-t0:.0f}s)")
    # ensamblar series por índice
    series=collections.defaultdict(dict)   # key -> {date: pt}
    for dstr, perday in results:
        for k, pt in perday.items():
            series[k][dstr]=pt
    hist={'updated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'series':{}}
    for k, bydate in series.items():
        hist['series'][k]=[bydate[d] for d in sorted(bydate)]
    json.dump(hist, open('indices_history.json','w',encoding='utf-8'), ensure_ascii=False)
    print(f"\nHecho en {time.time()-t0:.0f}s")
    for k,v in hist['series'].items():
        span=f"{v[0]['d']} -> {v[-1]['d']}" if v else "-"
        print(f"  {k:5} {len(v):4d} días  [{span}]  último={v[-1]['v'] if v else '-'}")

if __name__=='__main__':
    main()
