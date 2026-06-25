"""
Diagnóstico de autenticação — Comprasnet Contratos API
=======================================================
Executa: python diagnostico_comprasnet_auth.py

Testa diferentes formatos de payload para POST /api/v1/auth/login
e exibe a resposta completa de cada tentativa.

Preencha CPF e SENHA antes de executar.
"""

import json
import os
import sys

import requests

# ── Credenciais ────────────────────────────────────────────────
CPF   = os.environ.get("COMPRASNET_CONTRATOS_CPF",   "")   # ou coloque direto aqui
SENHA = os.environ.get("COMPRASNET_CONTRATOS_SENHA", "")   # ou coloque direto aqui

if not CPF or not SENHA:
    print("ERRO: defina as variáveis COMPRASNET_CONTRATOS_CPF e COMPRASNET_CONTRATOS_SENHA")
    print("  set COMPRASNET_CONTRATOS_CPF=000.000.000-00")
    print("  set COMPRASNET_CONTRATOS_SENHA=SuaSenha")
    sys.exit(1)

# CPF sem formatação
CPF_LIMPO = CPF.replace(".", "").replace("-", "").strip()

BASE = "https://contratos.comprasnet.gov.br"
URL  = f"{BASE}/api/v1/auth/login"

# ── Formatos a testar ──────────────────────────────────────────
FORMATOS = [
    # Mais prováveis para APIs de governo brasileiras
    {"cpf": CPF_LIMPO,   "senha": SENHA},
    {"cpf": CPF,         "senha": SENHA},
    {"username": CPF_LIMPO, "password": SENHA},
    {"username": CPF,    "password": SENHA},
    {"login": CPF_LIMPO, "senha": SENHA},
    {"login": CPF,       "senha": SENHA},
    # Formato Django REST Framework padrão
    {"username": CPF_LIMPO, "senha": SENHA},
    # Com campo "usuario"
    {"usuario": CPF_LIMPO, "senha": SENHA},
    {"usuario": CPF,       "senha": SENHA},
]

print(f"{'='*60}")
print(f"Testando: {URL}")
print(f"CPF:  {CPF_LIMPO} (formatado: {CPF})")
print(f"{'='*60}\n")

session = requests.Session()
session.headers.update({
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "MPPI-PCA-Diagnostico/1.0",
})

for i, payload in enumerate(FORMATOS, 1):
    payload_str = json.dumps(payload)
    campos = list(payload.keys())
    print(f"[{i}/{len(FORMATOS)}] Payload: {payload_str}")

    try:
        resp = session.post(URL, json=payload, timeout=20)
        status = resp.status_code

        # Tenta parsear JSON
        try:
            body = resp.json()
            body_str = json.dumps(body, ensure_ascii=False, indent=2)
        except Exception:
            body_str = resp.text[:500]

        if status == 200:
            print(f"  ✅ STATUS {status} — SUCESSO!")
            print(f"  Resposta: {body_str[:300]}")

            # Extrai e mostra o token
            if isinstance(body, dict):
                token = (body.get("token") or body.get("access") or
                         body.get("access_token") or body.get("jwt") or "")
                if token:
                    print(f"\n  🔑 TOKEN: {token[:60]}...")
                    print(f"\n  ✅ CAMPO DE TOKEN: '{next((k for k in body if body[k] == token), 'desconhecido')}'")
            print(f"\n  ► FORMATO CORRETO: {payload_str}")
            sys.exit(0)

        elif status == 400:
            print(f"  ⚠️  STATUS 400 — Bad Request (campos incorretos ou faltando)")
            print(f"  Resposta: {body_str[:200]}")

        elif status == 401:
            print(f"  ❌ STATUS 401 — Não autorizado (formato pode estar ok, credencial errada?)")
            print(f"  Resposta: {body_str[:200]}")

        elif status == 404:
            print(f"  ⚠️  STATUS 404 — Endpoint não encontrado")

        elif status == 405:
            print(f"  ⚠️  STATUS 405 — Método não permitido")

        elif status == 422:
            print(f"  ⚠️  STATUS 422 — Unprocessable Entity (validação falhou)")
            print(f"  Resposta: {body_str[:300]}")

        else:
            print(f"  ?  STATUS {status}")
            print(f"  Resposta: {body_str[:200]}")

    except requests.RequestException as e:
        print(f"  💥 Erro de conexão: {e}")

    print()

print("="*60)
print("Nenhum formato retornou 200.")
print()
print("Próximos passos:")
print("  1. Verifique se CPF e senha estão corretos no Comprasnet")
print("  2. Acesse https://contratos.comprasnet.gov.br/api/docs")
print("     → seção 'Autenticação' → veja o schema do POST /api/v1/auth/login")
print("  3. Verifique se sua conta tem acesso à UG 926092")
