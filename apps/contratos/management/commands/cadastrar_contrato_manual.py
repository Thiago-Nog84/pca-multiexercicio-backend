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
