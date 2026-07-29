"""
Management command: conciliar_tcepi
====================================================
SOMENTE LEITURA. Cruza dados locais (Empenho/Contrato) contra o Portal da
Cidadania do TCE-PI — a fonte de dados do órgão de CONTROLE EXTERNO,
independente tanto do SIAFE (execução orçamentária do Executivo) quanto do
PNCP/dadosabertos (divulgação de compras). Serve como uma TERCEIRA fonte
para validar valores.

Para cada órgão do MPPI (pgj/fmmp/fepdc), busca a lista completa de
credores do TCE no exercício (CNPJ + empenhado/liquidado/pago) e compara
contra a soma local de `Empenho` (agrupado por `cnpj_favorecido`) do mesmo
exercício e unidade orçamentária. Classifica cada CNPJ local em:
  - CONFERE: soma local bate com o TCE dentro da tolerância.
  - DIVERGE: soma local e TCE existem mas diferem além da tolerância.
  - NAO ENCONTRADO NO TCE: CNPJ local não aparece na lista de credores do
    TCE para esse órgão/exercício (pode ser erro de código de UG, CNPJ
    digitado errado localmente, ou despesa ainda não processada pelo TCE).

Também lista, de forma informativa (sem comparar contra nada local ainda),
as licitações do órgão registradas no TCE para o exercício — útil para
detectar licitações que existem no TCE mas ainda não têm ProcessoLicitatorio
cadastrado localmente.

LIMITAÇÃO ESTRUTURAL CONHECIDA (não é bug, não tentar "corrigir"):
o TCE soma TODO o empenhado do credor no órgão, inclusive despesas SEM
instrumento contratual (compra direta / dispensa). O modelo local `Empenho`
exige FK obrigatória para `Contrato`, então NE sem contrato não tem como ser
registrada aqui — no SIAFE ela vem com `codContrato='00000000'` e é contada
como "avulsa" pelo `importar_empenhos_siafe`. Resultado: para credores que
tiveram compra direta no exercício, o total local fica LEGITIMAMENTE abaixo
do TCE, e essa diferença nunca vai fechar.
  Caso real (2026-07-29): ZENITE INFORMACAO E CONSULTORIA, exercício 2026,
  PGJ — diferença de R$5.568,00 = NE 2026NE00818, confirmada pelo Thiago
  como contratação sem contrato. Nada a corrigir.
Antes de investigar um DIVERGE onde local < TCE, rodar
`investigar_ne_faltante --cnpj <cnpj> --exercicio <ano>`: se a NE que falta
tiver `codContrato='00000000'`, é este caso e pode ser encerrado.

Nunca adivinha nem corrige nada — só reporta para revisão manual, mesmo
padrão dos outros comandos de auditoria desta sessão (consultar_contrato_siafe,
investigar_fracao_pendente etc).

Uso:
  python manage.py conciliar_tcepi --exercicio 2026 --orgao pgj fmmp fepdc --saida saida.txt
  python manage.py conciliar_tcepi --exercicio 2026 --orgao pgj --tolerancia 5 --pular-licitacoes
"""

import re
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.contratos.models_empenho import Empenho
from apps.tcepi.client import CODIGOS_UG_MPPI, TcePiAPIError, TcePiClient


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


class Command(BaseCommand):
    help = "Concilia Empenho/Contrato local contra credores e licitações do Portal da Cidadania (TCE-PI) — somente leitura"

    def add_arguments(self, parser):
        parser.add_argument("--exercicio", type=int, default=date.today().year)
        parser.add_argument(
            "--orgao", type=str, nargs="+", default=["pgj", "fmmp", "fepdc"],
            choices=["pgj", "fmmp", "fepdc"],
        )
        parser.add_argument(
            "--tolerancia", type=str, default="1.00",
            help="Tolerância em R$ para considerar 'CONFERE' (padrão: 1.00)",
        )
        parser.add_argument("--pular-licitacoes", action="store_true", help="Não busca licitações (só o cruzamento de credores)")
        parser.add_argument("--saida", type=str, default=None)

    def handle(self, *args, **options):
        arquivo_saida = None
        if options.get("saida"):
            arquivo_saida = open(options["saida"], "w", encoding="utf-8")
            escrever_original = self.stdout.write

            def escrever_e_gravar(msg="", *a, **kw):
                escrever_original(msg, *a, **kw)
                arquivo_saida.write(str(msg) + "\n")

            self.stdout.write = escrever_e_gravar

        exercicio = options["exercicio"]
        tolerancia = Decimal(options["tolerancia"])
        client = TcePiClient()

        totais_gerais = {"confere": 0, "diverge": 0, "nao_encontrado": 0}

        for orgao_key in options["orgao"]:
            codigo_ug = CODIGOS_UG_MPPI[orgao_key]
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n=== {orgao_key.upper()} (UG {codigo_ug}) — exercício {exercicio} ==="
            ))

            # --------------------------------------------------------
            # 1. Cruzamento de credores (Empenho local x TCE)
            # --------------------------------------------------------
            try:
                credores_tce = client.credores_orgao_lista_completa(codigo_ug, exercicio)
            except TcePiAPIError as exc:
                self.stdout.write(self.style.ERROR(f"  Erro ao consultar credores no TCE: {exc}"))
                continue

            mapa_tce = {}
            for c in credores_tce:
                digitos = _digitos(c.get("documento"))
                if not digitos:
                    continue
                mapa_tce[digitos] = c

            self.stdout.write(f"  {len(mapa_tce)} credores (pessoa jurídica/física) no TCE para este órgão/exercício.")

            locais = (
                Empenho.objects.filter(
                    ano_exercicio=exercicio,
                    contrato__unidade_orcamentaria=orgao_key,
                )
                .exclude(cnpj_favorecido="")
                .values("cnpj_favorecido")
            )
            cnpjs_locais = sorted({_digitos(row["cnpj_favorecido"]) for row in locais if _digitos(row["cnpj_favorecido"])})

            if not cnpjs_locais:
                self.stdout.write(self.style.WARNING(
                    "  Nenhum Empenho local com cnpj_favorecido preenchido para este órgão/exercício — nada para cruzar."
                ))
                continue

            for cnpj in cnpjs_locais:
                agregados_local = Empenho.objects.filter(
                    ano_exercicio=exercicio,
                    contrato__unidade_orcamentaria=orgao_key,
                    cnpj_favorecido__icontains=cnpj[-8:],
                )
                # NEs do tipo "anulacao" reduzem o valor empenhado — somar como
                # positivo dobra a divergência ao invés de zerar a anulação
                # (achado real: contrato 29/2026/PGJ, NE 2026NE00738 anulacao
                # R$2.504.625,82 sobre a NE 2026NE00434 R$3.572.724,80 — líquido
                # R$1.068.098,98, que bate exatamente com o TCE).
                empenhado_local = sum(
                    ((-e.valor_empenhado if e.tipo == "anulacao" else e.valor_empenhado) for e in agregados_local),
                    Decimal("0"),
                )
                liquidado_local = sum((e.valor_liquidado for e in agregados_local), Decimal("0"))
                nome_local = next(iter(agregados_local.values_list("nome_favorecido", flat=True)), "")

                credor_tce = mapa_tce.get(cnpj)
                if not credor_tce:
                    totais_gerais["nao_encontrado"] += 1
                    self.stdout.write(self.style.WARNING(
                        f"  [NAO ENCONTRADO NO TCE] {cnpj} ({nome_local or '—'}): "
                        f"local empenhado=R$ {empenhado_local:,.2f} — sem correspondência nos credores do TCE."
                    ))
                    continue

                empenhado_tce = Decimal(str(credor_tce.get("empenhado", 0) or 0))
                liquidado_tce = Decimal(str(credor_tce.get("liquidado", 0) or 0))
                diff_empenhado = abs(empenhado_local - empenhado_tce)

                if diff_empenhado <= tolerancia:
                    totais_gerais["confere"] += 1
                else:
                    totais_gerais["diverge"] += 1
                    self.stdout.write(self.style.ERROR(
                        f"  [DIVERGE] {cnpj} ({credor_tce.get('nome') or nome_local}): "
                        f"local empenhado=R$ {empenhado_local:,.2f} | TCE empenhado=R$ {empenhado_tce:,.2f} "
                        f"| diferença=R$ {diff_empenhado:,.2f} "
                        f"(liquidado local=R$ {liquidado_local:,.2f} | TCE=R$ {liquidado_tce:,.2f})"
                    ))
                    if empenhado_local < empenhado_tce:
                        self.stdout.write(
                            f"      local < TCE: pode ser NE sem contrato (compra direta), que o modelo "
                            f"local não registra — checar com: python manage.py investigar_ne_faltante "
                            f"--cnpj {cnpj} --exercicio {exercicio}"
                        )

            # --------------------------------------------------------
            # 2. Despesas por elemento — contexto informativo (não compara)
            # --------------------------------------------------------
            try:
                despesas = client.despesas_orgao_por_elemento(codigo_ug, exercicio)
                relevantes = [
                    d for d in despesas
                    if d.get("elemento") and any(
                        termo in d["elemento"] for termo in
                        ("Material de Consumo", "Serviços de Terceiros", "Locação", "Obras", "Equipamentos")
                    )
                ]
                if relevantes:
                    self.stdout.write("  Despesas TCE (elementos relacionados a compras/contratos, informativo):")
                    for d in sorted(relevantes, key=lambda x: -x.get("empenhada", 0)):
                        self.stdout.write(
                            f"    {d['elemento']}: empenhada=R$ {d.get('empenhada', 0):,.2f} | "
                            f"liquidada=R$ {d.get('liquidada', 0):,.2f} | paga=R$ {d.get('paga', 0):,.2f}"
                        )
            except TcePiAPIError as exc:
                self.stdout.write(self.style.WARNING(f"  Erro ao consultar despesas por elemento: {exc}"))

            # --------------------------------------------------------
            # 3. Licitações do órgão — listagem informativa
            # --------------------------------------------------------
            if not options["pular_licitacoes"]:
                try:
                    calendario = client.licitacoes_orgao(codigo_ug)
                except TcePiAPIError as exc:
                    self.stdout.write(self.style.WARNING(f"  Erro ao consultar calendário de licitações: {exc}"))
                    calendario = []

                datas_exercicio = [
                    item["link"] for item in calendario
                    if item.get("link", "").startswith(str(exercicio))
                ]
                if datas_exercicio:
                    self.stdout.write(f"  {len(datas_exercicio)} data(s) com licitação registrada no TCE em {exercicio}:")
                    for data_str in datas_exercicio:
                        try:
                            itens = client.licitacoes_orgao_data(codigo_ug, data_str, esfera=2, qtde_por_pagina=100)
                        except TcePiAPIError as exc:
                            self.stdout.write(self.style.WARNING(f"    {data_str}: erro ao detalhar ({exc})"))
                            continue
                        for lic in itens:
                            self.stdout.write(
                                f"    {data_str} | {lic.get('modalidade', '—')} | "
                                f"R$ {lic.get('previsto', 0):,.2f} | {lic.get('unidadeOrcamentaria', '—')} | "
                                f"{(lic.get('objeto') or '')[:100]}"
                            )
                            if lic.get("mural"):
                                self.stdout.write(f"      mural: {lic['mural']} (idLicitacaoWeb={lic.get('idLicitacaoWeb')})")
                else:
                    self.stdout.write("  Nenhuma licitação do TCE registrada para este órgão no exercício informado.")

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Resumo ==="))
        self.stdout.write(
            f"  CONFERE: {totais_gerais['confere']} | DIVERGE: {totais_gerais['diverge']} | "
            f"NAO ENCONTRADO NO TCE: {totais_gerais['nao_encontrado']}"
        )
        self.stdout.write(self.style.WARNING(
            "\nSomente leitura — nenhuma alteração foi feita. Casos DIVERGE ou NAO ENCONTRADO "
            "precisam de revisão manual antes de qualquer correção."
        ))

        if arquivo_saida:
            arquivo_saida.close()
