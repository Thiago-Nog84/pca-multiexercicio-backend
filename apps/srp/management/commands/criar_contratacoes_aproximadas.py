"""
Cria ContratacaoDecorrente para contratos já vinculados via Contrato.arp_origem.

Estratégia por número de itens da ARP:
  1 item  → quantidade = round(valor_contrato / valor_unitario) — alta confiança
  2 itens → SequenceMatcher entre Contrato.objeto e ItemARP.descricao — média confiança
  3+ itens → reporta como ambíguo; requer NE manual ou --forcar-multiplos

Uso:
  python manage.py criar_contratacoes_aproximadas --dry-run
  python manage.py criar_contratacoes_aproximadas --dry-run --arp 00012/2025
  python manage.py criar_contratacoes_aproximadas
  python manage.py criar_contratacoes_aproximadas --forcar-multiplos --min-similaridade 0.25
"""

from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher

from django.core.management.base import BaseCommand
from django.db.models import F

from apps.contratos.models import Contrato
from apps.srp.models import AtaRegistroPrecos, ContratacaoDecorrente, ItemARP


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "")[:200].lower(), (b or "")[:200].lower()).ratio()


def _calcular_quantidade(valor_contrato: Decimal, valor_unitario: Decimal) -> Decimal:
    if not valor_unitario or valor_unitario == 0:
        return Decimal("1")
    qtd = valor_contrato / valor_unitario
    return qtd.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = "Cria ContratacaoDecorrente aproximadas a partir de Contrato.arp_origem"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--arp", type=str, help="Filtrar por número de ARP ex: 00012/2025")
        parser.add_argument(
            "--forcar-multiplos",
            action="store_true",
            help="Tenta criar CD mesmo para ARPs com 3+ itens (usa melhor match por similaridade)",
        )
        parser.add_argument(
            "--min-similaridade",
            type=float,
            default=0.20,
            help="Score mínimo de similaridade para aceitar match (default 0.20)",
        )
        parser.add_argument(
            "--sobrescrever",
            action="store_true",
            help="Recria CD mesmo se já existir com o mesmo numero_pedido",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        filtro_arp = options["arp"]
        forcar = options["forcar_multiplos"]
        min_sim = options["min_similaridade"]
        sobrescrever = options["sobrescrever"]

        if dry:
            self.stdout.write("*** DRY-RUN — nenhuma alteração será salva ***\n")

        qs = Contrato.objects.filter(arp_origem__isnull=False).select_related(
            "arp_origem", "unidade_requisitante"
        )
        if filtro_arp:
            qs = qs.filter(arp_origem__numero_arp=filtro_arp)

        # Pré-carrega itens por ARP
        arps_ids = set(qs.values_list("arp_origem_id", flat=True))
        itens_por_arp: dict[int, list[ItemARP]] = {}
        for item in ItemARP.objects.filter(arp_id__in=arps_ids):
            itens_por_arp.setdefault(item.arp_id, []).append(item)

        criados = 0
        pulados = 0
        ambiguos = []

        for c in qs.order_by("arp_origem__numero_arp", "numero_contrato"):
            arp = c.arp_origem
            itens = itens_por_arp.get(arp.pk, [])
            n_itens = len(itens)
            valor = c.valor_atual or c.valor_inicial or Decimal("0")

            if not sobrescrever:
                if ContratacaoDecorrente.objects.filter(
                    arp=arp, numero_pedido=c.numero_contrato
                ).exists():
                    pulados += 1
                    continue

            # ── 1 item ──────────────────────────────────────────────
            if n_itens == 1:
                item = itens[0]
                qtd = _calcular_quantidade(valor, item.valor_unitario)
                vl_total = (qtd * item.valor_unitario).quantize(Decimal("0.01"))
                confianca = "ALTA"

            # ── 2 itens ─────────────────────────────────────────────
            elif n_itens == 2:
                scores = [(it, _sim(c.objeto or "", it.descricao)) for it in itens]
                scores.sort(key=lambda x: -x[1])
                item, score = scores[0]
                if score < min_sim:
                    ambiguos.append((c, arp, itens, scores))
                    continue
                qtd = _calcular_quantidade(valor, item.valor_unitario)
                vl_total = (qtd * item.valor_unitario).quantize(Decimal("0.01"))
                confianca = f"MÉDIA (score={score:.2f})"

            # ── 3+ itens ────────────────────────────────────────────
            else:
                if not forcar:
                    ambiguos.append((c, arp, itens, []))
                    continue
                scores = [(it, _sim(c.objeto or "", it.descricao)) for it in itens]
                scores.sort(key=lambda x: -x[1])
                item, score = scores[0]
                if score < min_sim:
                    ambiguos.append((c, arp, itens, scores))
                    continue
                qtd = _calcular_quantidade(valor, item.valor_unitario)
                vl_total = (qtd * item.valor_unitario).quantize(Decimal("0.01"))
                confianca = f"BAIXA ({n_itens} itens, score={score:.2f})"

            self.stdout.write(
                f"  [{confianca}] {c.numero_contrato} → ARP {arp.numero_arp} "
                f"item={item.numero_item} qtd={qtd} vl={vl_total} | {(item.descricao or '')[:60]}"
            )

            if not dry:
                cd = ContratacaoDecorrente(
                    arp=arp,
                    item_arp=item,
                    numero_pedido=c.numero_contrato,
                    numero_sei="",
                    exercicio=(c.data_assinatura.year if c.data_assinatura else 2025),
                    quantidade=qtd,
                    valor_unitario=item.valor_unitario,
                    valor_total=vl_total,
                    data_emissao=c.data_assinatura or arp.data_inicio_vigencia,
                    status="concluido",
                    unidade_requisitante=c.unidade_requisitante,
                )
                ContratacaoDecorrente.objects.bulk_create([cd])
                ItemARP.objects.filter(pk=item.pk).update(
                    quantidade_contratada=F("quantidade_contratada") + qtd
                )
            criados += 1

        # ── Relatório ───────────────────────────────────────────────
        self.stdout.write(f"\n{'[DRY-RUN] ' if dry else ''}Criados: {criados} | Pulados (já existia): {pulados}")

        if ambiguos:
            self.stdout.write(f"\n── AMBÍGUOS ({len(ambiguos)}) — requerem NE manual ──")
            for c, arp, itens, scores in ambiguos:
                self.stdout.write(
                    f"  {c.numero_contrato} → ARP {arp.numero_arp} ({len(itens)} itens) | {(c.objeto or '')[:70]}"
                )
                if scores:
                    top = scores[:3]
                    for it, sc in top:
                        self.stdout.write(
                            f"    score={sc:.2f} item={it.numero_item} {(it.descricao or '')[:60]}"
                        )
