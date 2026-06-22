"""
Scraper resultados Registraduría Nacional - Elecciones Presidenciales Colombia 2026.

Descarga datos JSON desde resultados.registraduria.gov.co para 1ra y/o 2da vuelta
en todos los ámbitos (país, departamentos, municipios) y los aplana a CSV.

Uso:
    python scrape_resultados.py --round 2 --out data_v2
    python scrape_resultados.py --round 1 --out data_v1 --level depto
    python scrape_resultados.py --round both --out all_data

Endpoints descubiertos (sin auth, requieren UA + Referer):
    /json/nomenclator.json              -> árbol territorial
    /json/ACT/PR/{scopeCode}.json       -> resultados 1ra vuelta
    /v2/json/ACT/PR/{scopeCode}.json    -> resultados 2da vuelta
    /maps/{scopeCode}.geojson           -> polígonos GeoJSON
"""

import argparse
import csv
import json
import ssl
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()
    try:
        SSL_CTX.load_default_certs()
    except Exception:
        pass

BASE = "https://resultados.registraduria.gov.co"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "es-CO,es;q=0.9",
}

ROUND_PATHS = {
    1: {"prefix": "/json", "referer": f"{BASE}/"},
    2: {"prefix": "/v2/json", "referer": f"{BASE}/v2/resultados/0/00/"},
}


def fetch_json(url, referer, retries=3, backoff=1.5):
    headers = dict(HEADERS, Referer=referer)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as r:
                raw = r.read()
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (403, 404):
                return None
            time.sleep(backoff ** attempt)
        except Exception as e:
            last_err = e
            time.sleep(backoff ** attempt)
    raise RuntimeError(f"Falló {url}: {last_err}")


def fix_latin(s):
    """No-op (respuesta ya decodificada como latin-1 en fetch_json)."""
    return s


def get_nomenclator(rnd):
    p = ROUND_PATHS[rnd]
    url = f"{BASE}{p['prefix']}/nomenclator.json"
    return fetch_json(url, p["referer"])


def list_scopes(nomenclator, levels):
    """Devuelve [(level, code, name)] filtrados por niveles pedidos."""
    out = []
    for elec in nomenclator["amb"]:
        for amb in elec["ambitos"]:
            if amb["l"] in levels:
                out.append((amb["l"], amb["co"], fix_latin(amb["n"])))
    return out


def get_act(rnd, scope_code):
    p = ROUND_PATHS[rnd]
    url = f"{BASE}{p['prefix']}/ACT/PR/{scope_code}.json"
    return fetch_json(url, p["referer"])


def flatten_act(data, level, code, name):
    """Aplana payload ACT a filas: totales + por candidato."""
    if not data:
        return []
    rows = []
    tot = data.get("totales", {}).get("act", {})
    base = {
        "level": level,
        "scope_code": code,
        "scope_name": name,
        "snapshot_mdhm": data.get("mdhm"),
        "numact": data.get("numact"),
        "numdep": data.get("numdep"),
        "mesas_total": tot.get("metota"),
        "mesas_escrutadas": tot.get("mesesc"),
        "pct_mesas_escrut": tot.get("pmesesc"),
        "censo_total": tot.get("centota"),
        "votantes": tot.get("votant"),
        "pct_participacion": tot.get("pvotant"),
        "abstencion": tot.get("absten"),
        "pct_abstencion": tot.get("pabsten"),
        "votos_nulos": tot.get("votnul"),
        "votos_no_marc": tot.get("votnma"),
        "votos_blancos": tot.get("votblan"),
        "votos_validos": tot.get("votval"),
    }
    found_candidate = False
    for cam in data.get("camaras", []):
        for p in cam.get("partotabla", []) or []:
            a = p.get("act", {})
            partido_cod = a.get("codpar")
            partido_votos = a.get("vot")
            partido_pct = a.get("pvot")
            for can in a.get("cantotabla", []) or []:
                found_candidate = True
                row = dict(base)
                row.update({
                    "partido_cod": partido_cod,
                    "partido_votos": partido_votos,
                    "partido_pct": partido_pct,
                    "candidato_cod": can.get("codcan"),
                    "candidato_cedula": can.get("cedula"),
                    "candidato_nombre": fix_latin(
                        f"{can.get('nomcan','')} {can.get('apecan','')}".strip()
                    ),
                    "formula_vp": fix_latin(
                        f"{can.get('nomcan2','')} {can.get('apecan2','')}".strip()
                    ),
                    "candidato_votos": can.get("vot"),
                    "candidato_pct": can.get("pvot"),
                    "candidato_pref": can.get("pref"),
                })
                rows.append(row)
    if not found_candidate:
        rows.append(base)
    return rows


CSV_COLS = [
    "level", "scope_code", "scope_name", "snapshot_mdhm",
    "numact", "numdep",
    "mesas_total", "mesas_escrutadas", "pct_mesas_escrut",
    "censo_total", "votantes", "pct_participacion",
    "abstencion", "pct_abstencion",
    "votos_nulos", "votos_no_marc", "votos_blancos", "votos_validos",
    "partido_cod", "partido_votos", "partido_pct",
    "candidato_cod", "candidato_cedula", "candidato_nombre", "formula_vp",
    "candidato_votos", "candidato_pct", "candidato_pref",
]


def scrape_round(rnd, levels, out_dir, workers, save_raw):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / f"raw_v{rnd}"
    if save_raw:
        raw_dir.mkdir(exist_ok=True)

    print(f"[v{rnd}] Obteniendo nomenclator…")
    nom = get_nomenclator(rnd)
    if not nom:
        print(f"[v{rnd}] No se pudo obtener nomenclator", file=sys.stderr)
        return
    (out_dir / f"nomenclator_v{rnd}.json").write_text(
        json.dumps(nom, ensure_ascii=False), encoding="utf-8"
    )
    scopes = list_scopes(nom, levels)
    print(f"[v{rnd}] {len(scopes)} ámbitos a descargar (niveles={levels})")

    rows = []
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(get_act, rnd, code): (lvl, code, name)
            for lvl, code, name in scopes
        }
        for i, fut in enumerate(as_completed(futs), 1):
            lvl, code, name = futs[fut]
            try:
                data = fut.result()
            except Exception as e:
                fail += 1
                print(f"  ! {code} {name}: {e}", file=sys.stderr)
                continue
            if data is None:
                fail += 1
                continue
            ok += 1
            if save_raw:
                (raw_dir / f"{code}.json").write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )
            rows.extend(flatten_act(data, lvl, code, name))
            if i % 50 == 0 or i == len(scopes):
                print(f"  {i}/{len(scopes)} ok={ok} fail={fail}")

    csv_path = out_dir / f"resultados_v{rnd}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[v{rnd}] CSV -> {csv_path} ({len(rows)} filas)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--round", choices=["1", "2", "both"], default="2",
                    help="1=1ra vuelta, 2=2da vuelta, both=ambas")
    ap.add_argument("--out", default="data", help="Carpeta salida")
    ap.add_argument("--level", choices=["pais", "depto", "muni", "all"],
                    default="all", help="Granularidad geográfica")
    ap.add_argument("--workers", type=int, default=8,
                    help="Descargas concurrentes")
    ap.add_argument("--raw", action="store_true",
                    help="Guardar también JSON crudo por ámbito")
    args = ap.parse_args()

    level_map = {
        "pais": [1],
        "depto": [1, 2],
        "muni": [1, 2, 3],
        "all": [1, 2, 3],
    }
    levels = level_map[args.level]

    rounds = [1, 2] if args.round == "both" else [int(args.round)]
    for r in rounds:
        scrape_round(r, levels, args.out, args.workers, args.raw)


if __name__ == "__main__":
    main()
