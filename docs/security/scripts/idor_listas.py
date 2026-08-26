"""Verifica se as listagens vazam recursos da outra agência."""
import json
import sys
import urllib.request

BASE = "http://localhost:5001/api/v1"


def login(email):
    req = urllib.request.Request(f"{BASE}/auth/dev-login",
                                 data=json.dumps({"email": email}).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["data"]["tokens"]["access_token"]


def get(path, token):
    req = urllib.request.Request(f"{BASE}{path}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def ids_of(payload):
    data = payload.get("data", payload)
    items = data.get("items", data) if isinstance(data, dict) else data
    return {i["id"] for i in items if isinstance(i, dict) and "id" in i}


B = json.load(open(sys.argv[1]))
tok_a = login("marina@lumina-agency.com.br")

CHECKS = [
    ("/influencers?per_page=200",     "influencer_id"),
    ("/campaigns?per_page=200",       "campaign_id"),
    ("/users?per_page=200",           "user_id"),
    ("/social-accounts?per_page=200", "social_account_id"),
    ("/reports?per_page=200",         "report_id"),
    ("/agencies",                     "agency_id"),
]

print(f"{'LISTAGEM':32} {'ITENS':>6}  RECURSO DE B PRESENTE?")
falhas = 0
for path, key in CHECKS:
    got = ids_of(get(path, tok_a))
    leaked = B[key] in got
    falhas += leaked
    print(f"{path.split('?')[0]:32} {len(got):>6}  {'SIM — VAZOU' if leaked else 'não'}")
print(f"\n{len(CHECKS)} listagens · {len(CHECKS)-falhas} isoladas · {falhas} com vazamento")
