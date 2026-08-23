#!/usr/bin/env python3
"""
Fetcher diario de índices de crédito negociables (CDX/iTraxx) desde el DTCC.

RESILIENTE: ataca el S3 público directo (construye la URL por fecha), SIN pasar por la
API de pddata.dtcc.com — que bloquea/limita IPs de datacenter (503 en GitHub Actions).
S3 es otro host (AWS) y no bloquea. Con reintentos para 503/timeout transitorios.

Nivel diario = mediana del spread normalizado de prints on-the-run 5Y (roll por maturity modal).
HY cotiza en PRECIO: serie primaria = precio observado; spread = derivado (modelo), etiquetado.
Escribe indices.json + actualiza indices_history.json (observado, se acumula).
"""
import json, csv, io, zipfile, urllib.request, urllib.error, collections, statistics as st, datetime as dt, math, os, time

S3 = 'https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/eod/CFTC_CUMULATIVE_CREDITS_{}.zip'
UA = {'User-Agent': 'Mozilla/5.0'}
MIN_PRINTS = 15
MAX_BACK = 8            # días hacia atrás para encontrar el último fichero bueno
HIST = 'indices_history.json'

META = {
    'CDX.NA.IG':               dict(key='IG',   name='CDX.NA.IG',        region='Norteamérica', grade='Investment Grade', kind='spread'),
    'ITRAXX EUROPE':           dict(key='MAIN', name='iTraxx Europe',    region='Europa',       grade='Investment Grade', kind='spread'),
    'ITRAXX EUROPE CROSSOVER': dict(key='XO',   name='iTraxx Crossover', region='Europa',       grade='Sub-IG (Crossover)', kind='spread'),
    'CDX.NA.HY':               dict(key='HY',   name='CDX.NA.HY',        region='Norteamérica', grade='High Yield',       kind='price'),
}

def _num(x):
    x = x.replace(',', '').strip()
    try: return float(x)
    except: return None

def hy_price_to_spread(price, coupon_bps=500, R=0.30, T=5.0, r=0.04, freq=4):
    c = coupon_bps/1e4; upfront = (100.0-price)/100.0; n = int(T*freq); dt_ = 1/freq
    def legs(h):
        RA = prot = 0.0
        for i in range(1, n+1):
            t = i*dt_; disc = math.exp(-r*t); surv = math.exp(-h*t)
            RA += disc*surv*dt_; prot += disc*(math.exp(-h*(t-dt_))-surv)
        return RA, prot*(1-R)
    lo, hi = 1e-6, 3.0
    for _ in range(200):
        mid = (lo+hi)/2; RA, prot = legs(mid)
        if prot-(c*RA+upfront) > 0: hi = mid
        else: lo = mid
    RA, prot = legs((lo+hi)/2)
    return round(prot/RA*1e4, 1)

def s3_url(d):  return S3.format(d.strftime('%Y_%m_%d'))

def download(url, tries=4):
    """GET con reintentos. Devuelve bytes, o None si 404 (no existe ese día)."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=90).read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404): return None       # S3 devuelve 403 si el objeto no existe
            last = e                                   # 503/5xx -> reintenta
        except Exception as e:
            last = e
        time.sleep(2*(i+1))
    raise last

def rows_from_bytes(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    return list(csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), 'utf-8')))

def level_for(rows, upi, fdate):
    hdr = rows[0]; I = {h: i for i, h in enumerate(hdr)}
    g = lambda r, h: r[I[h]]
    win = []
    for r in rows[1:]:
        if g(r, 'UPI Underlier Name') != upi: continue
        try: m = dt.datetime.strptime(g(r, 'Expiration Date')[:10], '%Y-%m-%d').date()
        except: continue
        if 4.5*365 <= (m-fdate).days <= 5.6*365: win.append((r, m))
    if not win: return None
    modal = collections.Counter(m for _, m in win).most_common(1)[0][0]
    vals = []
    for r, m in win:
        if m != modal: continue
        v = _num(g(r, 'Spread-Leg 1'))
        if v is None: continue
        if v < 1: v *= 10000
        vals.append(v)
    if len(vals) < MIN_PRINTS: return None
    return dict(n=len(vals), value=round(st.median(vals), 2),
                lo=round(min(vals), 2), hi=round(max(vals), 2), maturity=str(modal))

def latest_good():
    """Camina hacia atrás desde ayer hasta el fichero que dé niveles válidos."""
    today = dt.datetime.now(dt.timezone.utc).date()
    for back in range(1, MAX_BACK+1):
        d = today - dt.timedelta(back)
        raw = download(s3_url(d))
        if raw is None: continue                       # no existe (futuro/roto)
        try: rows = rows_from_bytes(raw)
        except: continue
        levels = {upi: level_for(rows, upi, d) for upi in META}
        if levels.get('CDX.NA.IG') and sum(v is not None for v in levels.values()) >= 2:
            return d, levels
    raise RuntimeError('No se encontró fichero EOD válido en los últimos %d días' % MAX_BACK)

def build_entry(upi, lv):
    m = META[upi]; e = dict(m); e.update(n=lv['n'], lo=lv['lo'], hi=lv['hi'], maturity=lv['maturity'])
    e['value'] = lv['value']
    if m['kind'] == 'price': e['spread_derived'] = hy_price_to_spread(lv['value'])
    return e

def update_history(entries, dstr):
    hist = {'updated_utc': '', 'series': {}}
    if os.path.exists(HIST):
        try: hist = json.load(open(HIST, encoding='utf-8')); hist.setdefault('series', {})
        except: pass
    for e in entries:
        s = hist['series'].setdefault(e['key'], [])
        s = [p for p in s if p['d'] != dstr]
        pt = {'d': dstr, 'v': e['value']}
        if 'spread_derived' in e: pt['sd'] = e['spread_derived']
        s.append(pt); s.sort(key=lambda p: p['d']); hist['series'][e['key']] = s[-500:]
    hist['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    json.dump(hist, open(HIST, 'w', encoding='utf-8'), ensure_ascii=False)

def main():
    fdate, levels = latest_good(); dstr = fdate.isoformat()
    entries = [build_entry(upi, lv) for upi, lv in levels.items() if lv]
    doc = {'fetched_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
           'file_date': dstr, 'source': 'DTCC PPD (CFTC/Credits) vía S3',
           'lag_note': 'EOD del DTCC, ~1 día hábil', 'data': entries}
    json.dump(doc, open('indices.json', 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    update_history(entries, dstr)
    for e in entries:
        extra = f" -> spread~{e['spread_derived']}" if 'spread_derived' in e else ''
        print(f"  {e['name']:18} {e['value']:>8} ({'precio' if e['kind']=='price' else 'bps'}) n={e['n']}{extra}")
    print("OK", dstr)

if __name__ == '__main__':
    main()
