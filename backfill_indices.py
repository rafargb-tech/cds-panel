#!/usr/bin/env python3
"""Backfill del histórico OBSERVADO de índices de crédito, vía S3 directo (sin API DTCC).
   Itera fechas hacia atrás (~14 meses), descarga de S3 lo que exista (403/404 = no existe),
   calcula la mediana on-the-run 5Y por índice y ensambla indices_history.json. Paralelo + caché."""
import json, io, zipfile, collections, datetime as dt, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import fetch_credit_indices as F     # s3_url, download, rows_from_bytes, level_for, hy_price_to_spread, META

CACHE='cache'; DAYS_BACK=430

def get_day(d):
    fn=f"CFTC_CUMULATIVE_CREDITS_{d.strftime('%Y_%m_%d')}.zip"
    path=os.path.join(CACHE, fn)
    if os.path.exists(path) and os.path.getsize(path)>200:
        raw=open(path,'rb').read()
    else:
        try: raw=F.download(F.s3_url(d))
        except Exception: return (d, None)
        if raw is None: return (d, None)              # 403/404 -> no existe ese día
        open(path,'wb').write(raw)
    try: rows=F.rows_from_bytes(raw)
    except Exception: return (d, None)
    out={}
    for upi,meta in F.META.items():
        lv=F.level_for(rows, upi, d)
        if not lv: continue
        pt={'d':d.isoformat(),'v':lv['value']}
        if meta['kind']=='price': pt['sd']=F.hy_price_to_spread(lv['value'])
        out[meta['key']]=pt
    return (d, out or None)

def main():
    os.makedirs(CACHE, exist_ok=True)
    today=dt.datetime.now(dt.timezone.utc).date()
    cands=[today-dt.timedelta(k) for k in range(1, DAYS_BACK+1)]
    t0=time.time(); series=collections.defaultdict(dict); ok=0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs=[ex.submit(get_day,d) for d in cands]
        for i,fut in enumerate(as_completed(futs),1):
            d,out=fut.result()
            if out:
                ok+=1
                for k,pt in out.items(): series[k][pt['d']]=pt
            if i%80==0: print(f"  {i}/{len(cands)}  días válidos={ok}  ({time.time()-t0:.0f}s)")
    hist={'updated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'series':{}}
    for k,bydate in series.items():
        hist['series'][k]=[bydate[dd] for dd in sorted(bydate)]
    json.dump(hist, open('indices_history.json','w',encoding='utf-8'), ensure_ascii=False)
    print(f"\nHecho en {time.time()-t0:.0f}s · días válidos={ok}")
    for k,v in hist['series'].items():
        print(f"  {k:5} {len(v):4d} días  [{v[0]['d']} -> {v[-1]['d']}]  último={v[-1]['v']}")

if __name__=='__main__':
    main()
