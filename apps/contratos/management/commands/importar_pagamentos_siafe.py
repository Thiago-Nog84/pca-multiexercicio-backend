"""
Management command: importar_pagamentos_siafe
=============================================
Importa as Ordens Bancárias (OB) do SIAFE-PI — 3º e último estágio da despesa
(pagamento efetivo) — e preenche em cada `Empenho` local o `valor_pago`, a
`data_pagamento` e promove o `status_liquidacao` a "pago" quando quitado.

Fonte (confirmado ao vivo 2026-07-30): `SiafeClient.ob_orcamentaria_por_credor`
(a OB só é consultável POR CREDOR + período — não há endpoint por UG). Cada OB
traz a ligação completa:
  - `codigoNE` + `exercicioNE` + `codigoUGEmpenho` → o empenho pago
  - `codigoNL` → a liquidação paga
  - `valor` → valor pago
  - `dataPagamento` / `dataContabilizacao`
  - `dataCancelamento` (quando preenchido, OB cancelada → ignorada)

Estratégia (para não varrer o estado inteiro):
  1. Busca os NEs das 3 UGs do MPPI e coleta os `codigoCredor` dos empenhos
     CONTRATUAIS (codContrato ≠ 00000000) — só os fornecedores dos nossos
     contratos.
  2. Para cada credor, busca as OBs no período e agrega o valor pago por
     (codigoNE, codigoUGEmpenho), mantendo só as UGs do MPPI.
  3. Casa com o Empenho local por (numero_empenho, unidade_orcamentaria=UG) —
     mesma chave robusta da liquidação (nº de NE se repete entre UGs).

⚠️ Muitas chamadas ao SIAFE (uma por credor) numa API instável — o comando
tem retry e degrada com aviso; rode preferencialmente agendado/fora do horário
de pico. Pagamento é o 3º estágio: sempre ≤ liquidado ≤ empenhado.

Uso:
    python manage.py importar_pagamentos_siafe --dry-run
    python manage.py importar_pagamentos_siafe --exercicios 2025 2026
    python manage.py importar_pagamentos_siafe
"""

import time
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.contratos.models_empenho import Empenho
from apps.siafe.client import SiafeClient

UGS_MPPI = ["250101", "250102", "250104"]


def _dec(v):
    try:
        return Decimal(str(v or 0))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _data(v):
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Importa as Ordens Bancárias do SIAFE e preenche valor_pago/status=pago dos Empenhos."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--exercicios", type=int, nargs="+", default=None,
                            help="Exercícios das OBs (padrão: ano atual e anterior).")
        parser.add_argument("--max-credores", type=int, default=None,
                            help="Limita o nº de credores consultados (para teste rápido).")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        if dry:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nada será gravado ***\n"))

        ano = timezone.now().year
        exercicios = opts["exercicios"] or [ano - 1, ano]
        client = SiafeClient()

        # ── 1. Coleta os credores dos empenhos CONTRATUAIS ──
        credores = set()
        for exe in exercicios:
            for ug in UGS_MPPI:
                nes = self._fetch(client.nota_empenho_por_ug, exe, ug)
                for ne in nes:
                    cc = (str(ne.get("codContrato") or "")).strip()
                    cred = (str(ne.get("codigoCredor") or "")).strip()
                    if cred and cc and cc != "00000000":
                        credores.add(cred)
        credores = sorted(credores)
        if opts["max_credores"]:
            credores = credores[: opts["max_credores"]]
        self.stdout.write(f"Credores contratuais a consultar: {len(credores)}")

        # ── 2. Busca OBs por credor e agrega pago por (codigoNE, UG) ──
        pago = defaultdict(Decimal)     # (codigoNE, ug) -> soma pago
        data_pg = {}                    # (codigoNE, ug) -> maior data
        n_obs = n_canceladas = 0
        ugs_set = set(UGS_MPPI)

        for i, cred in enumerate(credores, 1):
            for exe in exercicios:
                obs = self._fetch(
                    client.ob_orcamentaria_por_credor, exe, cred,
                    f"{exe}-01-01", f"{exe}-12-31",
                )
                for ob in obs:
                    if ob.get("dataCancelamento"):
                        n_canceladas += 1
                        continue
                    ne = (str(ob.get("codigoNE") or "")).strip()
                    ug = (str(ob.get("codigoUGEmpenho") or "")).strip()
                    if not ne or ug not in ugs_set:
                        continue
                    n_obs += 1
                    pago[(ne, ug)] += _dec(ob.get("valor"))
                    d = _data(ob.get("dataPagamento") or ob.get("dataContabilizacao"))
                    if d and ((ne, ug) not in data_pg or d > data_pg[(ne, ug)]):
                        data_pg[(ne, ug)] = d
            if i % 20 == 0:
                self.stdout.write(f"  … {i}/{len(credores)} credores processados")

        self.stdout.write(self.style.SUCCESS(
            f"\n{n_obs} OB(s) de contrato agregadas ({n_canceladas} canceladas ignoradas); "
            f"{len(pago)} par(es) empenho+UG com pagamento."
        ))

        # ── 3. Reset + aplica em cada Empenho local ──
        resumo = {"atualizados": 0, "promovidos_pago": 0, "sem_match": 0}
        aplicados = set()

        with transaction.atomic():
            if not dry:
                Empenho.objects.exclude(valor_pago=0).update(
                    valor_pago=Decimal("0"), data_pagamento=None,
                )
            for emp in Empenho.objects.select_related("contrato"):
                ug = (emp.unidade_orcamentaria or "").strip()
                if not ug:
                    continue
                chave = (emp.numero_empenho, ug)
                total = pago.get(chave)
                if total is None:
                    continue
                aplicados.add(chave)
                self._aplicar(emp, total, data_pg.get(chave), dry, resumo)

            if dry:
                transaction.set_rollback(True)

        resumo["sem_match"] = len(pago) - len(aplicados)

        # ── 4. Resumo ──
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(
            f"{'DRY-RUN — ' if dry else ''}Concluído.\n"
            f"  Empenhos com pagamento atualizado: {resumo['atualizados']}\n"
            f"  Promovidos a 'pago' (quitados): {resumo['promovidos_pago']}\n"
            f"  Pagamentos SIAFE sem empenho local correspondente: {resumo['sem_match']}"
        ))

    # ------------------------------------------------------------------
    def _aplicar(self, emp, valor_pago, data, dry, resumo):
        valor_pago = valor_pago.quantize(Decimal("0.01"))
        if valor_pago <= 0:
            return
        promove = valor_pago >= (emp.valor_empenhado or Decimal("0"))
        novo_status = "pago" if promove else emp.status_liquidacao
        mudou = (
            emp.valor_pago != valor_pago
            or (data and emp.data_pagamento != data)
            or emp.status_liquidacao != novo_status
        )
        if not mudou:
            return
        resumo["atualizados"] += 1
        if promove and emp.status_liquidacao != "pago":
            resumo["promovidos_pago"] += 1
        if not dry:
            emp.valor_pago = valor_pago
            if data:
                emp.data_pagamento = data
            emp.status_liquidacao = novo_status
            emp.save(update_fields=["valor_pago", "data_pagamento", "status_liquidacao"])

    def _fetch(self, fn, *a):
        for tent in range(3):
            try:
                return fn(*a) or []
            except Exception as exc:  # noqa: BLE001
                if tent == 2:
                    self.stdout.write(self.style.WARNING(f"  [SIAFE indisponível] {fn.__name__}{a}: {exc}"))
                    return []
                time.sleep(3)
        return []
