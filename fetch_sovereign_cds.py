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
from datetime import datetime, timezone

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

def update_history(data, today_iso):
    """Acumula un punto por pais por dia. Reejecutar el mismo dia reemplaza, no duplica."""
    hist = {"updated_utc": "", "series": {}}
    if os.path.exists(HISTORY_FILE):
        try:
            hist = json.load(open(HISTORY_FILE, encoding="utf-8"))
            hist.setdefault("series", {})
        except Exception:
            pass
    for d in data:
        key = d["iso"] or d["country"]
        pts = hist["series"].setdefault(key, [])
        pts = [p for p in pts if p["d"] != today_iso]          # dedupe por fecha
        pts.append({"d": today_iso, "v": d["cds5y"]})
        pts.sort(key=lambda p: p["d"])
        hist["series"][key] = pts[-400:]                       # cap ~18 meses
    hist["updated_utc"] = datetime.now(timezone.utc).isoformat()
    json.dump(hist, open(HISTORY_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    return sum(len(v) for v in hist["series"].values())

def main():
    data = parse(fetch())
    now = datetime.now(timezone.utc)
    doc = {"fetched_utc": now.isoformat(), "source": ORIGIN, "count": len(data), "data": data}
    json.dump(doc, open("sovereign_cds.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    with open("sovereign_cds.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader(); w.writerows(data)
    total = update_history(data, now.strftime("%Y-%m-%d"))
    print(f"OK - {len(data)} soberanos - {now.isoformat()} - historia: {total} puntos")

if __name__ == "__main__":
    main()
