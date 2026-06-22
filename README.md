# Scraper Registraduría Nacional — Elecciones Presidenciales Colombia 2026

Suite de scripts Python (stdlib + certifi) para extraer datos electorales públicos
desde los portales oficiales de la Registraduría Nacional del Estado Civil.

## Estado actual (2026-06-22)

- ✅ Resultados JSON (1ra + 2da vuelta) → CSV plano por país / depto / muni
- ✅ Nomenclator territorial (1224 ámbitos: 1 país, 34 deptos, 1189 munis)
- ⚠️ PDFs de actas (E-14/E-24/E-26): requiere descubrir patrón URL del portal
      `escrutiniospresidente2026.registraduria.gov.co` (bloqueado desde sandbox
      Anthropic, accesible desde red residencial normal)

## Endpoints descubiertos

Host: `https://resultados.registraduria.gov.co`

| Path | Contenido |
|------|-----------|
| `/json/web/config.json` | Configuración app (fase, polling 5s) |
| `/json/nomenclator.json` | Árbol territorial completo |
| `/json/notification.json` | Versión + timestamp `mdhm` |
| `/json/ACT/PR/{scope}.json` | Resultados **1ra vuelta** (mayo 31) |
| `/json/INI/PR/IN_{scope}.json` | Carga inicial |
| `/json/EST/PR/EST_{stat}.json` | Estadísticas |
| `/json/HIST/{depto}/PR/{advance}/{scope}.json` | Histórico boletines |
| `/maps/{scope}.geojson` | Polígonos GeoJSON |
| `/v2/json/ACT/PR/{scope}.json` | Resultados **2da vuelta** (junio 21) |

Requisitos anti-bot (CloudFront):
- Header `User-Agent` de navegador real
- Header `Referer: https://resultados.registraduria.gov.co/` (o `/v2/...` para v2)

## Uso

### 1. Resultados JSON

```bash
# 2da vuelta, todos los niveles (país + 34 deptos + 1189 munis)
python scrape_resultados.py --round 2 --level all --out elecciones_2026 --raw

# Ambas vueltas, solo agregado nacional + departamentos
python scrape_resultados.py --round both --level depto --out elecciones_2026

# Solo país (smoke test rápido)
python scrape_resultados.py --round 2 --level pais --out test
```

Salida:
```
elecciones_2026/
├── nomenclator_v1.json
├── nomenclator_v2.json
├── resultados_v1.csv         # 15,913 filas (1ra vuelta, 11 candidatos × 1224 ámbitos)
├── resultados_v2.csv         # 2,448 filas (2da vuelta, 2 candidatos × 1224 ámbitos)
├── raw_v1/                   # JSON crudo por ámbito (con --raw)
└── raw_v2/
```

### 2. Descubrir patrón URL de PDFs de actas

```bash
# Genera reporte con todos endpoints/paths/URLs candidatas
python discover_pdfs.py --out discovery
```

Inspecciona `discovery/<host>/report.txt`. Busca rutas con `pdf`, `acta`, `e14`,
`documento`. Una vez identificado el patrón:

### 3. Descargar PDFs en masa

```bash
python download_actas.py \
    --template "https://escrutiniospresidente2026.registraduria.gov.co/api/.../{scope_code}/E14.pdf" \
    --nomenclator elecciones_2026/nomenclator_v2.json \
    --out actas/ \
    --max 100 \
    --workers 8 \
    --throttle-ms 150
```

Placeholders disponibles en `--template`:
- `{scope_code}` → código completo (ej. `01001`)
- `{depto}` → 2 dígitos depto (ej. `01`)
- `{muni}` → 3 dígitos muni (ej. `001`)
- `{mesa}` → número de mesa (requiere `--mesa-range`)
- `{puesto}` → número de puesto

## Datos verificados (snapshot 2026-06-21 21:34, 99.99% mesas)

**Segunda vuelta presidencial:**
- Censo: 41,421,973
- Votantes: 26,345,364 (63.60% participación)
- Blancos: 426,848 · Nulos: 220,763

| Fórmula | Votos | % |
|---------|-------|---|
| Abelardo De La Espriella / José Manuel Restrepo Abondano | 12,959,542 | 49.66% |
| Iván Cepeda Castro / Aida Marina Quilcué Vivas | 12,708,712 | 48.70% |

## Notas técnicas

- **Codificación**: respuestas son UTF-8 correcto. Si la consola muestra glifos
  raros (`IV�N`), es problema visual del terminal — el archivo CSV está bien.
  Abrir en Excel / VS Code para verificar.
- **Polling**: backend actualiza cada ~5s en jornada electoral. Scrape periódico
  posible con un loop simple + diff de `notification.json`.
- **Códigos de ámbito**: NO son DANE oficiales. Son códigos internos de la
  Registraduría (2 dígitos depto + 3 dígitos muni para nivel 3).
- **Encoding latin-1 mojibake**: NO ocurre. Aclaración: backend sirve UTF-8
  válido; el byte sequence `0xC3 0x81` es `Á` correcto.

## Estructura JSON `/json/ACT/PR/{scope}.json`

```jsonc
{
  "elec": "1",                    // Elección (PR=presidencial)
  "amb": "00",                    // Código ámbito
  "tope": "2",                    // Phase (1=preconteo, 2=escrutinio)
  "numact": "66",                 // # acta/boletín
  "numdep": "66",                 // # avance dep
  "mdhm": "06212134",             // Timestamp MMDDHHmm
  "totales": {
    "act": { "metota": "...", "mesesc": "...", "votant": "...", ... }
  },
  "camaras": [{
    "cir": "1",
    "partotabla": [{
      "act": {
        "codpar": "3",
        "vot": "12959542",
        "pvot": "49,66%",
        "cantotabla": [{
          "codcan": "2",
          "cedula": "11004242",
          "nomcan": "ABELARDO",
          "apecan": "DE LA ESPRIELLA",
          "nomcan2": "JOSÉ MANUEL",
          "apecan2": "RESTREPO ABONDANO",
          "vot": "12959542",
          "pvot": "49,66%",
          "pref": "1"
        }]
      }
    }]
  }],
  "historico": [{ "numact": "65", "mdhm": "...", ... }]
}
```

## Cumplimiento

Estos datos son **públicos** por mandato de la ley electoral colombiana
(Ley 1475/2011, Decreto 2241/1986). El acceso vía API es uso legítimo de
información oficial publicada. Respeta `--throttle-ms` para no abusar de la
infraestructura.
