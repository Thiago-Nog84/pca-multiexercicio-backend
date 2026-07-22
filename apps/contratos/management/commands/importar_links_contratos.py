"""
Importa os links dos contratos assinados a partir do Comprasnet Contratos
(contratos.comprasnet.gov.br/api/docs — endpoints públicos, sem autenticação).

Estratégia dupla para maximizar a cobertura:
  1. Consulta a lista de contratos ativos e inativos da UASG (926092 para todo o MPPI).
  2. Para cada contrato local SEM link, consulta individualmente pelo número/ano usando
     o endpoint /api/contrato/ugorigem/{uasg}/numeroano/{numero}.

Para cada contrato encontrado na API:
  - Busca em /api/contrato/{id}/arquivos o documento de tipo "Contrato" e
    grava a URL do PDF assinado em Contrato.link_contrato.
  - Fallback: página pública de transparência do Comprasnet.
  - Grava também Contrato.comprasnet_id para sincronizações futuras.

Uso:
    python manage.py importar_links_contratos [--uasg 926092] [--dry-run]
"""

import re
import time

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.contratos.models import Contrato
from apps.srp.services.comprasnet_contratos import ComprasnetContratosClient

TRANSPARENCIA_URL = "https://contratos.comprasnet.gov.br/transparencia/contratos/{id}"
UASG_MPPI = "926092"


def normalizar_numero(texto):
    """
    Extrai (numero, ano) de formatos como:
        "00005/2026"      -> (5, 2026)   [API]
        "05/2026/FPDC"    -> (5, 2026)   [local]
        "12/2026 FMMPPI"  -> (12, 2026)  [local]
        "01/2025"         -> (1, 2025)   [local]
    Retorna None para formatos sem par número/ano (ex: empenhos "26000035").
    """
    m = re.match(r"\s*0*(\d+)\s*/\s*(\d{4})", str(texto or ""))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def numero_api_from_key(chave):
    """Converte (5, 2026) -> '00005/2026' no formato da API."""
    num, ano = chave
    return f"{num:05d}/{ano}"


def buscar_link(client, contrato_id):
    """Retorna a URL do PDF do instrumento ou a URL de transparência."""
    link = TRANSPARENCIA_URL.format(id=contrato_id)
    try:
        arquivos = client.get_contrato_arquivos(contrato_id)
    except Exception:
        arquivos = []
    for a in arquivos:
        if a.get("tipo") == "Contrato" and a.get("path_arquivo"):
            link = a["path_arquivo"]
            break
    return link


class Command(BaseCommand):
    help = "Importa links dos contratos assinados do Comprasnet Contratos (UASG 926092 = todo o MPPI)."

    def add_arguments(self, parser):
        parser.add_argument("--uasg", default=UASG_MPPI,
                            help="UASG do órgão (926092 para todo o MPPI — PGJ, FMMPPI, FPDC).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Mostra o que seria feito sem gravar.")

    def handle(self, *args, **opts):
        uasg = opts["uasg"]
        dry_run = opts["dry_run"]
        client = ComprasnetContratosClient()

        # ----------------------------------------------------------------
        # Passo 1 — carrega lista da API (ativos + inativos)
        # ----------------------------------------------------------------
        self.stdout.write(f"Buscando contratos da UASG {uasg} no Comprasnet...")
        contratos_api = client.get_contratos_ug(uasg, ativos=True)
        contratos_api += client.get_contratos_ug(uasg, ativos=False)
        self.stdout.write(f"  -> {len(contratos_api)} contrato(s) retornados pela listagem.\n")

        # Índice da API: (numero, ano) -> dados do contrato
        idx_api = {}
        for capi in contratos_api:
            chave = normalizar_numero(capi.get("numero", ""))
            if chave and capi.get("id"):
                idx_api[chave] = capi

        # ----------------------------------------------------------------
        # Passo 2 — carrega contratos locais e monta índice
        # ----------------------------------------------------------------
        todos_locais = list(Contrato.objects.all())
        idx_local = {}   # (numero, ano) -> [Contrato, ...]
        sem_chave = []   # contratos com número fora do padrão (empenhos, etc.)
        for c in todos_locais:
            chave = normalizar_numero(c.numero_contrato)
            if chave:
                idx_local.setdefault(chave, []).append(c)
            else:
                sem_chave.append(c)

        self.stdout.write(
            f"Contratos locais: {len(todos_locais)} total | "
            f"{len(idx_local)} com número padrão | {len(sem_chave)} fora do padrão.\n"
        )

        # ----------------------------------------------------------------
        # Passo 3 — para contratos locais SEM link, consulta individual na API
        # ----------------------------------------------------------------
        sem_link_chaves = {
            chave
            for chave, lista in idx_local.items()
            if any(not c.link_contrato for c in lista) and chave not in idx_api
        }
        if sem_link_chaves:
            self.stdout.write(
                f"Consultando {len(sem_link_chaves)} contrato(s) individualmente na API..."
            )
        for chave in sorted(sem_link_chaves):
            numero_api = numero_api_from_key(chave)
            try:
                dados = client.get_contrato_por_uasg_numero(uasg, numero_api)
                time.sleep(0.3)  # respeita rate-limit da API
                if dados and dados.get("id"):
                    idx_api[chave] = dados
            except Exception as e:
                self.stderr.write(f"  [AVISO] Erro ao consultar {numero_api}: {e}")

        self.stdout.write(
            f"  -> {len(idx_api)} contrato(s) disponíveis na API após busca individual.\n"
        )

        # ----------------------------------------------------------------
        # Passo 4 — aplica links
        # ----------------------------------------------------------------
        atualizados = sem_local = ambiguos = ja_tem_link = 0

        with transaction.atomic():
            for chave, capi in idx_api.items():
                capi_id = capi.get("id")
                if not capi_id:
                    continue

                locais = idx_local.get(chave, [])
                if not locais:
                    sem_local += 1
                    obj_str = str(capi.get("objeto") or "")[:60].encode("ascii", "replace").decode("ascii")
                    self.stdout.write(self.style.WARNING(
                        f"  [SEM LOCAL] {numero_api_from_key(chave)} -- {obj_str}"
                    ))
                    continue

                if len(locais) > 1:
                    ambiguos += 1
                    nums = ", ".join(c.numero_contrato for c in locais)
                    self.stdout.write(self.style.WARNING(
                        f"  [AMBIGUO] {numero_api_from_key(chave)} -> {nums} — pulado"
                    ))
                    continue

                contrato = locais[0]
                if contrato.link_contrato:
                    ja_tem_link += 1
                    continue  # já possui link; não sobrescreve

                link = buscar_link(client, capi_id)
                link_curto = link[:80].encode("ascii", "replace").decode("ascii")
                self.stdout.write(self.style.SUCCESS(
                    f"  [OK] {contrato.numero_contrato} -> {link_curto}"
                ))
                if not dry_run:
                    contrato.link_contrato = link
                    contrato.comprasnet_id = capi_id
                    contrato.save(update_fields=["link_contrato", "comprasnet_id"])
                atualizados += 1

            if dry_run:
                transaction.set_rollback(True)

        modo = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Resultado:"
            f"\n  Links novos aplicados : {atualizados}"
            f"\n  Ja possuiam link      : {ja_tem_link}"
            f"\n  Sem contrato local    : {sem_local}"
            f"\n  Ambiguos (pulados)    : {ambiguos}"
            f"\n  Fora do padrao num.   : {len(sem_chave)}"
        ))
