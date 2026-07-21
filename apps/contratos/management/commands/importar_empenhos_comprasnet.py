"""
Importa empenhos dos contratos a partir do Comprasnet Contratos
(contratos.comprasnet.gov.br/api — endpoint público /api/contrato/{id}/empenhos).

Para cada contrato da UASG na API:
1. Casa o número com o `contratos.Contrato` local (mesma normalização de
   importar_links_contratos).
2. Busca /api/contrato/{id}/empenhos e faz update_or_create de
   `contratos.Empenho` (chave: contrato + numero_empenho), preenchendo
   valores empenhado/liquidado/pago, classificação orçamentária, credor e
   datas — marcando `importado_siafe=False` (origem = Comprasnet, não SIAFE-PI).

Formato dos valores na API: string brasileira ("1.361.640,02").
O campo `credor` vem como "CNPJ - NOME"; `naturezadespesa` como "339039 - OUTROS...".

Uso:
    python manage.py importar_empenhos_comprasnet [--uasg 926092] [--dry-run]
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.contratos.models import Contrato, Empenho
from apps.srp.services.comprasnet_contratos import ComprasnetContratosClient


def normalizar_numero(texto):
    m = re.match(r"\s*0*(\d+)\s*/\s*(\d{4})", str(texto or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def brl_para_decimal(valor):
    if valor in (None, ""):
        return Decimal("0.00")
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))
    s = str(valor).strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0.00")


def separar_credor(credor):
    """'09.439.320/0001-17 - GLOBAL SERVICOS LTDA' -> (cnpj, nome)."""
    if not credor:
        return "", ""
    partes = str(credor).split(" - ", 1)
    if len(partes) == 2:
        return partes[0].strip(), partes[1].strip()
    return "", str(credor).strip()


def ano_do_empenho(numero):
    """'2019NE800022' -> 2019."""
    m = re.match(r"(\d{4})", str(numero or ""))
    return int(m.group(1)) if m else timezone.now().year


def status_liquidacao(empenhado, liquidado, pago):
    if pago and pago >= empenhado and empenhado > 0:
        return "pago"
    if liquidado and liquidado >= empenhado and empenhado > 0:
        return "liquidado"
    if liquidado and liquidado > 0:
        return "parcialmente"
    return "nao_liquidado"


class Command(BaseCommand):
    help = "Importa empenhos dos contratos via Comprasnet Contratos."

    def add_arguments(self, parser):
        parser.add_argument("--uasg", default="926092")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        client = ComprasnetContratosClient()
        contratos_api = client.get_contratos_ug(opts["uasg"], ativos=True)
        contratos_api += client.get_contratos_ug(opts["uasg"], ativos=False)
        self.stdout.write(
            f"Comprasnet retornou {len(contratos_api)} contrato(s) da UASG {opts['uasg']}.\n"
        )

        idx = {}
        for c in Contrato.objects.all():
            chave = normalizar_numero(c.numero_contrato)
            if chave:
                idx.setdefault(chave, []).append(c)

        criados = atualizados = sem_local = sem_empenho = 0
        agora = timezone.now()

        with transaction.atomic():
            for capi in contratos_api:
                chave = normalizar_numero(capi.get("numero", ""))
                cid = capi.get("id")
                if not chave or not cid:
                    continue
                locais = idx.get(chave, [])
                if len(locais) != 1:
                    if not locais:
                        sem_local += 1
                    continue
                contrato = locais[0]

                try:
                    empenhos = client.get_contrato_empenhos(cid)
                except Exception as e:  # noqa: BLE001
                    self.stderr.write(f"  empenhos indisponíveis p/ {capi.get('numero')}: {e}")
                    continue

                if not empenhos:
                    sem_empenho += 1
                    continue

                for e in empenhos:
                    numero = e.get("numero") or e.get("numero_empenho") or ""
                    if not numero:
                        continue
                    empenhado = brl_para_decimal(e.get("empenhado") or e.get("valor_empenhado"))
                    liquidado = brl_para_decimal(e.get("liquidado") or e.get("valor_liquidado"))
                    pago = brl_para_decimal(e.get("pago") or e.get("valor_pago"))
                    cnpj, nome = separar_credor(e.get("credor"))
                    nat = e.get("naturezadespesa") or ""
                    elemento = nat.split(" - ")[0].strip() if nat else ""
                    data_em = e.get("data_emissao")
                    try:
                        data_emissao = datetime.strptime(data_em, "%Y-%m-%d").date() if data_em else None
                    except (ValueError, TypeError):
                        data_emissao = None

                    defaults = {
                        "ano_exercicio": ano_do_empenho(numero),
                        "valor_empenhado": empenhado,
                        "valor_liquidado": liquidado,
                        "valor_pago": pago,
                        "programa_trabalho": (e.get("programa_trabalho") or "")[:30],
                        "elemento_despesa": elemento[:20],
                        "fonte_recurso": (e.get("fonte_recurso") or "")[:10],
                        "cnpj_favorecido": cnpj[:18],
                        "nome_favorecido": nome[:255],
                        "data_emissao": data_emissao,
                        "descricao": (e.get("informacao_complementar") or nat or "")[:500],
                        "status_liquidacao": status_liquidacao(empenhado, liquidado, pago),
                        "importado_siafe": False,
                        "importado_em": agora,
                    }

                    if opts["dry_run"]:
                        existe = Empenho.objects.filter(
                            contrato=contrato, numero_empenho=numero
                        ).exists()
                        criados += 0 if existe else 1
                        atualizados += 1 if existe else 0
                        self.stdout.write(
                            f"  [{'UPD' if existe else 'NEW'}] {contrato.numero_contrato} / "
                            f"{numero} R$ {empenhado}"
                        )
                        continue

                    _, created = Empenho.objects.update_or_create(
                        contrato=contrato, numero_empenho=numero, defaults=defaults
                    )
                    if created:
                        criados += 1
                    else:
                        atualizados += 1
                    self.stdout.write(
                        f"  [{'NEW' if created else 'UPD'}] {contrato.numero_contrato} / "
                        f"{numero} R$ {empenhado}"
                    )

            if opts["dry_run"]:
                transaction.set_rollback(True)

        modo = "[DRY-RUN — nada gravado] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Empenhos criados: {criados} | Atualizados: {atualizados} | "
            f"Contratos sem empenho na API: {sem_empenho} | Sem contrato local: {sem_local}"
        ))
        if criados == 0 and atualizados == 0:
            self.stdout.write(
                "\nNenhum empenho retornado pela API para os contratos desta UASG. "
                "O MPPI executa empenhos no SIAFE-PI (estadual), que não alimenta o "
                "Comprasnet Contratos (federal) — por isso o endpoint volta vazio. "
                "Para empenhos reais, usar a importação SIAFE (EmpenhosSIAFEView) ou "
                "credenciais válidas para os endpoints v1 autenticados por UG."
            )
