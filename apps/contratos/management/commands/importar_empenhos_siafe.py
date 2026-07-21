"""
Importa as Notas de Empenho (NEs) do SIAFE-PI como linhas individuais de
`contratos.Empenho`, vinculadas aos contratos locais.

Diferença para `atualizar_execucao_siafe`: aquele comando apenas soma o
empenhado por contrato e grava o agregado em `Contrato.valor_empenhado`.
Este PERSISTE cada NE (número, valor, credor, natureza, fonte, programa de
trabalho, data, observação) — dando o detalhamento nota a nota. Ao final,
também atualiza o agregado `Contrato.valor_empenhado` (líquido de anulações),
mantendo os dois consistentes.

Fonte: apps.siafe.client.SiafeClient (API SEFAZ-PI, credenciais no .env que
FUNCIONAM — diferente da API federal Comprasnet, que não tem empenhos do MPPI).

Vínculo NE↔contrato: campo `codContrato` da NE (código SIAFE de 8 dígitos)
casa com `Contrato.codigo_siafe`.

Uso:
    python manage.py importar_empenhos_siafe [--exercicio 2026] [--ug 250101] [--dry-run]
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.contratos.models import Contrato, Empenho
from apps.siafe.client import SiafeAPIError, SiafeClient

UGS_MPPI = ["250101", "250102", "250104"]

# modalidade SIAFE → Empenho.NATUREZA
NATUREZA_MAP = {"GLOBAL": "global", "ESTIMATIVO": "estimativo", "ORDINARIO": "ordinario"}
# tipoAlteracaoNE → Empenho.TIPO
TIPO_MAP = {"NENHUMA": "empenho", "REFORCO": "reforco", "ANULACAO": "anulacao"}


def parse_valor(v):
    if v is None:
        return Decimal("0")
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = re.sub(r"[R$\s]", "", str(v)).replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def classificador(ne, nome_tipo):
    """Extrai o nomeClassificador de um classificador da NE pelo nomeTipoClassificador."""
    for c in ne.get("classificadores") or []:
        if c.get("nomeTipoClassificador") == nome_tipo:
            return (c.get("nomeClassificador") or "").strip()
    return ""


class Command(BaseCommand):
    help = "Importa as Notas de Empenho do SIAFE-PI como linhas de Empenho."

    def add_arguments(self, parser):
        parser.add_argument("--exercicio", type=int, default=timezone.now().year)
        parser.add_argument("--ug", default="", help="Restringe a uma UG (senão todas do MPPI).")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        exercicio = opts["exercicio"]
        ugs = [opts["ug"]] if opts["ug"] else UGS_MPPI
        client = SiafeClient()

        # Índice de contratos por codigo_siafe
        idx = {
            c.codigo_siafe.strip(): c
            for c in Contrato.objects.exclude(codigo_siafe="").exclude(codigo_siafe__isnull=True)
        }
        self.stdout.write(f"{len(idx)} contrato(s) local(is) com codigo_siafe.\n")

        criados = atualizados = sem_contrato = ignoradas = 0
        liquido_por_contrato = {}  # codigo_siafe -> Decimal (net de anulações)
        agora = timezone.now()

        with transaction.atomic():
            for ug in ugs:
                self.stdout.write(f"Buscando NEs da UG {ug} — exercício {exercicio}...")
                try:
                    nes = client.nota_empenho_por_ug(exercicio, ug)
                except SiafeAPIError as exc:
                    self.stderr.write(self.style.WARNING(f"  [ERRO] UG {ug}: {exc}"))
                    continue
                self.stdout.write(f"  {len(nes)} NEs recebidas")

                for ne in nes:
                    cod_contrato = (ne.get("codContrato") or "").strip()
                    if not cod_contrato or cod_contrato in ("0", "00000000"):
                        ignoradas += 1
                        continue

                    contrato = idx.get(cod_contrato)
                    if contrato is None:
                        sem_contrato += 1
                        continue

                    numero = (ne.get("codigo") or "").strip()
                    if not numero:
                        continue

                    valor = parse_valor(ne.get("valor"))
                    tipo_alt = (ne.get("tipoAlteracaoNE") or "NENHUMA").upper()
                    tipo = TIPO_MAP.get(tipo_alt, "empenho")

                    # Agregado líquido por contrato (anulação subtrai)
                    delta = -valor if tipo == "anulacao" else valor
                    liquido_por_contrato[cod_contrato] = (
                        liquido_por_contrato.get(cod_contrato, Decimal("0")) + delta
                    )

                    data_em = ne.get("dataEmissao")
                    try:
                        data_emissao = datetime.strptime(data_em, "%Y-%m-%d").date() if data_em else None
                    except (ValueError, TypeError):
                        data_emissao = None

                    ano_m = re.match(r"(\d{4})", numero)
                    natureza_str = classificador(ne, "Natureza") or ne.get("codNatureza") or ""

                    defaults = {
                        "ano_exercicio": int(ano_m.group(1)) if ano_m else exercicio,
                        "natureza": NATUREZA_MAP.get((ne.get("modalidade") or "").upper(), "ordinario"),
                        "tipo": tipo,
                        "valor_empenhado": valor,
                        "programa_trabalho": classificador(ne, "Programa de trabalho")[:30],
                        "elemento_despesa": natureza_str[:20],
                        "fonte_recurso": (ne.get("codFonte") or classificador(ne, "Fonte"))[:10],
                        "unidade_orcamentaria": (ne.get("codigoUG") or "")[:10],
                        "cnpj_favorecido": (ne.get("cnpjCredor") or ne.get("cpfCredor") or "")[:18],
                        "nome_favorecido": (ne.get("nomeCredor") or "")[:255],
                        "data_emissao": data_emissao,
                        "descricao": (ne.get("observacao") or "").strip(),
                        "importado_siafe": True,
                        "importado_em": agora,
                    }

                    if opts["dry_run"]:
                        existe = Empenho.objects.filter(
                            contrato=contrato, numero_empenho=numero
                        ).exists()
                        if existe:
                            atualizados += 1
                        else:
                            criados += 1
                        continue

                    _, created = Empenho.objects.update_or_create(
                        contrato=contrato, numero_empenho=numero, defaults=defaults
                    )
                    if created:
                        criados += 1
                    else:
                        atualizados += 1

            # Atualiza o agregado no contrato (líquido de anulações)
            contratos_atualizados = 0
            if not opts["dry_run"]:
                for cod, total in liquido_por_contrato.items():
                    contrato = idx.get(cod)
                    if contrato:
                        contrato.valor_empenhado = total
                        contrato.ultima_atualizacao_siafe = agora
                        contrato.save(update_fields=["valor_empenhado", "ultima_atualizacao_siafe"])
                        contratos_atualizados += 1

            if opts["dry_run"]:
                transaction.set_rollback(True)

        modo = "[DRY-RUN — nada gravado] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Empenhos criados: {criados} | Atualizados: {atualizados} | "
            f"NEs sem contrato local: {sem_contrato} | NEs sem contrato (avulsas): {ignoradas}"
        ))
        if not opts["dry_run"]:
            self.stdout.write(
                f"Contratos com valor_empenhado atualizado: {len(liquido_por_contrato)}"
            )
