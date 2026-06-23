"""
Fallback: descarga PDFs vía Wayback Machine cuando el host original no es
alcanzable (firewall, CDN block, geo-restriction).

Wayback Machine sí puede acceder los assets de Akamai-fronted hosts y guarda
copia. Si el PDF está archivado, Wayback lo sirve sin restricciones.

CAVEAT: Wayback solo tiene snapshots PARCIALES (al 2026-06-23 solo 1 PDF
archivado de 122k mesas). Sirve como respaldo, no como fuente primaria.

Uso:
    # Listar todos PDFs archivados de actas E-14 presidencia
    python fetch_via_wayback.py list

    # Descargar todos los archivados
    python fetch_via_wayback.py download --out actas/

    # Forzar archivado de un PDF en Wayback (Save Page Now)
    python fetch_via_wayback.py save --url "https://e14segundavueltapresidente..."
"""

import argparse
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

WB_CDX = "https://web.archive.org/cdx/search/cdx"
WB_PLAY = "https://web.archive.org/web/{ts}if_/{url}"
WB_SAVE = "https://web.archive.org/save/{url}"

TARGET_BASE = "e14segundavueltapresidente.registraduria.gov.co/assets/temis/pdf/*"


def http_get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX)


def list_archived(target_pattern=TARGET_BASE, limit=10000):
    params = {
        "url": target_pattern,
        "output": "json",
        "limit": str(limit),
        "filter": "mimetype:application/pdf",
    }
    url = WB_CDX + "?" + urllib.parse.urlencode(params)
    with http_get(url, timeout=60) as r:
        rows = json.loads(r.read())
    if not rows:
        return []
    header = rows[0]
    out = []
    for r in rows[1:]:
        rec = dict(zip(header, r))
        if rec.get("statuscode") == "200":
            out.append({"ts": rec["timestamp"], "url": rec["original"]})
    return out


def parse_pdf_path_parts(original_url):
    """Extrae {dep}/{mun}/{zon}/{stand}/{mesa}/{CORP}/{hash}.pdf"""
    path = urllib.parse.urlparse(original_url).path
    parts = path.rsplit("/", 7)[-7:]
    if len(parts) == 7:
        return {
            "dep": parts[0],
            "mun": parts[1],
            "zon": parts[2],
            "stand": parts[3],
            "mesa": parts[4],
            "corp": parts[5],
            "filename": parts[6],
        }
    return None


def download_one(entry, out_dir):
    play_url = WB_PLAY.format(ts=entry["ts"], url=entry["url"])
    parts = parse_pdf_path_parts(entry["url"])
    if not parts:
        return ("bad-path", entry["url"], 0)
    dest = (out_dir / parts["dep"] / parts["mun"] / parts["zon"]
            / parts["stand"] / parts["mesa"] / parts["corp"] / parts["filename"])
    if dest.exists() and dest.stat().st_size > 1000:
        return ("skip-exists", entry["url"], dest.stat().st_size)
    try:
        with http_get(play_url, timeout=120) as r:
            data = r.read()
    except Exception as e:
        return (f"err-{type(e).__name__}", entry["url"], 0)
    if not data.startswith(b"%PDF"):
        return ("not-pdf", entry["url"], len(data))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return ("ok", entry["url"], len(data))


def cmd_list(args):
    items = list_archived(args.pattern or TARGET_BASE)
    print(f"Archivados: {len(items)}")
    for it in items[:50]:
        print(f"  [{it['ts']}] {it['url']}")
    if len(items) > 50:
        print(f"  … +{len(items) - 50} más")


def cmd_download(args):
    items = list_archived(args.pattern or TARGET_BASE)
    print(f"Encontrados en Wayback: {len(items)} PDFs")
    if not items:
        print("Sin PDFs archivados. Considera 'save' para archivar URLs conocidas.")
        sys.exit(0)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {"ok": 0, "skip": 0, "err": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(download_one, it, out_dir): it for it in items}
        for i, fut in enumerate(as_completed(futs), 1):
            status, url, sz = fut.result()
            if status == "ok":
                stats["ok"] += 1
            elif status.startswith("skip"):
                stats["skip"] += 1
            else:
                stats["err"] += 1
            if i % 10 == 0 or i == len(items):
                print(f"  {i}/{len(items)} ok={stats['ok']} "
                      f"skip={stats['skip']} err={stats['err']}")
    print(f"Done. {stats}")


def cmd_save(args):
    """Forzar Wayback a archivar una URL (Save Page Now)."""
    url = WB_SAVE.format(url=args.url)
    print(f"Solicitando archivo: {url}")
    try:
        with http_get(url, timeout=90) as r:
            print(f"HTTP {r.status}")
    except Exception as e:
        print(f"Error: {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="Listar PDFs archivados en Wayback")
    pl.add_argument("--pattern", help="Patrón CDX (default presidencia 2v)")
    pl.set_defaults(func=cmd_list)

    pd = sub.add_parser("download", help="Bajar PDFs archivados")
    pd.add_argument("--out", default="actas/")
    pd.add_argument("--pattern")
    pd.add_argument("--workers", type=int, default=4)
    pd.set_defaults(func=cmd_download)

    ps = sub.add_parser("save", help="Forzar archivado Wayback Save Page Now")
    ps.add_argument("--url", required=True)
    ps.set_defaults(func=cmd_save)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
