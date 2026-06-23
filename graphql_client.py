"""
Cliente GraphQL para AWS AppSync de la Registraduría usando Cognito Identity
Pool (acceso unauthenticated/guest) + AWS SigV4.

Config descubierta del bundle SPA:
    graphqlUrl:          https://apx2e14awsprodpresidenciav2.prdtpssas.com/graphql
    region:              us-east-2
    cognitoIdentityPoolId: us-east-2:f44a557a-d26b-4f14-8a4d-1de5a0b0f7aa
    defaultAuthMode:     iam (SigV4)
    allowGuestAccess:    true

Sin certifi/boto3 requeridos — implementa SigV4 con stdlib.
"""

import datetime
import hashlib
import hmac
import json
import ssl
import sys
import urllib.parse
import urllib.request
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

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# === Config oficial del SPA ===
GRAPHQL_URL = "https://apx2e14awsprodpresidenciav2.prdtpssas.com/graphql"
REGION = "us-east-2"
IDENTITY_POOL_ID = "us-east-2:f44a557a-d26b-4f14-8a4d-1de5a0b0f7aa"
COGNITO_ENDPOINT = f"https://cognito-identity.{REGION}.amazonaws.com/"
SERVICE = "appsync"

# === Query exacto del bundle ===
QUERY_TRANSMISSION_CODES = """
query TransmissionCodesByStand(
  $idCorporationCode: String!,
  $first: Int!,
  $idDepartmentCode: String,
  $municipalityCode: String,
  $idZoneCode: String,
  $standCode: String
) {
  status11: allTransmissionCodes(
    first: $first
    condition: {
      idTransmissionCodeStatus: 11
      idCorporationCode: $idCorporationCode
      idDepartmentCode: $idDepartmentCode
      municipalityCode: $municipalityCode
      idZoneCode: $idZoneCode
      standCode: $standCode
    }
  ) {
    nodes {
      idStand
      numberStand
      idDepartmentCode
      municipalityCode
      idZoneCode
      standCode
      idCorporationCode
      expectedName
    }
  }
  status3: allTransmissionCodes(
    first: $first
    condition: {
      idTransmissionCodeStatus: 3
      idCorporationCode: $idCorporationCode
      idDepartmentCode: $idDepartmentCode
      municipalityCode: $municipalityCode
      idZoneCode: $idZoneCode
      standCode: $standCode
    }
  ) {
    nodes {
      idStand
      numberStand
      idDepartmentCode
      municipalityCode
      idZoneCode
      standCode
      idCorporationCode
      expectedName
    }
  }
}
"""


def cognito_get_id():
    payload = json.dumps({"IdentityPoolId": IDENTITY_POOL_ID}).encode()
    req = urllib.request.Request(
        COGNITO_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityService.GetId",
            "User-Agent": UA,
        },
    )
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        return json.loads(r.read())["IdentityId"]


def cognito_get_credentials(identity_id):
    payload = json.dumps({"IdentityId": identity_id}).encode()
    req = urllib.request.Request(
        COGNITO_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityService.GetCredentialsForIdentity",
            "User-Agent": UA,
        },
    )
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        return json.loads(r.read())["Credentials"]


def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signature_key(secret_key, date_stamp, region, service):
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def sigv4_post(url, body_bytes, access_key, secret_key, session_token,
               region, service, extra_headers=None):
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    canonical_uri = parsed.path or "/"
    canonical_query = parsed.query or ""

    now = datetime.datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(body_bytes).hexdigest()

    headers = {
        "host": host,
        "content-type": "application/json; charset=UTF-8",
        "x-amz-date": amz_date,
        "x-amz-security-token": session_token,
    }
    if extra_headers:
        headers.update({k.lower(): v for k, v in extra_headers.items()})

    sorted_h = sorted(headers.items())
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted_h)
    signed_headers = ";".join(k for k, _ in sorted_h)

    canonical_request = "\n".join([
        "POST",
        canonical_uri,
        canonical_query,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    signing_key = _signature_key(secret_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode(),
                         hashlib.sha256).hexdigest()

    auth_header = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    final_headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json; charset=UTF-8",
        "X-Amz-Date": amz_date,
        "X-Amz-Security-Token": session_token,
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://e14segundavueltapresidente.registraduria.gov.co",
        "Referer": "https://e14segundavueltapresidente.registraduria.gov.co/",
    }
    if extra_headers:
        final_headers.update(extra_headers)

    req = urllib.request.Request(url, data=body_bytes, headers=final_headers,
                                 method="POST")
    return urllib.request.urlopen(req, timeout=90, context=SSL_CTX)


class AppSyncClient:
    def __init__(self):
        print("[cognito] obteniendo IdentityId…")
        self.identity_id = cognito_get_id()
        print(f"[cognito] IdentityId: {self.identity_id}")
        print("[cognito] obteniendo credenciales temporales…")
        c = cognito_get_credentials(self.identity_id)
        self.access_key = c["AccessKeyId"]
        self.secret_key = c["SecretKey"]
        self.session_token = c["SessionToken"]
        print("[cognito] OK, creds válidos por ~1h")

    def graphql(self, query, variables=None, operation_name=None):
        body = json.dumps({
            "query": query,
            "variables": variables or {},
            "operationName": operation_name,
        }).encode("utf-8")
        with sigv4_post(GRAPHQL_URL, body,
                        self.access_key, self.secret_key, self.session_token,
                        REGION, SERVICE) as r:
            return json.loads(r.read())


def query_transmission_codes(client, corp="001", dep=None, mun=None,
                             zon=None, stand=None, first=10000):
    vars_ = {"idCorporationCode": corp, "first": first}
    if dep: vars_["idDepartmentCode"] = str(dep).zfill(2)
    if mun: vars_["municipalityCode"] = str(mun).zfill(3)
    if zon: vars_["idZoneCode"] = str(zon).zfill(3)
    if stand: vars_["standCode"] = str(stand).zfill(2)
    return client.graphql(QUERY_TRANSMISSION_CODES, vars_,
                          "TransmissionCodesByStand")


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--depto", help="Código depto 2 dig (ej. 01)")
    ap.add_argument("--muni", help="Muni 3 dig")
    ap.add_argument("--zona", help="Zona 3 dig")
    ap.add_argument("--stand", help="Stand 2 dig")
    ap.add_argument("--first", type=int, default=10000)
    ap.add_argument("--out", default="catalog_graphql.json")
    args = ap.parse_args()

    cli = AppSyncClient()
    print(f"[graphql] consultando TransmissionCodesByStand "
          f"(dep={args.depto}, mun={args.muni}, zona={args.zona}, "
          f"stand={args.stand}, first={args.first})…")
    result = query_transmission_codes(cli, dep=args.depto, mun=args.muni,
                                      zon=args.zona, stand=args.stand,
                                      first=args.first)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False),
                              encoding="utf-8")
    nodes11 = result.get("data", {}).get("status11", {}).get("nodes", []) or []
    nodes3 = result.get("data", {}).get("status3", {}).get("nodes", []) or []
    print(f"[graphql] status11 nodes: {len(nodes11)}")
    print(f"[graphql] status3  nodes: {len(nodes3)}")
    print(f"[out] {args.out}")
    if result.get("errors"):
        print("ERRORS:", result["errors"], file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
