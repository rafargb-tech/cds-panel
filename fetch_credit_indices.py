#!/usr/bin/env python3
"""
Fetcher diario de índices de crédito negociables (CDX/iTraxx) desde el tape público del DTCC.
Fuente verificada: DTCC Public Price Dissemination (CFTC / Credits).
- Índice de ficheros: GET pddata.dtcc.com/ppd/api/cumulative/CFTC/CR  (SIN cabecera Origin)
- Fichero EOD: S3 público directo (fullFilePath), ZIP -> 1 CSV (formato CDE, 110 col)
Nivel diario = mediana del spread normalizado de prints on-the-run 5Y (roll por maturity modal).
HY cotiza en PRECIO (puntos): serie primaria = precio observado; spread = derivado (modelo), etiquetado.

Escribe: indices.json (foto del día) + actualiza indices_history.json (observado, se acumula)
"""
import json, csv, io, zipfile, urllib.request, collections, statistics as st, datetime as dt, math, os

API   = 'https://pddata.dtcc.com/ppd/api/cumulative/CFTC/CR'
UA    = {'User-Agent': 'Mozilla/5.0'}          # NUNCA enviar Origin (403 CORS)
MIN_PRINTS = 15
HIST  = 'indices_history.json'

# UPI Underlier Name -> metadatos de presentación
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
    """Flat-hazard ISDA-style. Aproximación de un factor -> ETIQUETAR como derivado."""
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

def get_index():
    req = urllib.request.Request(API, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=60))

def file_date(entry):
    return dt.datetime.strptime(entry['fileName'].split('CREDITS_')[1][:10], '%Y_%m_%d').date()

def fetch_rows(url):
    req = urllib.request.Request(url, headers=UA)
    raw = urllib.request.urlopen(req, timeout=120).read()
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

def build_entry(upi, lv):
    m = META[upi]; e = dict(m); e.update(n=lv['n'], lo=lv['lo'], hi=lv['hi'], maturity=lv['maturity'])
    if m['kind'] == 'price':
        e['value'] = lv['value']                       # precio observado
        e['spread_derived'] = hy_price_to_spread(lv['value'])
    else:
        e['value'] = lv['value']                       # spread nativo bps
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
    idx = get_index()
    latest = max(idx, key=file_date)
    fdate = file_date(latest); dstr = fdate.isoformat()
    rows = fetch_rows(latest['fullFilePath'])
    entries = []
    for upi in META:
        lv = level_for(rows, upi, fdate)
        if lv: entries.append(build_entry(upi, lv))
    doc = {'fetched_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
           'file_date': dstr, 'source': 'DTCC PPD (CFTC/Credits)',
           'lag_note': 'EOD del DTCC, ~1 día hábil', 'data': entries}
    json.dump(doc, open('indices.json', 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    update_history(entries, dstr)
    for e in entries:
        extra = f" -> spread~{e['spread_derived']}" if 'spread_derived' in e else ''
        print(f"  {e['name']:18} {e['value']:>8} ({'precio' if e['kind']=='price' else 'bps'}) n={e['n']}{extra}")
    print("OK", dstr)

if __name__ == '__main__':
    main()
