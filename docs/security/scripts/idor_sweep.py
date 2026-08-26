"""Sweep de IDOR: agência A tentando alcançar recursos da agência B.

Três controles por endpoint:
  1. sem token          -> espera 401 (prova que a rota existe e exige auth)
  2. token A + id de B  -> espera 403/404 (o teste de IDOR propriamente dito)
  3. token A + id de A  -> espera 2xx (controle positivo, só em GET)
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:5001/api/v1"


def login(email):
    req = urllib.request.Request(
        f"{BASE}/auth/dev-login",
        data=json.dumps({"email": email}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["data"]["tokens"]["access_token"]


def call(method, path, token=None):
    req = urllib.request.Request(f"{BASE}{path}", method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if method in ("POST", "PATCH", "PUT"):
        req.add_header("Content-Type", "application/json")
        req.data = b"{}"
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        return f"ERR {type(e).__name__}"


A = json.load(open(sys.argv[1]))
B = json.load(open(sys.argv[2]))
tok_a = login("marina@lumina-agency.com.br")

# (método, template, chave do id, roda controle positivo?)
CASES = [
    ("GET",    "/agencies/{agency_id}",                    "agency_id",         True),
    ("PATCH",  "/agencies/{agency_id}",                    "agency_id",         False),
    ("DELETE", "/agencies/{agency_id}",                    "agency_id",         False),
    ("GET",    "/agencies/{agency_id}/usage",              "agency_id",         True),
    ("GET",    "/users/{user_id}",                         "user_id",           True),
    ("PATCH",  "/users/{user_id}",                         "user_id",           False),
    ("DELETE", "/users/{user_id}",                         "user_id",           False),
    ("GET",    "/influencers/{influencer_id}",             "influencer_id",     True),
    ("PATCH",  "/influencers/{influencer_id}",             "influencer_id",     False),
    ("DELETE", "/influencers/{influencer_id}",             "influencer_id",     False),
    ("GET",    "/influencers/{influencer_id}/analysis",    "influencer_id",     True),
    ("GET",    "/influencers/{influencer_id}/posts",       "influencer_id",     True),
    ("POST",   "/influencers/{influencer_id}/sync",        "influencer_id",     False),
    ("GET",    "/social-accounts/{social_account_id}",     "social_account_id", True),
    ("PATCH",  "/social-accounts/{social_account_id}",     "social_account_id", False),
    ("DELETE", "/social-accounts/{social_account_id}",     "social_account_id", False),
    ("POST",   "/integrations/instagram/disconnect/{social_account_id}",
                                                           "social_account_id", False),
    ("GET",    "/campaigns/{campaign_id}",                 "campaign_id",       True),
    ("PATCH",  "/campaigns/{campaign_id}",                 "campaign_id",       False),
    ("DELETE", "/campaigns/{campaign_id}",                 "campaign_id",       False),
    ("GET",    "/campaigns/{campaign_id}/benchmarking",    "campaign_id",       True),
    ("GET",    "/posts/{post_id}",                         "post_id",           True),
    ("GET",    "/posts/{post_id}/analyses",                "post_id",           True),
    ("POST",   "/posts/{post_id}/analyze",                 "post_id",           False),
    ("GET",    "/reports/{report_id}",                     "report_id",         True),
    ("GET",    "/reports/{report_id}/download",            "report_id",         True),
]

rows = []
for method, tpl, key, positive in CASES:
    path_b = tpl.format(**B)
    no_token = call(method, path_b)
    cross = call(method, path_b, tok_a)
    own = call(method, tpl.format(**A), tok_a) if positive else "—"

    route_ok = no_token == 401
    blocked = cross in (403, 404)
    own_ok = (own == "—") or (isinstance(own, int) and 200 <= own < 300)
    verdict = "PASSOU" if (route_ok and blocked and own_ok) else "FALHOU"
    rows.append((method, tpl, no_token, cross, own, verdict))

w = max(len(t) for _, t, *_ in rows)
print(f"{'MÉTODO':7} {'ENDPOINT':{w}} {'S/TOKEN':>8} {'A→B':>6} {'A→A':>6}  VEREDITO")
for m, t, nt, cx, ow, v in rows:
    print(f"{m:7} {t:{w}} {str(nt):>8} {str(cx):>6} {str(ow):>6}  {v}")

falhas = [r for r in rows if r[5] == "FALHOU"]
print(f"\n{len(rows)} casos · {len(rows)-len(falhas)} passaram · {len(falhas)} falharam")
