# Scraper Registraduría Nacional — Elecciones Presidenciales Colombia 2026

Suite de scripts Python (stdlib + certifi) para extraer datos electorales públicos
desde los portales oficiales de la Registraduría Nacional del Estado Civil.

## Estado actual (2026-06-23)

- ✅ Resultados JSON (1ra + 2da vuelta) → CSV plano por país / depto / muni
- ✅ Nomenclator territorial (1224 ámbitos: 1 país, 34 deptos, 1189 munis)
- ✅ Patrón URL PDFs actas E-14 **descifrado por ingeniería inversa** del
      bundle Angular del SPA oficial (Wayback snapshot 2026-06-22)
- ✅ 1 acta de prueba descargada vía Wayback Machine (Antioquia, muni 127,
      zona 099, puesto 55, mesa 001)
- ⚠️ Catálogo completo de hashes SHA256 (122k mesas) requiere acceso a
      `e14segundavueltapresidente.registraduria.gov.co/assets/temis/divipol_json/allTransmissionCodes.json`
      desde IP no bloqueada por Akamai (residencial Colombia)

## Patrón URL actas E-14 (descifrado)

```
https://e14segundavueltapresidente.registraduria.gov.co/assets/temis/pdf/
    {dep2}/{mun3}/{zon3}/{stand2}/{mesa3}/{CORP}/{sha256}.pdf
```

Ejemplo verificado:
```
.../assets/temis/pdf/01/127/099/55/001/PRE/f92d13390e9c24d549e0a8beee131928086526aeee159e5f964b7caef0e1ba28.pdf
```

- `dep2`: código depto interno Registraduría (2 dígitos)
- `mun3`: muni (3 dígitos)
- `zon3`: zona (3 dígitos)
- `stand2`: puesto (2 dígitos)
- `mesa3`: mesa (3 dígitos)
- `CORP`: acrónimo corporación — `PRE` para PRESIDENTE
- `{sha256}.pdf`: hash SHA-256 del documento (**no enumerable**)

**NO requiere captcha.** Archivos estáticos. Sólo Referer del SPA.

## Arquitectura completa descubierta

- Frontend: Angular SPA en `e14segundavueltapresidente.registraduria.gov.co` (Akamai)
- API GraphQL: `apx2e14awsprodpresidenciav2.prdtpssas.com/graphql` (AWS AppSync, Akamai-fronted)
- Auth API: AWS Cognito Identity Pool **público** `us-east-2:f44a557a-d26b-4f14-8a4d-1de5a0b0f7aa`
  + IAM SigV4 con creds temporales unauthenticated role
- Recaptcha siteKey: `6LeGPAstAAAAAP5Y9DpTIUqzpFv5bGrZHm6azHaS` (solo para form submission ciudadana, NO afecta PDFs estáticos)
- GraphQL queries identificadas: `CorpIndexAndMap`, `DepartmentsTree`,
  `TransmissionCodesByStand`, `OnTableChange` (subscription)

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

### 2. Descargar PDFs actas E-14 (necesita red Colombia)

```bash
# Bajar catálogo (única vez, ~MB)
python download_actas.py fetch-catalog --out catalog.json

# Bajar PDFs sólo de Antioquia (15,801 mesas esperadas)
python download_actas.py download --from-catalog catalog.json \
    --depto 01 --out actas/ --workers 8 --throttle-ms 120

# Bajar todos los PDFs nacionales (122k mesas, ~30GB estimado)
python download_actas.py download --from-catalog catalog.json \
    --out actas/ --workers 16 --throttle-ms 80
```

### 3. Fallback: Wayback Machine

Cuando el sitio original es inaccesible (geo-block, firewall, sitio caído),
Wayback Machine sirve snapshots de PDFs ya archivados:

```bash
# Listar PDFs archivados
python fetch_via_wayback.py list

# Descargar todos
python fetch_via_wayback.py download --out actas/

# Forzar archivado de URL específica
python fetch_via_wayback.py save --url "https://e14segundavueltapresidente.../xxx.pdf"
```

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
