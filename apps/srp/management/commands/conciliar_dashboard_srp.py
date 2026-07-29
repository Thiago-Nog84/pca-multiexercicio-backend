"""
Management command: conciliar_dashboard_srp
=============================================
Concilia as Contratações Decorrentes e os saldos dos itens das ARPs para o Dashboard SRP,
garantindo que nenhum item ultrapasse sua quantidade registrada (evitando saldo negativo)
e distribuindo contratos que abrangem múltiplos itens de forma proporcional/prioritária.

Uso:
    python manage.py conciliar_dashboard_srp --dry-run
    python manage.py conciliar_dashboard_srp --arp 00001/2026
    python manage.py conciliar_dashboard_srp
"""

from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

from apps.contratos.models import Contrato
from apps.srp.models import AtaRegistroPrecos, ContratacaoDecorrente, ItemARP
from apps.srp.services.dadosabertos_contratos import (
    resolver_itens_para_contrato,
    resolver_quantidade_por_valor_homologado,
)


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "")[:200].lower(), (b or "")[:200].lower()).ratio()


# Alocações oficiais extraídas diretamente de Termos de Contrato / Apêndices assinados
OFFICIAL_CONTRACT_ITEMS = {
    ("00001/2026", "18/2026/PGJ"): {
        1: Decimal("2"),    # Assistente Social (30h/sem)
        2: Decimal("2"),    # Pedagogo (30h/sem)
        3: Decimal("3"),    # Psicólogo (20h/sem)
        4: Decimal("576"),  # Diárias
    },
    ("00003/2026", "28/2026 PGJ"): {
        10: Decimal("994"),   # Açúcar Cristal 1kg (Empenho 2026NE00428)
        11: Decimal("11450"), # Café 250g (Empenho 2026NE00428)
    },
    ("00027/2025", "71/2025/FPDC"): {
        # Fonte: CONTRATO-No-71-2025-FPDC.pdf (Apêndice/Memória de Cálculo), conferido
        # também no Extrato do Contrato (Diário Eletrônico MPPI nº 1848) e na Nota de
        # Empenho 2025NE00114 — os 3 documentos batem exatamente.
        # Bug anterior: o algoritmo de similaridade/sobra (fallback abaixo) atribuía
        # 400 desktops (2x o real) ao item 1 e jogava a sobra de R$2.986,00 como
        # 0,4811 notebooks no item 2 — quantidade fisicamente impossível.
        1: Decimal("200"),  # Computador Desktop All-In-One
        2: Decimal("198"),  # Notebook com mochila e mouse
    },
    ("00035/2025", "2025NE01038"): {
        # Fonte: Nota de Empenho 2025NE01038 (SEI 19.21.0428.0031214/2025-20, pg. 57/61/89/97),
        # conferida em 4 pontos independentes do mesmo processo (Autorização de Empenho,
        # Nota de Empenho do Siafe, Ordem de Fornecimento e Controle de Saldo) — todos batem
        # em R$ 51.625,00.
        # O Contrato local (pk=161) tem valor_inicial=R$108.135,00, que é o TOTAL do
        # contrato 92/2025/PGJ para 24 meses — mas numero_contrato aqui é o número da nota
        # de empenho, que cobre só a 1ª aquisição (12 meses, R$51.625,00) do Lote 1.
        # O fallback estava dividindo o valor do CONTRATO INTEIRO (108.135,00) contra esse
        # pedido parcial, sobrando R$201,00 alocados como 0,7614 toners fantasma no item 4
        # (que é do Lote 2, reservado ME/EPP — não comprado nesta nota).
        1: Decimal("150"),  # Toner MLT-D203U (SL-M4070FR), Lote 1 — Empenho 2025NE01038
        3: Decimal("65"),   # Toner MLT-D205L (SCX-4833), Lote 1 — Empenho 2025NE01038
        # Item 2 (MLT-D205E) e itens 4/5/6 (Lote 2) não foram comprados nesta nota — 0.
    },
}


class Command(BaseCommand):
    help = "Concilia saldo das ARPs e distribui contratações evitando saldos negativos no Dashboard SRP"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simula sem salvar no banco")
        parser.add_argument(
            "--arp", type=str, nargs="+",
            help="Filtrar por um ou mais números de ARP (ex: --arp 00001/2026 00002/2026)",
        )
        parser.add_argument(
            "--saida", type=str, default=None,
            help="Grava a saída também num arquivo UTF-8 nesse caminho (evita o mojibake do '>' do PowerShell)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        filtro_arp = options["arp"]

        arquivo_saida = None
        if options.get("saida"):
            arquivo_saida = open(options["saida"], "w", encoding="utf-8")
            escrever_original = self.stdout.write

            def escrever_e_gravar(msg="", *a, **kw):
                escrever_original(msg, *a, **kw)
                arquivo_saida.write(str(msg) + "\n")

            self.stdout.write = escrever_e_gravar

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nenhuma alteração será salva ***\n"))

        arps = AtaRegistroPrecos.objects.all()
        if filtro_arp:
            from django.db.models import Q
            q = Q()
            for numero in filtro_arp:
                q |= Q(numero_arp__icontains=numero)
            arps = arps.filter(q)

        arps_conciliadas = 0
        total_cds_criadas = 0

        for arp in arps:
            # Contratos RESCINDIDOS não consomem saldo da ata: o quantitativo
            # volta a ficar disponível para nova contratação. Caso real que
            # motivou o filtro (2026-07-29): ARP 00004/2026 — a MASTER
            # FACILITIES assinou o contrato 29/2026/PGJ e depois desistiu; a
            # ALFA (cadastro de reserva) assumiu a ata e contratou o MESMO
            # objeto (contrato 35/2026). Sem este filtro os dois contratos
            # consumiriam o saldo, dobrando o consumo do mesmo objeto.
            # ⚠️ Só 'rescindido' é excluído — 'encerrado' significa contrato
            # cumprido até o fim, que consumiu o quantitativo de verdade.
            contratos = (
                Contrato.objects
                .filter(arp_origem=arp)
                .exclude(status="rescindido")
                .order_by("data_assinatura", "numero_contrato")
            )
            if not contratos.exists():
                continue

            arps_conciliadas += 1
            self.stdout.write(f"\nConciliando ARP {arp.numero_arp} ({contratos.count()} contratos vinculados)...")

            with transaction.atomic():
                # 1. Remove contratações decorrentes anteriores desta ARP para reconstrução limpa
                ContratacaoDecorrente.objects.filter(arp=arp).delete()

                # 2. Zera as quantidades contratadas dos itens em memória e no banco
                ItemARP.objects.filter(arp=arp).update(quantidade_contratada=Decimal("0"))
                itens = list(arp.itens.all().order_by("numero_item"))
                for item in itens:
                    item.quantidade_contratada = Decimal("0")

                cds_to_create = []

                # 3. Distribui cada contrato nos itens da ARP
                for c in contratos:
                    chave_oficial = (arp.numero_arp, c.numero_contrato)
                    mapa = None
                    fonte_mapa = None
                    if chave_oficial in OFFICIAL_CONTRACT_ITEMS:
                        mapa = OFFICIAL_CONTRACT_ITEMS[chave_oficial]
                        fonte_mapa = "manual (OFFICIAL_CONTRACT_ITEMS)"
                    else:
                        try:
                            mapa_auto = resolver_itens_para_contrato(c)
                        except Exception as exc:
                            mapa_auto = None
                            self.stdout.write(self.style.WARNING(
                                f"  [API dadosabertos] erro ao consultar {c.numero_contrato}: {exc}"
                            ))
                        if mapa_auto:
                            mapa = mapa_auto
                            fonte_mapa = "automático (dadosabertos Módulo Contratos)"
                        else:
                            # Fallback 2: casa CNPJ do fornecedor + preço unitário
                            # homologado na ARP (API pública do PNCP) contra o
                            # valor_inicial do contrato. Cobre contratos de
                            # qualquer ano (dadosabertos Módulo Contratos só
                            # cobre 2026+) — só aceita se a combinação de
                            # quantidades for matematicamente única.
                            try:
                                mapa_auto2 = resolver_quantidade_por_valor_homologado(c)
                            except Exception as exc:
                                mapa_auto2 = None
                                self.stdout.write(self.style.WARNING(
                                    f"  [API PNCP] erro ao consultar {c.numero_contrato}: {exc}"
                                ))
                            if mapa_auto2:
                                mapa = mapa_auto2
                                fonte_mapa = "automático (PNCP — valor homologado)"

                    if mapa is not None:
                        self.stdout.write(f"  [{fonte_mapa}] {c.numero_contrato}: {dict(mapa)}")
                        for item in itens:
                            if item.numero_item in mapa:
                                qtd = mapa[item.numero_item]
                                vl_total = (qtd * item.valor_unitario).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                                cds_to_create.append(
                                    ContratacaoDecorrente(
                                        arp=arp,
                                        item_arp=item,
                                        numero_pedido=c.numero_contrato,
                                        numero_sei="",
                                        exercicio=(c.data_assinatura.year if c.data_assinatura else 2026),
                                        quantidade=qtd,
                                        valor_unitario=item.valor_unitario,
                                        valor_total=vl_total,
                                        data_emissao=c.data_assinatura or arp.data_inicio_vigencia,
                                        status="concluido",
                                        unidade_requisitante=c.unidade_requisitante,
                                    )
                                )
                                item.quantidade_contratada += qtd
                                total_cds_criadas += 1
                        continue

                    val_restante = c.valor_inicial or Decimal("0")
                    if val_restante <= 0:
                        continue

                    self.stdout.write(self.style.WARNING(
                        f"  [fallback - similaridade/valor] {c.numero_contrato}: SEM resolver automático "
                        f"(nem manual, nem dadosabertos, nem PNCP) — dividindo por similaridade de texto + "
                        f"valor/preço. Risco de quantidade fracionária errada (ver checagem [fracao] da auditoria)."
                    ))

                    # Ordena os itens por similaridade com o objeto do contrato
                    obj_c = c.objeto or ""
                    candidatos = sorted(
                        itens,
                        key=lambda i: (_sim(obj_c, i.descricao or ""), -i.numero_item),
                        reverse=True
                    )

                    for idx, item in enumerate(candidatos):
                        if not item.valor_unitario or item.valor_unitario <= 0:
                            continue

                        qtd_disp = item.quantidade_registrada - item.quantidade_contratada
                        if qtd_disp <= Decimal("0"):
                            continue

                        val_disp = (qtd_disp * item.valor_unitario).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        is_last_item = (idx == len(candidatos) - 1)

                        if val_restante <= val_disp:
                            qtd_raw = val_restante / item.valor_unitario
                            int_qtd = Decimal(int(qtd_raw))
                            # Se não for o último candidato e couber quantidade inteira (ex: postos de trabalho),
                            # prioriza o número inteiro e repassa a sobra fracionada para o próximo item (ex: diárias)
                            if not is_last_item and int_qtd > Decimal("0") and (qtd_raw - int_qtd) > Decimal("0.0001"):
                                qtd = int_qtd
                                val_total_cd = (qtd * item.valor_unitario).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                                val_restante -= val_total_cd
                            else:
                                qtd = qtd_raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                                if qtd > qtd_disp:
                                    qtd = qtd_disp
                                val_total_cd = val_restante
                                val_restante = Decimal("0")
                        else:
                            # Contrato excede este item, consome todo o saldo disponível e passa para o próximo
                            qtd = qtd_disp
                            val_total_cd = val_disp
                            val_restante -= val_disp

                        if qtd > Decimal("0"):
                            cds_to_create.append(
                                ContratacaoDecorrente(
                                    arp=arp,
                                    item_arp=item,
                                    numero_pedido=c.numero_contrato,
                                    numero_sei="",
                                    exercicio=(c.data_assinatura.year if c.data_assinatura else 2026),
                                    quantidade=qtd,
                                    valor_unitario=item.valor_unitario,
                                    valor_total=val_total_cd,
                                    data_emissao=c.data_assinatura or arp.data_inicio_vigencia,
                                    status="concluido",
                                    unidade_requisitante=c.unidade_requisitante,
                                )
                            )
                            item.quantidade_contratada += qtd
                            total_cds_criadas += 1

                        if val_restante <= Decimal("0"):
                            break

                # 4. Grava as contratações decorrentes em lote e sincroniza
                #    quantidade_contratada atomicamente via criar_em_lote().
                #    ATENÇÃO: não usar bulk_create direto — ele não atualiza o
                #    campo e causa 0% de consumo no Dashboard SRP.
                if not dry_run and cds_to_create:
                    # Injeta a quantidade já calculada antes de criar em lote
                    # (criar_em_lote acumularia delta sobre o atual que já foi
                    # zerado via update() acima — sobrescrevemos com valor exato)
                    ContratacaoDecorrente.objects.bulk_create(cds_to_create)

                # 5. Salva a quantidade contratada exata em cada item da ARP no banco
                if not dry_run:
                    for item in itens:
                        ItemARP.objects.filter(pk=item.pk).update(quantidade_contratada=item.quantidade_contratada)

                if dry_run:
                    transaction.set_rollback(True)

            # Exibe resumo dos itens desta ARP após conciliação
            for item in itens:
                saldo = item.quantidade_registrada - item.quantidade_contratada
                self.stdout.write(
                    f"  Item {item.numero_item:02d}: Reg={item.quantidade_registrada:10.4f} | "
                    f"Contratada={item.quantidade_contratada:10.4f} | Saldo={saldo:10.4f}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nConciliação concluída: {arps_conciliadas} ARPs processadas, "
                f"{total_cds_criadas} contratações decorrentes conciliadas."
            )
        )

        if arquivo_saida:
            arquivo_saida.close()
