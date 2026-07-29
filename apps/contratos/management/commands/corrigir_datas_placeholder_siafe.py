"""
Management command: corrigir_datas_placeholder_siafe
=========================================================
Versão em lote do resincronizar_contrato_siafe: percorre todos os
Contrato com codigo_siafe preenchido cuja data_assinatura ou
data_inicio_vigencia caiu no fallback 01/01 (usado por
importar_contratos_siafe_api.py quando a API não trazia a data) e consulta
o SIAFE de novo pra cada um, corrigindo datas/valor/SEI.

IMPORTANTE — usa sempre o dado BRUTO devolvido pelo SIAFE (dataCelebracao,
dataInicioVigencia, dataFimVigencia/dataFimVigenciaTotal), nunca o valor já
com fallback sintético que _map_contrato_siafe aplica (date(exercicio,1,1))
quando a API não traz a data. Se usássemos o mapeado direto, um contrato
com data REAL já cadastrada (ex: data_assinatura=2025-09-11) mas
data_inicio_vigencia=01/01 correria o risco de ter a data_assinatura
substituída por um 01/01 fabricado, caso o SIAFE não devolvesse
dataCelebracao pra aquele código — achado no teste com --limite 107
(2026-07-29): pk=169 e pk=176 fariam exatamente isso.

Regra de segurança: nunca substitui uma data JÁ real (não é 01/01) por uma
nova data que também caia em 01/01 — isso é sinal de dado ausente/errado no
SIAFE pra aquele campo, não uma correção. Fica na lista de revisão manual.

Valor: mesma tolerância do resincronizar_contrato_siafe — diferença grande
(> R$50) não é aplicada sozinha (achado: pk=106 caiu de R$53.096 pra
R$5.000 — parece parcela, não valor total).

Uso:
  python manage.py corrigir_datas_placeholder_siafe --dry-run
  python manage.py corrigir_datas_placeholder_siafe
  python manage.py corrigir_datas_placeholder_siafe --limite 20   # testa com poucos primeiro
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

import requests

from apps.contratos.management.commands.importar_contratos_siafe_api import _parse_date
from apps.contratos.models import Contrato
from apps.siafe.client import SiafeClient, SiafeAPIError

TOLERANCIA_VALOR_AUTOMATICA = Decimal("50.00")


def _eh_placeholder(d):
    return d is not None and d.month == 1 and d.day == 1


def _get_raw(data: dict, *keys):
    for k in keys:
        v = data.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


class Command(BaseCommand):
    help = "Corrige em lote datas/valor/SEI placeholder consultando o SIAFE de novo (por codigo_siafe)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limite", type=int, default=None, help="Processa só os N primeiros (teste)")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limite = options["limite"]

        candidatos = Contrato.objects.exclude(codigo_siafe="").filter(
            data_assinatura__month=1, data_assinatura__day=1
        ) | Contrato.objects.exclude(codigo_siafe="").filter(
            data_inicio_vigencia__month=1, data_inicio_vigencia__day=1
        )
        candidatos = candidatos.distinct().order_by("pk")
        if limite:
            candidatos = candidatos[:limite]

        total = candidatos.count() if not limite else len(candidatos)
        self.stdout.write(f"{total} contrato(s) candidato(s) (codigo_siafe preenchido + data 01/01)\n")
        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nenhuma alteração será salva ***\n"))

        client = SiafeClient()
        corrigidos = sem_mudanca = nao_encontrados = erros = 0
        valores_para_revisao = []
        datas_para_revisao = []

        for c in candidatos:
            exercicio = c.data_assinatura.year if c.data_assinatura else c.exercicio
            try:
                data = client.contrato(exercicio, c.codigo_siafe)
            except SiafeAPIError as exc:
                self.stdout.write(self.style.WARNING(
                    f"  [{c.pk}] {c.numero_contrato}: ERRO API ({exc}) — pulando"
                ))
                if "não foi localizado" in str(exc) or "nao foi localizado" in str(exc).lower():
                    nao_encontrados += 1
                else:
                    erros += 1
                continue
            except requests.exceptions.RequestException as exc:
                self.stdout.write(self.style.WARNING(
                    f"  [{c.pk}] {c.numero_contrato}: ERRO DE REDE ({exc.__class__.__name__}) — pulando"
                ))
                erros += 1
                continue

            if not isinstance(data, dict) or not data:
                self.stdout.write(f"  [{c.pk}] {c.numero_contrato}: resposta vazia — pulando")
                nao_encontrados += 1
                continue

            numero_sei_siafe = _get_raw(data, "numProcesso")
            raw_assinatura = _parse_date(_get_raw(data, "dataCelebracao", "dataAssinatura"))
            raw_inicio = _parse_date(_get_raw(data, "dataInicioVigencia"))
            raw_fim = _parse_date(_get_raw(data, "dataFimVigenciaTotal", "dataFimVigencia"))
            valor_siafe = None
            valor_raw = _get_raw(data, "valorTotal", "valor")
            if valor_raw is not None:
                try:
                    valor_siafe = Decimal(str(valor_raw))
                except Exception:
                    valor_siafe = None

            # Valor suspeito -> NÃO aplica NADA nesse registro (nem as
            # datas), só reporta. Achado (2026-07-29): pk=176 tinha o valor
            # sinalizado mas as datas foram aplicadas mesmo assim, deixando
            # o registro com data nova e valor velho — inconsistente. Um
            # valor muito divergente é sinal de que o codigo_siafe pode nem
            # corresponder de verdade a este contrato (mesmo padrão do
            # Grupo 1 da auditoria [duplicados], onde campos vieram
            # trocados entre dois contratos da mesma empresa).
            valor_suspeito = False
            if valor_siafe is not None and c.valor_inicial != valor_siafe:
                diff = abs((c.valor_inicial or Decimal("0")) - valor_siafe)
                if diff > TOLERANCIA_VALOR_AUTOMATICA:
                    valor_suspeito = True
                    valores_para_revisao.append((c.pk, c.numero_contrato, c.valor_inicial, valor_siafe))

            if valor_suspeito:
                continue

            campos = {}

            if valor_siafe is not None and c.valor_inicial != valor_siafe:
                campos["valor_inicial"] = valor_siafe
                if c.valor_atual == c.valor_inicial:
                    campos["valor_atual"] = valor_siafe
                if c.saldo_disponivel == c.valor_inicial:
                    campos["saldo_disponivel"] = valor_siafe

            for campo, atual, novo in (
                ("data_assinatura", c.data_assinatura, raw_assinatura),
                ("data_inicio_vigencia", c.data_inicio_vigencia, raw_inicio),
                ("data_fim_vigencia", c.data_fim_vigencia, raw_fim),
            ):
                if novo is None or novo == atual:
                    continue
                if not _eh_placeholder(atual) and _eh_placeholder(novo):
                    # data real virando 01/01 — SIAFE não trouxe o campo de
                    # verdade pra esse código, não aplica sozinho
                    datas_para_revisao.append((c.pk, c.numero_contrato, campo, atual, novo))
                    continue
                campos[campo] = novo

            if numero_sei_siafe and not c.numero_sei and c.numero_sei != numero_sei_siafe:
                campos["numero_sei"] = numero_sei_siafe

            if not campos:
                sem_mudanca += 1
                continue

            resumo = ", ".join(f"{k}: {getattr(c, k)!r}->{v!r}" for k, v in campos.items())
            self.stdout.write(f"  [{c.pk}] {c.numero_contrato}: {resumo}")

            if not dry_run:
                for k, v in campos.items():
                    setattr(c, k, v)
                c.save(update_fields=list(campos.keys()))
            corrigidos += 1

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS(
            f"{corrigidos} corrigido(s), {sem_mudanca} já ok, "
            f"{nao_encontrados} não encontrado(s) no SIAFE, {erros} erro(s) de API"
        ))

        if valores_para_revisao:
            self.stdout.write(self.style.WARNING(
                f"\n⚠ {len(valores_para_revisao)} contrato(s) com diferença de VALOR "
                f"maior que R$ {TOLERANCIA_VALOR_AUTOMATICA} — NÃO aplicada, revisar manualmente:"
            ))
            for pk, numero, valor_banco, valor_siafe in valores_para_revisao:
                self.stdout.write(
                    f"  [{pk}] {numero}: banco=R$ {valor_banco:,.2f} | SIAFE=R$ {valor_siafe:,.2f}"
                )

        if datas_para_revisao:
            self.stdout.write(self.style.WARNING(
                f"\n⚠ {len(datas_para_revisao)} campo(s) de DATA onde o SIAFE não trouxe valor "
                "e a data atual já é real — NÃO aplicada, revisar manualmente:"
            ))
            for pk, numero, campo, atual, novo in datas_para_revisao:
                self.stdout.write(f"  [{pk}] {numero}: {campo} atual={atual} (SIAFE devolveria {novo}, ignorado)")
