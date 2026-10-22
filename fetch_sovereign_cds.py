#!/usr/bin/env python3
"""
Fetcher de CDS soberanos — capa 1 del panel SoyRGB.

Fuente: worldgovernmentbonds.com (endpoint interno wp-json).
Verificado 10-Ago-2026: el endpoint exige POST + header Origin del propio sitio.

Escribe:
  sovereign_cds.json  -> foto del dia (lo lee el panel)
  sovereign_cds.csv   -> misma foto en CSV
  history.json        -> serie historica que se acumula dia a dia (por pais)
"""
import json, re, csv, sys, os
from datetime import datetime, timezone, date

try:
    import requests
except ImportError:
    sys.exit("Falta 'requests' -> pip install requests")

ENDPOINT = "https://www.worldgovernmentbonds.com/wp-json/cds/v1/main"
ORIGIN   = "https://www.worldgovernmentbonds.com"
REFERER  = "https://www.worldgovernmentbonds.com/sovereign-cds/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Origin": ORIGIN, "Referer": REFERER, "Content-Type": "application/json",
}
HISTORY_FILE = "history.json"

def fetch():
    r = requests.post(ENDPOINT, headers=HEADERS, timeout=30)
    r.raise_for_status()
    p = r.json()
    if not p.get("success"):
        raise RuntimeError("Respuesta sin success=true")
    return p

def parse(payload):
    iso = dict((name, code) for code, _v, name in re.findall(
        r'"code":\s*"([A-Z]{2})",\s*"value":\s*([0-9.]+),\s*"name":\s*"([^"]+)"', payload["chart"]))
    tbody = payload["table"].split("</thead>")[-1]
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        clean = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in cells]
        if len(clean) < 8:
            continue
        _, country, rating, cds, v1, v6, pd, date = clean[:8]
        out.append({"country": country, "iso": iso.get(country, ""), "rating": rating,
                    "cds5y": float(cds), "var1m": v1.replace(" ", ""),
                    "var6m": v6.replace(" ", ""), "pd": pd.replace(" ", ""), "date": date})
    out.sort(key=lambda x: x["cds5y"])
    return out

import calendar

def _minus_months(d, m):
    y, mo = d.year, d.month - m
    while mo <= 0:
        mo += 12; y -= 1
    day = min(d.day, calendar.monthrange(y, mo)[1])
    return d.replace(year=y, month=mo, day=day)

def _pct(s):
    try:
        return float(str(s).replace("%", "").replace("+", "").strip())
    except ValueError:
        return 0.0

def update_history(data, today):
    """
    Acumula la serie por pais con dos tipos de punto:
      s="obs" -> observado (nivel real del dia)
      s="der" -> reconstruido a partir del cambio 1m/6m reportado por la fuente
    Cada corrida siembra 3 puntos de control: hace 6m, hace 1m y hoy.
    Precedencia: un observado NUNCA es pisado por un reconstruido.
    """
    hist = {"updated_utc": "", "series": {}}
    if os.path.exists(HISTORY_FILE):
        try:
            hist = json.load(open(HISTORY_FILE, encoding="utf-8"))
            hist.setdefault("series", {})
        except Exception:
            pass

    d0 = today
    d1 = _minus_months(d0, 1)
    d6 = _minus_months(d0, 6)

    for d in data:
        key = d["iso"] or d["country"]
        idx = {p["d"]: {**p, "s": p.get("s", "obs")} for p in hist["series"].get(key, [])}

        def put(dt, val, s):
            ds = dt.isoformat()
            cur = idx.get(ds)
            if cur is None or s == "obs" or cur.get("s") == "der":
                idx[ds] = {"d": ds, "v": val, "s": s}

        C = d["cds5y"]
        put(d0, C, "obs")
        v1, v6 = _pct(d["var1m"]), _pct(d["var6m"])
        if 1 + v1 / 100 > 0:
            put(d1, round(C / (1 + v1 / 100), 2), "der")
        if 1 + v6 / 100 > 0:
            put(d6, round(C / (1 + v6 / 100), 2), "der")

        pts = sorted(idx.values(), key=lambda p: p["d"])[-500:]
        hist["series"][key] = pts

    hist["updated_utc"] = datetime.now(timezone.utc).isoformat()
    json.dump(hist, open(HISTORY_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    return sum(len(v) for v in hist["series"].values())


_MONTHS_EN = {m: i for i, m in enumerate(
    ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'], 1)}

def _parse_ddmon(s, ref):
    """'20 Oct' -> date, usando el año de ref (corrige frontera de año)."""
    try:
        day, mon = str(s).strip().split()
        mo = _MONTHS_EN[mon[:3].title()]
        d = date(ref.year, mo, int(day))
        if (d - ref).days > 300:        # cayó en el futuro -> año anterior
            d = date(ref.year - 1, mo, int(day))
        return d
    except Exception:
        return None

ROSTER_FILE = "roster.json"

def merge_roster(fresh, max_age_days=30):
    """Roster PERSISTENTE: roster.json guarda el ULTIMO registro completo de cada país.
    Cada corrida lo actualiza con los frescos de hoy y reconstruye el snapshot = todos los
    del roster con fecha <= max_age_days. Así un país que se cae del feed se sigue mostrando
    con su último dato real (el panel lo marca (o) por fecha < la más reciente); si supera
    30 días, se da de baja. No inventa valores."""
    ref = datetime.now(timezone.utc).date()
    roster = {}
    if os.path.exists(ROSTER_FILE):
        try:
            roster = json.load(open(ROSTER_FILE, encoding="utf-8"))
        except Exception:
            roster = {}
    for r in fresh:                                    # refresca con lo de hoy
        roster[r["country"]] = r
    out, kept = [], {}
    for country, rec in roster.items():
        dte = _parse_ddmon(rec.get("date", ""), ref)
        if dte is None or (ref - dte).days > max_age_days:
            continue                                   # >30 días -> baja del roster
        out.append(rec); kept[country] = rec
    json.dump(kept, open(ROSTER_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    out.sort(key=lambda x: x["cds5y"])
    return out, len(out) - len(fresh)

def main():
    fresh = parse(fetch())
    now = datetime.now(timezone.utc)
    total = update_history(fresh, now.date())          # histórico SOLO con observaciones frescas
    data, carried = merge_roster(list(fresh))          # snapshot = fresco + arrastrados
    doc = {"fetched_utc": now.isoformat(), "source": ORIGIN,
           "count": len(data), "fresh": len(fresh), "carried": carried, "data": data}
    json.dump(doc, open("sovereign_cds.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    with open("sovereign_cds.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader(); w.writerows(data)
    print(f"OK - {len(fresh)} frescos + {carried} arrastrados = {len(data)} - historia: {total} puntos")

if __name__ == "__main__":
    main()
