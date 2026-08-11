#!/usr/bin/env python3
"""
Fetcher de CDS soberanos — capa 1 del panel SoyRGB.

Fuente: worldgovernmentbonds.com (endpoint interno wp-json).
Verificado 10-Ago-2026: el endpoint exige POST + header Origin del propio sitio.
Devuelve CDS 5Y, rating S&P, variacion 1m/6m y probabilidad de default implicita.

Salida: sovereign_cds.json  (lo lee el panel)  +  sovereign_cds.csv

Uso local:
    pip install requests
    python3 fetch_sovereign_cds.py
"""
import json, re, csv, sys
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
    "Origin": ORIGIN,            # imprescindible; sin esto responde 403
    "Referer": REFERER,
    "Content-Type": "application/json",
}

def fetch():
    r = requests.post(ENDPOINT, headers=HEADERS, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"):
        raise RuntimeError("Respuesta sin success=true")
    return payload

def parse(payload):
    iso = dict(
        (name, code) for code, _v, name in
        re.findall(r'"code":\s*"([A-Z]{2})",\s*"value":\s*([0-9.]+),\s*"name":\s*"([^"]+)"',
                   payload["chart"])
    )
    tbody = payload["table"].split("</thead>")[-1]
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.DOTALL)
    out = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        clean = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in cells]
        if len(clean) < 8:
            continue
        _, country, rating, cds, v1, v6, pd, date = clean[:8]
        out.append({
            "country": country,
            "iso": iso.get(country, ""),
            "rating": rating,
            "cds5y": float(cds),
            "var1m": v1.replace(" ", ""),
            "var6m": v6.replace(" ", ""),
            "pd": pd.replace(" ", ""),
            "date": date,
        })
    out.sort(key=lambda x: x["cds5y"])
    return out

def main():
    data = parse(fetch())
    doc = {
        "fetched_utc": datetime.now(timezone.utc).isoformat(),
        "source": ORIGIN,
        "count": len(data),
        "data": data,
    }
    with open("sovereign_cds.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    with open("sovereign_cds.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader(); w.writerows(data)
    print(f"OK - {len(data)} soberanos - {doc['fetched_utc']}")

if __name__ == "__main__":
    main()
