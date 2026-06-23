"""
Descargador actas E-14 — Elecciones Presidenciales Colombia 2026 (2da vuelta).

Patrón URL descifrado del SPA Angular oficial via ingeniería inversa del bundle
JS (Wayback Machine snapshot 2026-06-22):

    Frontend:    https://e14segundavueltapresidente.registraduria.gov.co/
    PDFs en:     /assets/temis/pdf/{filename}
    Filename:    E14_PRE_X_{dep2}_{mun3}_{zon3}_{stand}_{mesa}_X_XXX.pdf
    Backend GraphQL (opcional): apx2e14awsprodpresidenciav2.prdtpssas.com/graphql
                 (AppSync, Cognito Identity Pool us-east-2:f44a557a-...)

    NO requiere captcha. NO requiere auth. Solo Referer del SPA.

Catálogo de mesas: /assets/temis/divipol_json/allTransmissionCodes.json
  (Wayback no lo archivó por tamaño. Debe obtenerse del sitio en vivo
   o vía consulta GraphQL `TransmissionCodesByStand`.)

Uso:
    # 1. Bajar catálogo (sólo accesible desde IP residencial Colombia):
    python download_actas.py fetch-catalog

    # 2. Bajar PDFs:
    python download_actas.py download --max 100 --workers 8 --depto 01
    python download_actas.py download --all
"""

import argparse
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()

HOST = "https://e14segundavueltapresidente.registraduria.gov.co"
CATALOG_PATH = "/assets/temis/divipol_json/allTransmissionCodes.json"
PDF_PATH_TEMPLATE = "/assets/temis/pdf/{filename}"

# Corporación PRESIDENTE 2da vuelta. Acronym viene de la API (PRE en este caso).
DEFAULT_ACRONYM = "PRE"
DEFAULT_CORP_CODE = "001"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
COMMON_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json,application/pdf,*/*",
    "Accept-Language": "es-CO,es;q=0.9",
    "Referer": HOST + "/",
}


def build_filename(acronym, dep, mun, zon, stand, mesa):
    """E14_PRE_X_{dep2}_{mun3}_{zon3}_{stand2}_{mesa3}_X_XXX.pdf"""
    return (
        f"E14_{acronym}_X_"
        f"{str(dep).zfill(2)}_"
        f"{str(mun).zfill(3)}_"
        f"{str(zon).zfill(3)}_"
        f"{str(stand).zfill(2)}_"
        f"{str(mesa).zfill(3)}_"
        f"X_XXX.pdf"
    )


def build_url(filename, with_uuid=True):
    base = f"{HOST}{PDF_PATH_TEMPLATE.format(filename=filename)}"
    if with_uuid:
        return f"{base}?uuid={uuid.uuid4()}"
    return base


def http_get(url, timeout=30, accept_pdf=False):
    headers = dict(COMMON_HEADERS)
    if accept_pdf:
        headers["Accept"] = "application/pdf,*/*"
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX)


def fetch_catalog(out_path):
    """Descarga allTransmissionCodes.json del sitio en vivo (con fallback GraphQL)."""
    url = HOST + CATALOG_PATH
    print(f"Intento 1: catálogo estático {url}")
    for attempt in range(3):
        try:
            with http_get(url, timeout=120) as r:
                data = r.read()
            if data and data.startswith(b"{"):
                Path(out_path).write_bytes(data)
                print(f"OK: {out_path} ({len(data):,} bytes)")
                return True
            print(f"  intento {attempt+1}: respuesta no JSON ({len(data)} bytes)")
        except urllib.error.HTTPError as e:
            print(f"  intento {attempt+1}: HTTP {e.code}")
            if e.code == 404:
                break
        except Exception as e:
            print(f"  intento {attempt+1}: {type(e).__name__}: {e}")
        time.sleep(3 * (attempt + 1))

    print()
    print("Intento 2: fallback GraphQL (AWS AppSync + Cognito)…")
    try:
        from graphql_client import AppSyncClient, query_transmission_codes
    except ImportError:
        print("ERROR: graphql_client.py no encontrado", file=sys.stderr)
        return False
    try:
        cli = AppSyncClient()
    except Exception as e:
        print(f"ERROR Cognito: {e}", file=sys.stderr)
        return False

    print("Consultando departamentos uno por uno (34 deptos)…")
    all_nodes = {"status11": [], "status3": []}
    deps = [f"{n:02d}" for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
                                  14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
                                  25, 26, 27, 28, 29, 30, 31, 32, 33, 34,
                                  40, 60, 99]]
    for dep in deps:
        try:
            r = query_transmission_codes(cli, dep=dep, first=20000)
        except Exception as e:
            print(f"  dep {dep}: error {e}")
            continue
        n11 = (r.get("data") or {}).get("status11", {}).get("nodes") or []
        n3 = (r.get("data") or {}).get("status3", {}).get("nodes") or []
        all_nodes["status11"].extend(n11)
        all_nodes["status3"].extend(n3)
        print(f"  dep {dep}: +{len(n11)} status11 / +{len(n3)} status3 "
              f"| total {len(all_nodes['status11'])}/{len(all_nodes['status3'])}")
        time.sleep(0.3)

    catalog = {"data": {
        "status11": {"nodes": all_nodes["status11"]},
        "status3": {"nodes": all_nodes["status3"]},
    }}
    Path(out_path).write_text(json.dumps(catalog, ensure_ascii=False),
                              encoding="utf-8")
    total = len(all_nodes["status11"]) + len(all_nodes["status3"])
    print(f"OK: {out_path} ({total:,} nodes total)")
    return total > 0


def load_catalog(path):
    raw = json.load(open(path, encoding="utf-8"))
    if isinstance(raw, dict) and "data" in raw:
        out = []
        for v in raw["data"].values():
            if isinstance(v, dict) and "edges" in v:
                out.extend(e["node"] for e in v["edges"])
            elif isinstance(v, dict) and "nodes" in v:
                out.extend(v["nodes"])
            elif isinstance(v, list):
                out.extend(v)
        # Dedup por idStand+expectedName
        seen = set()
        uniq = []
        for n in out:
            k = (n.get("idStand"), n.get("expectedName"))
            if k not in seen:
                seen.add(k)
                uniq.append(n)
        return uniq
    if isinstance(raw, list):
        return raw
    raise ValueError("Formato catálogo no reconocido")


def download_pdf(url_path, dest_path, with_uuid=True, max_retries=3):
    """url_path puede ser solo el filename o el path completo dep/mun/.../hash.pdf"""
    url = build_url(url_path, with_uuid)
    for attempt in range(max_retries):
        try:
            with http_get(url, timeout=60, accept_pdf=True) as r:
                data = r.read()
            if not data.startswith(b"%PDF"):
                return ("not-pdf", url, len(data))
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(data)
            return ("ok", url, len(data))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ("404", url, 0)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return (f"http-{e.code}", url, 0)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return (f"err-{type(e).__name__}", url, 0)


def cmd_fetch_catalog(args):
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ok = fetch_catalog(out)
    sys.exit(0 if ok else 1)


def cmd_download(args):
    if args.from_catalog:
        cat = load_catalog(args.from_catalog)
        print(f"Catálogo cargado: {len(cat):,} mesas únicas")
        tasks = []
        for node in cat:
            dep = node.get("idDepartmentCode") or node.get("departamento")
            mun = node.get("municipalityCode") or node.get("municipio")
            zon = node.get("idZoneCode") or node.get("zona")
            stand = node.get("standCode") or node.get("stand")
            mesa = node.get("numberStand") or node.get("mesa")
            corp_acronym = node.get("acronym") or args.acronym
            expected = node.get("expectedName") or build_filename(
                corp_acronym, dep, mun, zon, stand, mesa
            )
            if not all([dep, mun, zon, stand, expected]):
                continue
            if args.depto and str(dep).zfill(2) != str(args.depto).zfill(2):
                continue
            tasks.append({
                "filename": expected,
                "dep": str(dep).zfill(2),
                "mun": str(mun).zfill(3),
                "zon": str(zon).zfill(3),
                "stand": str(stand).zfill(2),
                "mesa": str(mesa or "001").zfill(3),
                "corp": corp_acronym,
            })
    else:
        # Modo enumerativo (sin catálogo) — peligroso, miles de 404s
        if not args.dep_range:
            print("Sin catálogo, --dep-range es requerido. Ej: --dep-range 01-99", file=sys.stderr)
            sys.exit(1)
        print("Modo enumerativo activado. Generará muchos 404s.")
        a, b = args.dep_range.split("-")
        tasks = []
        for d in range(int(a), int(b) + 1):
            for m in range(1, args.max_mun + 1):
                for z in range(1, args.max_zon + 1):
                    for s in range(1, args.max_stand + 1):
                        for me in range(1, args.max_mesa + 1):
                            tasks.append({
                                "filename": build_filename(
                                    args.acronym, d, m, z, s, me
                                ),
                                "dep": str(d).zfill(2),
                                "mun": str(m).zfill(3),
                                "zon": str(z).zfill(3),
                                "stand": str(s).zfill(2),
                                "mesa": str(me).zfill(3),
                            })

    if args.max:
        tasks = tasks[: args.max]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Descargas planificadas: {len(tasks):,}")
    print(f"Destino: {out_dir.resolve()}")
    print(f"Workers: {args.workers}, throttle: {args.throttle_ms}ms")
    print()

    stats = {"ok": 0, "404": 0, "not-pdf": 0, "err": 0}
    started = time.time()

    def task_url_path(t):
        return f"{t['dep']}/{t['mun']}/{t['zon']}/{t['stand']}/{t['mesa']}/{t.get('corp', DEFAULT_ACRONYM)}/{t['filename']}"

    def task_path(t):
        return (out_dir / t["dep"] / t["mun"] / t["zon"] / t["stand"]
                / t["mesa"] / t.get("corp", DEFAULT_ACRONYM) / t["filename"])

    # Skip already-downloaded
    tasks = [t for t in tasks if not task_path(t).exists()
             or task_path(t).stat().st_size < 1000]
    print(f"Tras filtro reanudación: {len(tasks):,} pendientes")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(download_pdf, task_url_path(t), task_path(t), True): t
            for t in tasks
        }
        for i, fut in enumerate(as_completed(futs), 1):
            t = futs[fut]
            status, url, sz = fut.result()
            if status == "ok":
                stats["ok"] += 1
            elif status == "404":
                stats["404"] += 1
            elif status == "not-pdf":
                stats["not-pdf"] += 1
            else:
                stats["err"] += 1
            if i % 25 == 0 or i == len(tasks):
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                eta = (len(tasks) - i) / rate if rate else 0
                print(
                    f"  {i}/{len(tasks):,} "
                    f"ok={stats['ok']} 404={stats['404']} "
                    f"err={stats['err']+stats['not-pdf']} "
                    f"| {rate:.1f}/s ETA {eta/60:.1f}m"
                )
            if args.throttle_ms:
                time.sleep(args.throttle_ms / 1000)

    print()
    print(f"Done. PDFs guardados en {out_dir}")
    print(f"Stats: {stats}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch-catalog", help="Descargar allTransmissionCodes.json")
    pf.add_argument("--out", default="catalog.json")
    pf.set_defaults(func=cmd_fetch_catalog)

    pd = sub.add_parser("download", help="Descargar PDFs")
    pd.add_argument("--from-catalog", help="Path a catalog.json (recomendado)")
    pd.add_argument("--out", default="actas/")
    pd.add_argument("--acronym", default=DEFAULT_ACRONYM,
                    help="Acrónimo corporación (default: PRE)")
    pd.add_argument("--depto", help="Sólo este código depto (ej. 01)")
    pd.add_argument("--max", type=int, default=0,
                    help="Máximo PDFs (0=sin límite)")
    pd.add_argument("--workers", type=int, default=8)
    pd.add_argument("--throttle-ms", type=int, default=100,
                    help="Pausa ms entre descargas")
    pd.add_argument("--dep-range", help="(Modo enumerativo) ej '01-99'")
    pd.add_argument("--max-mun", type=int, default=999)
    pd.add_argument("--max-zon", type=int, default=999)
    pd.add_argument("--max-stand", type=int, default=99)
    pd.add_argument("--max-mesa", type=int, default=999)
    pd.set_defaults(func=cmd_download)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
