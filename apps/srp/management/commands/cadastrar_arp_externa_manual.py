"""
Management command: cadastrar_arp_externa_manual
====================================================
Cadastra registros de `ARPExterna` (carona RECEBIDA — ARP de outro órgão à
qual o MPPI aderiu) confirmados via documento fonte (SEI), e vincula o
`Contrato` correspondente via `arp_externa_origem`.

Complementa `corrigir_arp_origem_carona`, que zera o `arp_origem` (ARP
própria) errado desses contratos. Este comando faz a segunda metade: dá ao
contrato uma origem correta (`ARPExterna`) em vez de deixá-lo sem nenhuma
origem registrada.

Idempotente: usa `get_or_create` por (numero_arp_origem, fornecedor_cnpj_cpf,
numero_sei_adesao) — nunca duplica se rodado de novo. Nunca atualiza um
registro já existente (só avisa).

Uso:
  python manage.py cadastrar_arp_externa_manual --dry-run
  python manage.py cadastrar_arp_externa_manual
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato
from apps.srp.models import ARPExterna

# Cada entrada: dict completo de campos do ARPExterna + pk do Contrato local
# a vincular via arp_externa_origem.
ARPS_EXTERNAS_MANUAIS = [
    {
        # Fonte: SEI 19.21.0427.0019479/2025-78 (P.G.A. adesão), documentos
        # "Ata de Registro de Preço PM SANTA CATARINA - ATA PE 39 24 -
        # VIDEOWALL" e "Documento de Formalização da Demanda - DFD 1044291",
        # fornecidos em 2026-07-30. Confirmado pelo usuário como carona
        # externa — este contrato estava com `arp_origem` apontando por
        # engano para a ARP 00016/2025 (toners do MPPI), contaminando a
        # conciliação de fração dessa ARP (ver
        # docs/fracao_quantidades_2026-07-29.md).
        #
        # Vigência da ATA (não do contrato): publicada DOE 25/03/2025,
        # validade de 1 ano contada do primeiro dia útil subsequente à
        # publicação — datas abaixo são CALCULADAS a partir dessa regra
        # (26/03/2025 + 1 ano), não estão escritas literalmente no
        # documento. Conferir se houve prorrogação antes de reportar como
        # fato consumado.
        "orgao_gerenciador_nome": "Polícia Militar de Santa Catarina",
        "orgao_gerenciador_cnpj": "13.925.994/0001-07",
        "numero_arp_origem": "039/PMSC/2024",
        "numero_pncp_origem": "",  # não localizado assinado/publicado nos autos deste SEI
        "objeto": (
            "Solução de Video Wall com 4 monitores de LED 55\", decodificador, "
            "suporte de parede/painel e instalação — para o auditório do "
            "Ministério Público do Estado do Piauí (Rua Lindolfo Monteiro, 911, "
            "Fátima, Teresina-PI)."
        ),
        "fornecedor_razao_social": "REPREMIG REPRESENTAÇÃO E COMERCIO DE MINAS GERAIS LTDA",
        "fornecedor_cnpj_cpf": "65.149.197/0002-51",
        "data_inicio_vigencia": date(2025, 3, 26),  # calculada — ver nota acima
        "data_fim_vigencia": date(2026, 3, 25),      # calculada — ver nota acima
        "numero_sei_adesao": "19.21.0427.0019479/2025-78",
        "quantidade_autorizada": Decimal("1"),
        "valor_unitario": Decimal("55600.00"),
        "valor_total_autorizado": Decimal("55600.00"),
        "quantidade_utilizada": Decimal("1"),  # já consumida integralmente pelo Empenho 2025NE00141
        "observacoes": (
            "Cadastrado retroativamente em 2026-07-30 para corrigir vínculo errado "
            "(estava em arp_origem=ARP 00016/2025, toners do MPPI). Datas de "
            "vigência calculadas a partir da regra do item 5.1 da Ata (1 ano da "
            "publicação DOE), não conferidas contra prorrogação."
        ),
        "_contrato_pk": 159,  # Contrato 2025NE00141 (REPREMIG)
    },
]


class Command(BaseCommand):
    help = "Cadastra ARPExterna confirmadas via documento fonte e vincula o Contrato correspondente"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        criadas = 0
        ja_existiam = 0
        vinculados = 0
        nao_vinculados = 0

        for dados in ARPS_EXTERNAS_MANUAIS:
            dados = dict(dados)
            contrato_pk = dados.pop("_contrato_pk")

            existente = ARPExterna.objects.filter(
                numero_arp_origem=dados["numero_arp_origem"],
                fornecedor_cnpj_cpf=dados["fornecedor_cnpj_cpf"],
                numero_sei_adesao=dados["numero_sei_adesao"],
            ).first()

            if existente:
                ja_existiam += 1
                arp_externa = existente
                self.stdout.write(
                    f"  [já existe, não mexido] pk={existente.pk} ARP {dados['numero_arp_origem']!r} "
                    f"— {dados['fornecedor_razao_social']}"
                )
            else:
                self.stdout.write(
                    f"  ARP {dados['numero_arp_origem']!r} — {dados['fornecedor_razao_social']} — "
                    f"R$ {dados['valor_total_autorizado']:,.2f} — SEI {dados['numero_sei_adesao']}"
                )
                if not dry_run:
                    arp_externa = ARPExterna.objects.create(**dados)
                else:
                    arp_externa = None
                criadas += 1

            contrato = Contrato.objects.filter(pk=contrato_pk).first()
            if not contrato:
                nao_vinculados += 1
                self.stdout.write(self.style.ERROR(
                    f"      contrato pk={contrato_pk} não encontrado — não foi possível vincular."
                ))
                continue

            if contrato.arp_externa_origem_id:
                self.stdout.write(
                    f"      contrato pk={contrato_pk} já tem arp_externa_origem "
                    f"(pk={contrato.arp_externa_origem_id}) — não mexido."
                )
                continue

            self.stdout.write(
                f"      vincular contrato pk={contrato_pk} ({contrato.numero_contrato!r}) "
                f"-> arp_externa_origem"
            )
            if not dry_run:
                contrato.arp_externa_origem = arp_externa
                contrato.save(update_fields=["arp_externa_origem"])
            vinculados += 1

        modo = "[DRY-RUN — nada gravado] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}ARPExterna criadas: {criadas} | Já existiam: {ja_existiam} | "
            f"Contratos vinculados: {vinculados} | Não vinculados (erro): {nao_vinculados}"
        ))
