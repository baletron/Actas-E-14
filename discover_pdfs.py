"""
Descubre patrón URL para PDFs actas E-14 / E-24 / E-26 de la Registraduría.

Inspecciona los SPA de los portales de escrutinio: descarga el HTML, extrae los
bundles JS, y aplica regex para encontrar paths/endpoints PDF.

Uso:
    python discover_pdfs.py
    python discover_pdfs.py --host divulgacione14.registraduria.gov.co
"""

import argparse
import re
import ssl
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

DEFAULT_HOSTS = [
    "https://escrutiniospresidente2026.registraduria.gov.co/publicadas",
    "https://escrutiniospresidente2026.registraduria.gov.co/",
    "https://divulgacione14.registraduria.gov.co/",
    "https://divulgacione14congreso.registraduria.gov.co/",
]

SCRIPT_RE = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
URL_RE = re.compile(r'https?://[a-zA-Z0-9._/?=&:%+-]+')
PATH_RE = re.compile(r'"(/[a-zA-Z0-9_./?=&${}:%+-]{3,})"')
TEMPLATE_RE = re.compile(r'`([^`]*\$\{[^`]+\}[^`]*)`')


def fetch(url, referer=None):
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "es-CO,es;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as r:
        return r.read()


def discover(start_url, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    host_dir = out_dir / urlparse(start_url).hostname.replace(".", "_")
    host_dir.mkdir(exist_ok=True)

    print(f"\n=== {start_url} ===")
    try:
        html = fetch(start_url).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [!] fetch falló: {e}")
        return

    (host_dir / "index.html").write_text(html, encoding="utf-8")

    scripts = SCRIPT_RE.findall(html)
    print(f"  {len(scripts)} scripts encontrados")
    all_text = html
    for s in scripts:
        js_url = urljoin(start_url, s)
        try:
            js = fetch(js_url, referer=start_url).decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  [!] {js_url}: {e}")
            continue
        fname = Path(urlparse(js_url).path).name or "bundle.js"
        (host_dir / fname).write_text(js, encoding="utf-8")
        all_text += "\n" + js
        print(f"    + {fname} ({len(js)} bytes)")

    # Extraer candidatos
    urls = sorted(set(URL_RE.findall(all_text)))
    paths = sorted(set(PATH_RE.findall(all_text)))
    templates = sorted(set(TEMPLATE_RE.findall(all_text)))

    interesting_kw = ("pdf", "acta", "e14", "e_14", "e-14", "e24", "e26",
                      "escrutinio", "documento", "publicad", "consulta")
    candidates = []
    for s in urls + paths + templates:
        low = s.lower()
        if any(k in low for k in interesting_kw):
            candidates.append(s)

    report = host_dir / "report.txt"
    with report.open("w", encoding="utf-8") as f:
        f.write(f"# Discovery report: {start_url}\n\n")
        f.write(f"## Candidatos PDF/actas ({len(candidates)})\n")
        for c in candidates:
            f.write(f"  {c}\n")
        f.write(f"\n## Todos los paths ({len(paths)})\n")
        for p in paths:
            f.write(f"  {p}\n")
        f.write(f"\n## URLs absolutas ({len(urls)})\n")
        for u in urls:
            f.write(f"  {u}\n")
        f.write(f"\n## Template literals con ${{}} ({len(templates)})\n")
        for t in templates:
            f.write(f"  {t}\n")

    print(f"  Reporte -> {report}")
    print(f"  {len(candidates)} candidatos PDF/actas")
    for c in candidates[:15]:
        print(f"    {c}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", action="append",
                    help="URL inicial (repetible). Default = portales conocidos.")
    ap.add_argument("--out", default="discovery", help="Carpeta salida")
    args = ap.parse_args()

    hosts = args.host or DEFAULT_HOSTS
    for h in hosts:
        try:
            discover(h, args.out)
        except KeyboardInterrupt:
            sys.exit(1)
        except Exception as e:
            print(f"[!] {h}: {e}")


if __name__ == "__main__":
    main()
