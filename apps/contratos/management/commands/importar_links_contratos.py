"""
Importa os links dos contratos assinados a partir do Comprasnet Contratos
(contratos.comprasnet.gov.br/api/docs — endpoints públicos, sem autenticação).

Para cada contrato da UASG na API:
1. Normaliza o número ("00005/2026" → (5, 2026)) e casa com o
   `contratos.Contrato` local, cujos números vêm em formatos variados
   ("05/2026/FPDC", "12/2026 FMMPPI", "28/2026 PGJ").
2. Busca em /api/contrato/{id}/arquivos o documento de tipo "Contrato" e
   grava a URL do PDF assinado em `Contrato.link_contrato`
   (fallback: página pública de transparência do Comprasnet).
3. Grava também `Contrato.comprasnet_id` para sincronizações futuras.

Também preenche `srp.ContratacaoDecorrente.link_contrato` quando o
`numero_contrato` dela casar com um contrato da API (hoje esse campo está
vazio nas contratações históricas — o casamento passará a funcionar conforme
forem preenchidos).

Uso:
    python manage.py importar_links_contratos [--uasg 926092] [--dry-run]
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.contratos.models import Contrato
from apps.srp.models import ContratacaoDecorrente
from apps.srp.services.comprasnet_contratos import ComprasnetContratosClient

TRANSPARENCIA_URL = "https://contratos.comprasnet.gov.br/transparencia/contratos/{id}"


def normalizar_numero(texto):
    """
    Extrai (numero, ano) de formatos como:
        "00005/2026"      → (5, 2026)   [API]
        "05/2026/FPDC"    → (5, 2026)   [local]
        "12/2026 FMMPPI"  → (5, 2026)   [local]
    Retorna None para formatos sem par número/ano (ex: empenhos "26000035").
    """
    m = re.match(r"\s*0*(\d+)\s*/\s*(\d{4})", str(texto or ""))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


class Command(BaseCommand):
    help = "Importa links dos contratos assinados do Comprasnet Contratos."

    def add_arguments(self, parser):
        parser.add_argument("--uasg", default="926092")
        parser.add_argument("--dry-run", action="store_true",
                            help="Mostra o que seria feito sem gravar.")

    def handle(self, *args, **opts):
        client = ComprasnetContratosClient()

        contratos_api = client.get_contratos_ug(opts["uasg"], ativos=True)
        contratos_api += client.get_contratos_ug(opts["uasg"], ativos=False)
        self.stdout.write(
            f"Comprasnet retornou {len(contratos_api)} contrato(s) da UASG {opts['uasg']}.\n"
        )

        # Índices locais por (numero, ano) normalizado
        idx_contratos = {}
        for c in Contrato.objects.all():
            chave = normalizar_numero(c.numero_contrato)
            if chave:
                idx_contratos.setdefault(chave, []).append(c)

        idx_cds = {}
        for cd in ContratacaoDecorrente.objects.exclude(numero_contrato=""):
            chave = normalizar_numero(cd.numero_contrato)
            if chave:
                idx_cds.setdefault(chave, []).append(cd)

        atualizados = cds_atualizadas = sem_local = ambiguos = 0

        with transaction.atomic():
            for capi in contratos_api:
                numero_api = capi.get("numero", "")
                capi_id = capi.get("id")
                chave = normalizar_numero(numero_api)
                if not chave or not capi_id:
                    continue

                # Link: PDF assinado (arquivos) ou página de transparência
                link = TRANSPARENCIA_URL.format(id=capi_id)
                try:
                    arquivos = client.get_contrato_arquivos(capi_id)
                except Exception as e:  # noqa: BLE001
                    arquivos = []
                    self.stderr.write(f"  arquivos indisponíveis para {numero_api}: {e}")
                for a in arquivos:
                    if a.get("tipo") == "Contrato" and a.get("path_arquivo"):
                        link = a["path_arquivo"]
                        break

                locais = idx_contratos.get(chave, [])
                if not locais:
                    sem_local += 1
                    self.stdout.write(self.style.WARNING(
                        f"  [SEM CONTRATO LOCAL] {numero_api} — "
                        f"{(capi.get('objeto') or '')[:55]}"
                    ))
                elif len(locais) > 1:
                    ambiguos += 1
                    nums = ", ".join(c.numero_contrato for c in locais)
                    self.stdout.write(self.style.WARNING(
                        f"  [AMBÍGUO] {numero_api} casa com {len(locais)} locais ({nums}) — pulado"
                    ))
                else:
                    contrato = locais[0]
                    self.stdout.write(
                        f"  [OK] {numero_api} -> {contrato.numero_contrato} | {link[:70]}"
                    )
                    if not opts["dry_run"]:
                        contrato.link_contrato = link
                        contrato.comprasnet_id = capi_id
                        contrato.save(update_fields=["link_contrato", "comprasnet_id"])
                    atualizados += 1

                for cd in idx_cds.get(chave, []):
                    if not opts["dry_run"]:
                        cd.link_contrato = link
                        cd.save(update_fields=["link_contrato"])
                    cds_atualizadas += 1

            if opts["dry_run"]:
                transaction.set_rollback(True)

        modo = "[DRY-RUN — nada gravado] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Contratos atualizados: {atualizados} | "
            f"Contratações decorrentes atualizadas: {cds_atualizadas} | "
            f"Sem contrato local: {sem_local} | Ambíguos: {ambiguos}"
        ))
        if sem_local:
            self.stdout.write(
                "Dica: contratos 'sem local' existem no Comprasnet mas não no módulo "
                "de Contratos — cadastre-os lá para que o link seja aplicado na próxima execução."
            )
