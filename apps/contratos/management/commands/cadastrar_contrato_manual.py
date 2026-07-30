"""
Management command: cadastrar_contrato_manual
====================================================
Cadastra contratos confirmados via documento fonte (SEI/PNCP/SIAFE) que
foram achados como genuinamente FALTANTES no banco local — geralmente
descobertos por uma NE do SIAFE cujo `codContrato` não bate com nenhum
`Contrato.codigo_siafe` existente (ver `investigar_ne_faltante`).

Idempotente: usa `get_or_create` por (orgao, numero_contrato) — nunca cria
duplicata se rodado de novo. Nunca atualiza um contrato já existente (se
achar, só avisa e não mexe — evita sobrescrever correções manuais feitas
depois pelo usuário).

Após cadastrar, rode `importar_empenhos_siafe --exercicio <ano>` de novo —
agora que o `codigo_siafe` bate, a NE que estava "sem contrato local" vai
ser importada automaticamente como `Empenho`.

Uso:
  python manage.py cadastrar_contrato_manual --dry-run
  python manage.py cadastrar_contrato_manual
"""

import re
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato
from apps.core.models import Orgao
from apps.srp.models import AtaRegistroPrecos

CNPJ_MPPI = "05805924000189"


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))

# Cada entrada: dict completo de campos do Contrato + numero_arp_origem
# (opcional, string a buscar em AtaRegistroPrecos.numero_arp).
CONTRATOS_MANUAIS = [
    {
        # Fonte: PDF SEI 19.21.0428.0012055/2026-09 (Contrato 13/2026/PGJ,
        # pg. 26/30 — Termo de Contrato + Apêndice/Memória de Cálculo) e
        # Nota de Empenho 2026NE00165 (pg. 24) — achado via investigar_ne_faltante
        # (2026-07-29): NE com codContrato=26100672 não batia com nenhum
        # contrato local, porque este contrato nunca tinha sido cadastrado.
        "numero_contrato": "13/2026/PGJ",
        "numero_sei": "19.21.0428.0002645/2026-36",  # PGA original do contrato
        "tipo": "fornecimento",
        "objeto": (
            "Aquisição de material de higiene e limpeza para o MP-PI "
            "(copos descartáveis, limpadores, sabonetes líquidos, inseticidas, "
            "aromatizadores de ambientes, soda cáustica), conforme condições, "
            "quantidades e exigências estabelecidas no Termo de Referência e "
            "no Apêndice (Tabela 1) deste instrumento."
        ),
        "contratado_razao_social": "Laís G de Sousa – Eireli",
        "contratado_cnpj_cpf": "39.853.645/0001-02",
        "valor_inicial": Decimal("34966.00"),   # total da contratação, 24 meses (lotes 5 e 7)
        "valor_atual": Decimal("34966.00"),
        "saldo_disponivel": Decimal("12465.00"),  # "SALDO A EMPENHAR" citado no doc, pg. 53
        "valor_empenhado": Decimal("22501.00"),   # NE 2026NE00165 — valor para o exercício de 2026
        "codigo_siafe": "26100672",
        "data_assinatura": date(2026, 2, 19),
        "data_inicio_vigencia": date(2026, 2, 19),
        "data_fim_vigencia": date(2028, 2, 19),
        "unidade_orcamentaria": "pgj",
        "numero_arp_origem": "51/2025",  # ARP Nº 51/2025, Pregão Eletrônico nº 90023/2025, Lotes 05 e 07
    },
    {
        # Fonte: 4 documentos do SEI 19.21.0010.0018316/2024-04, fornecidos em
        # 2026-07-30 — Contrato (0795673), Apostilamento 01 (0953619),
        # Apostilamento 02 (1053628) e Termo Aditivo 01 (1222671).
        # Achado via sugerir_vinculo_ne_contrato: codContrato=24010263 com 2 NEs
        # de 2026 (2026NE00885 R$25.000 peças + 2026NE00886 R$100.000 serviços,
        # ambas emitidas em 28/07/2026) sem par local — este contrato nunca
        # tinha sido cadastrado. Era a última divergência acionável da PGJ na
        # conciliação com o TCE (diferença de exatamente R$125.000,00).
        #
        # HISTÓRICO DE VALOR (o contrato precisou de 2 apostilamentos para
        # corrigir um erro material de soma no instrumento original):
        #   - Contrato original (assinado 24/07/2024): texto da Cláusula
        #     Terceira dizia "R$223.042,39, sendo R$61.956,21 serviços e
        #     R$10.000,00 peças" — não fecha (61.956,21 + 10.000 = 71.956,21).
        #     O Anexo I do próprio contrato já trazia o total correto de
        #     R$259.042,39 (R$223.042,39 serviços + R$36.000,00 peças).
        #   - Apostilamento 01 (17/02/2025): corrigiu o total para R$259.042,39,
        #     mas manteve peças em R$10.000,00 — ainda não fechava.
        #   - Apostilamento 02 (10/06/2025): corrigiu peças para R$36.000,00.
        #     Só então 223.042,39 + 36.000,00 = 259.042,39 fecha.
        #   - Termo Aditivo 01 (11/12/2025): prorroga 18 meses a partir de
        #     24/01/2026 e reajusta pelo IPCA/IBGE — novo valor R$271.367,89
        #     (R$233.654,97 serviços + R$37.712,92 peças).
        #
        # valor_inicial = valor original já corrigido pelos apostilamentos
        # (que são meras correções de erro material, não alteram o objeto).
        # valor_atual = valor após o Termo Aditivo 01 (reajuste IPCA).
        "numero_contrato": "29/2024/PGJ",
        "numero_sei": "19.21.0010.0018316/2024-04",
        "tipo": "servico_continuo",
        "objeto": (
            "Contratação de empresa especializada na prestação de serviços de "
            "manutenção preventiva e corretiva COM FORNECIMENTO DE PEÇAS dos "
            "aparelhos de ar-condicionado tipo split, bebedouro, purificador de "
            "água, frigobar, geladeira, recarga de gás para split, geladeira, "
            "frigobar e bebedouro, bem como instalação, desinstalação e "
            "substituição de aparelhos de ar-condicionado (tipo split) de "
            "propriedade do MPPI, na sede da PGJ e demais órgãos, em Teresina e "
            "no interior do Estado (Lotes II, III e IV)."
        ),
        "contratado_razao_social": "EASWELL ENGENHARIA LTDA",
        "contratado_cnpj_cpf": "37.827.616/0001-40",
        "valor_inicial": Decimal("259042.39"),
        "valor_atual": Decimal("271367.89"),
        # Não há dado de execução/medição nos documentos fornecidos — o saldo
        # real depende das ordens de serviço já executadas. Registrado igual ao
        # valor_atual; ajustar quando houver a memória de execução.
        "saldo_disponivel": Decimal("271367.89"),
        # Deixado zerado de propósito: o importar_empenhos_siafe recalcula a
        # partir das NEs reais (2024NE00671, 2025NE01494/01495, 2026NE00885/00886).
        "valor_empenhado": Decimal("0.00"),
        "codigo_siafe": "24010263",
        "data_assinatura": date(2024, 7, 24),      # última assinatura eletrônica (contratada)
        "data_inicio_vigencia": date(2024, 7, 24),  # 18 meses da assinatura
        # Aditivo 01: mais 18 meses contados de 24/01/2026 -> 24/07/2027
        "data_fim_vigencia": date(2027, 7, 24),
        "unidade_orcamentaria": "pgj",
        "numero_arp_origem": "23/2023",  # ATA 23/2023, Pregão Eletrônico 28/2023, Lotes II, III e IV
    },
]


class Command(BaseCommand):
    help = "Cadastra contratos confirmados manualmente via documento fonte (idempotente, nunca sobrescreve existente)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        orgao = next(
            (o for o in Orgao.objects.all() if _digitos(o.cnpj) == CNPJ_MPPI), None
        )
        if not orgao:
            todos = list(Orgao.objects.values_list("pk", "sigla", "cnpj"))
            self.stdout.write(self.style.ERROR(
                f"Órgão com CNPJ {CNPJ_MPPI} não encontrado (comparando dígitos) — não dá pra cadastrar nada. "
                f"Órgãos existentes no banco: {todos}"
            ))
            return

        criados = 0
        ja_existiam = 0

        for dados in CONTRATOS_MANUAIS:
            dados = dict(dados)
            numero_arp = dados.pop("numero_arp_origem", None)

            existente = Contrato.objects.filter(
                orgao=orgao, numero_contrato=dados["numero_contrato"]
            ).first()
            if existente:
                ja_existiam += 1
                self.stdout.write(
                    f"  [já existe, não mexido] pk={existente.pk} {dados['numero_contrato']!r} "
                    f"(codigo_siafe atual={existente.codigo_siafe!r})"
                )
                continue

            arp = None
            if numero_arp:
                arp = AtaRegistroPrecos.objects.filter(numero_arp__icontains=numero_arp).first()

            self.stdout.write(
                f"  {dados['numero_contrato']!r} — {dados['contratado_razao_social']} — "
                f"R$ {dados['valor_inicial']:,.2f} — arp_origem={arp.numero_arp if arp else '(não achada, ficará vazio)'}"
            )

            if not dry_run:
                Contrato.objects.create(orgao=orgao, arp_origem=arp, **dados)
            criados += 1

        modo = "[DRY-RUN — nada gravado] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Criados: {criados} | Já existiam (mantidos intactos): {ja_existiam}"
        ))
        if criados and not dry_run:
            self.stdout.write(self.style.WARNING(
                "\nAgora rode `importar_empenhos_siafe --exercicio 2026` de novo — a NE que estava "
                "sem contrato local deve ser importada automaticamente."
            ))
