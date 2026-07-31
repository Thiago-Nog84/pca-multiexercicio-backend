"""
Management command: importar_liquidacoes_siafe
==============================================
Importa as Notas de Liquidação (NL) do SIAFE-PI e preenche, em cada
`Empenho` local, o `valor_liquidado`, a `data_liquidacao` e o
`status_liquidacao`. É o 2º estágio da despesa (reconhecimento da obrigação
após entrega) — o dado que faltava para medir CONSUMO real de contrato e
detectar exaurimento / necessidade de empenho complementar.

Fonte (confirmado ao vivo 2026-07-30): `SiafeClient.notas_liquidacao_por_ug`.
Cada NL traz:
  - `codigo`                  → nº da NL (ex: 2026NL00072)
  - `valor`                   → valor liquidado
  - `codigoEmpenhoVinculado`  → o EMPENHO liquidado, mesmo formato do nosso
                                `Empenho.numero_empenho` (ex: 2026NE00469)
  - `codContrato`             → código SIAFE do contrato (desambigua colisão
                                de nº de NE entre UGs)
  - `dataContabilizacao`      → data
  - `dataCancelamento`        → quando preenchido, a NL foi cancelada (ignorada)

A liquidação de UM empenho pode ser feita por VÁRIAS NLs (parcelas) e ao
longo de mais de um exercício (restos a pagar) — somamos as NLs de todos os
exercícios pedidos por `codigoEmpenhoVinculado`, mas DEDUPLICANDO por nº de NL:
a mesma NL de um exercício reaparece no listing do exercício seguinte (restos a
pagar) e, sem dedup, seria contada em dobro (inflava o liquidado acima do
empenhado — achado 2026-07-31, 64/2022/PGJ).

⚠️ Colisão de nº de NE entre UGs (ver [[project-pca-empenho-fonte-confiavel]]):
quando mais de um `Empenho` local tem o mesmo `numero_empenho`, desambigua
pelo `codContrato` da NL vs. `contrato.codigo_siafe`; se não der, pula e avisa.

Pagamento (valor_pago / status "pago") NÃO é tratado aqui — vem das Ordens
Bancárias (`ob_orcamentaria_por_credor`), por credor+período; fica p/ etapa
posterior.

Uso:
    python manage.py importar_liquidacoes_siafe --dry-run
    python manage.py importar_liquidacoes_siafe --exercicios 2025 2026
    python manage.py importar_liquidacoes_siafe
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
    help = "Importa as Notas de Liquidação do SIAFE e preenche valor_liquidado/status dos Empenhos."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--exercicios", type=int, nargs="+", default=None,
            help="Exercícios das NLs a buscar (padrão: ano atual e anterior).",
        )
        parser.add_argument("--ug", default="", help="Restringe a uma UG (senão as 3 do MPPI).")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        if dry:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nada será gravado ***\n"))

        ano = timezone.now().year
        exercicios = opts["exercicios"] or [ano - 1, ano]
        ugs = [opts["ug"]] if opts["ug"] else UGS_MPPI

        client = SiafeClient()

        # ── 1. Coleta as NLs e agrega por (empenho, UG) ──
        # ⚠️ nº de NE se repete entre UGs — agregar só pelo número mistura
        # empenhos de contratos diferentes (bug real: 38/2026 recebeu 13 mi).
        # A NL é buscada POR UG, e o Empenho local guarda a UG em
        # `unidade_orcamentaria` (250101/250102/250104) — então a chave
        # correta e sem ambiguidade é (codigoEmpenhoVinculado, UG).
        # (codContrato da NL vem quase sempre nulo, não serve para desambiguar.)
        # ⚠️ DEDUP por nº de NL: uma NL de um exercício REAPARECE no listing do
        # exercício seguinte como restos a pagar (ex.: 2025NL02300 aparece na
        # consulta de 2025 e na de 2026). Somar as duas dobrava o liquidado —
        # achado 2026-07-31 no 64/2022/PGJ (NE 2025NE01040/01293 apareciam com
        # liquidado > empenhado). Guardamos {codigo_nl: valor} por (empenho,UG)
        # e somamos só NLs distintas.
        liq_nl = defaultdict(dict)     # (numero_empenho, ug) -> {codigo_nl: valor}
        data_liq = {}                  # (numero_empenho, ug) -> maior data
        n_nls = n_canceladas = n_dup = 0

        for exe in exercicios:
            for ug in ugs:
                nls = self._fetch(client, exe, ug)
                self.stdout.write(f"  {exe}/UG {ug}: {len(nls)} NL(s)")
                for nl in nls:
                    if nl.get("dataCancelamento"):
                        n_canceladas += 1
                        continue
                    ne = (nl.get("codigoEmpenhoVinculado") or "").strip()
                    if not ne:
                        continue
                    cod = (str(nl.get("codigo") or "")).strip() or f"__idx{n_nls}_{n_dup}"
                    slot = liq_nl[(ne, ug)]
                    if cod in slot:          # mesma NL já contada (restos a pagar)
                        n_dup += 1
                        continue
                    slot[cod] = _dec(nl.get("valor"))
                    n_nls += 1
                    d = _data(nl.get("dataContabilizacao") or nl.get("dataEmissao"))
                    if d and ((ne, ug) not in data_liq or d > data_liq[(ne, ug)]):
                        data_liq[(ne, ug)] = d

        liq = {k: sum(v.values()) for k, v in liq_nl.items()}

        self.stdout.write(self.style.SUCCESS(
            f"\n{n_nls} NL(s) únicas agregadas ({n_canceladas} canceladas + "
            f"{n_dup} duplicadas entre exercícios ignoradas); "
            f"{len(liq)} par(es) empenho+UG liquidados no SIAFE."
        ))

        # ── 2. Reset + aplica em cada Empenho local (casa por nº + UG) ──
        resumo = {"atualizados": 0, "sem_ug": 0, "sem_match": 0}
        aplicados_chaves = set()

        with transaction.atomic():
            # zera antes para não deixar valor antigo/errado (idempotente e seguro)
            if not dry:
                Empenho.objects.exclude(valor_liquidado=0).update(
                    valor_liquidado=Decimal("0"), status_liquidacao="nao_liquidado",
                    data_liquidacao=None,
                )
            for emp in Empenho.objects.select_related("contrato"):
                ug = (emp.unidade_orcamentaria or "").strip()
                if not ug:
                    resumo["sem_ug"] += 1
                    continue
                chave = (emp.numero_empenho, ug)
                total = liq.get(chave)
                if total is None:
                    continue
                aplicados_chaves.add(chave)
                self._aplicar(emp, total, data_liq.get(chave), dry, resumo)

            if dry:
                transaction.set_rollback(True)

        resumo["sem_match"] = len(liq) - len(aplicados_chaves)

        # ── 3. Resumo ──
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(
            f"{'DRY-RUN — ' if dry else ''}Concluído.\n"
            f"  Empenhos com liquidação atualizada: {resumo['atualizados']}\n"
            f"  Empenhos sem UG (não casam): {resumo['sem_ug']}\n"
            f"  Liquidações SIAFE sem empenho local (folha/diárias/outras UGs): {resumo['sem_match']}"
        ))

    # ------------------------------------------------------------------
    def _aplicar(self, emp, liquidado, data, dry, resumo):
        liquidado = liquidado.quantize(Decimal("0.01"))
        if liquidado <= 0:
            return
        if liquidado >= (emp.valor_empenhado or Decimal("0")):
            status = "liquidado"
        else:
            status = "parcialmente"
        mudou = (
            emp.valor_liquidado != liquidado
            or emp.status_liquidacao != status
            or (data and emp.data_liquidacao != data)
        )
        if not mudou:
            return
        resumo["atualizados"] += 1
        if not dry:
            emp.valor_liquidado = liquidado
            emp.status_liquidacao = status
            if data:
                emp.data_liquidacao = data
            emp.save(update_fields=["valor_liquidado", "status_liquidacao", "data_liquidacao"])

    def _fetch(self, client, exercicio, ug):
        for tent in range(3):
            try:
                return client.notas_liquidacao_por_ug(exercicio, ug)
            except Exception as exc:  # noqa: BLE001
                if tent == 2:
                    self.stdout.write(self.style.WARNING(f"  [SIAFE indisponível] {exercicio}/{ug}: {exc}"))
                    return []
                time.sleep(3)
        return []
