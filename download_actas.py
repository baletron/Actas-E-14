"""
Descargador masivo de actas PDF (E-14 / E-24 / E-26) por mesa o puesto.

Requiere conocer el PATRÓN URL del portal de escrutinio. Después de correr
`discover_pdfs.py` para extraer endpoints, edita PDF_URL_TEMPLATE más abajo o
pásalo con --template.

Ejemplos de plantilla (uno de estos es el real — depende del portal):
    https://escrutiniospresidente2026.registraduria.gov.co/api/documento/{depto}/{muni}/{zona}/{puesto}/{mesa}/E14.pdf
    https://escrutiniospresidente2026.registraduria.gov.co/Documentos/{depto}{muni}{zona}{puesto}{mesa}.pdf
    https://escrutiniospresidente2026.registraduria.gov.co/files/{scope_code}/{mesa}/E14_T.pdf

Uso:
    python download_actas.py --template "https://.../api/.../{mesa}.pdf" \
        --out actas/ --max 500 --workers 16
"""

import argparse
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

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def load_nomenclator(path):
    """Lee nomenclator y devuelve lista de munis con código depto + interno."""
    n = json.load(open(path, encoding="utf-8"))
    munis = []
    for elec in n["amb"]:
        for amb in elec["ambitos"]:
            if amb["l"] == 3:
                code = amb["co"]
                munis.append({
                    "name": amb["n"],
                    "code": code,
                    "depto": code[:2],
                    "muni": code[2:],
                })
    return munis


def build_url(template, scope_code, mesa=None, puesto=None):
    return template.format(
        scope_code=scope_code,
        depto=scope_code[:2],
        muni=scope_code[2:],
        mesa=mesa or "",
        puesto=puesto or "",
    )


def download(url, dest, referer):
    headers = {
        "User-Agent": UA,
        "Accept": "application/pdf,*/*",
        "Accept-Language": "es-CO,es;q=0.9",
        "Referer": referer,
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
            data = r.read()
        # Verifica que sea PDF real
        if not data.startswith(b"%PDF"):
            return ("not-pdf", url, len(data))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return ("ok", url, len(data))
    except urllib.error.HTTPError as e:
        return (f"http-{e.code}", url, 0)
    except Exception as e:
        return (f"err-{type(e).__name__}", url, 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template", required=True,
                    help="Plantilla URL. Placeholders: {scope_code} {depto} "
                         "{muni} {mesa} {puesto}")
    ap.add_argument("--nomenclator", default="elecciones_2026/nomenclator_v2.json",
                    help="Path al nomenclator descargado por scrape_resultados.py")
    ap.add_argument("--out", default="actas", help="Carpeta destino PDFs")
    ap.add_argument("--referer", default="https://escrutiniospresidente2026.registraduria.gov.co/publicadas",
                    help="Header Referer obligatorio anti-bot")
    ap.add_argument("--max", type=int, default=0,
                    help="Máximo PDFs a bajar (0=sin límite)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--mesa-range", default="1-30",
                    help="Rango mesas si plantilla usa {mesa} (ej. '1-50')")
    ap.add_argument("--throttle-ms", type=int, default=100,
                    help="Pausa entre lotes para no abusar del servidor")
    args = ap.parse_args()

    munis = load_nomenclator(args.nomenclator)
    print(f"{len(munis)} municipios cargados")

    # Construir tareas
    needs_mesa = "{mesa}" in args.template
    if needs_mesa:
        a, b = args.mesa_range.split("-")
        mesas = range(int(a), int(b) + 1)
    else:
        mesas = [None]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    for m in munis:
        for mesa in mesas:
            url = build_url(args.template, m["code"], mesa=mesa)
            fname = url.rsplit("/", 1)[-1].split("?")[0] or "doc.pdf"
            dest = out_dir / m["depto"] / m["muni"] / (
                f"mesa{mesa}_{fname}" if mesa is not None else fname
            )
            tasks.append((url, dest))
            if args.max and len(tasks) >= args.max:
                break
        if args.max and len(tasks) >= args.max:
            break

    print(f"{len(tasks)} descargas planificadas. Iniciando…")

    stats = {"ok": 0, "skip": 0, "err": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(download, u, d, args.referer): (u, d) for u, d in tasks}
        for i, fut in enumerate(as_completed(futs), 1):
            status, url, sz = fut.result()
            if status == "ok":
                stats["ok"] += 1
            elif status.startswith("http-404") or status == "not-pdf":
                stats["skip"] += 1
            else:
                stats["err"] += 1
            if i % 50 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} ok={stats['ok']} "
                      f"skip={stats['skip']} err={stats['err']}")
            if args.throttle_ms:
                time.sleep(args.throttle_ms / 1000)

    print(f"Done. PDFs guardados en {out_dir}")


if __name__ == "__main__":
    main()
