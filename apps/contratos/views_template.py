"""Views Django Templates — Módulo Contratos."""

from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from .models import Aditivo, Contrato

# Modelos importados de fontes externas (srp app)
try:
    from apps.srp.models import ContratoARP, ContratoComprasnet
    _tem_dados_externos = True
except ImportError:
    _tem_dados_externos = False


@method_decorator(login_required, name="dispatch")
class DashboardContratosView(View):
    template_name = "contratos/dashboard.html"

    def get(self, request):
        hoje = date.today()
        d30  = hoje + timedelta(days=30)
        d60  = hoje + timedelta(days=60)
        d90  = hoje + timedelta(days=90)
        d120 = hoje + timedelta(days=120)

        # ── Contratos locais ──────────────────────────────────────────────
        contratos = Contrato.objects.select_related("orgao", "gestor")
        total_local    = contratos.count()
        vigentes_local = contratos.filter(status="vigente").count()
        encerrados     = contratos.filter(status="encerrado").count()
        rescindidos    = contratos.filter(status="rescindido").count()

        vencendo_30  = contratos.filter(status="vigente", data_fim_vigencia__range=(hoje, d30)).count()
        vencendo_60  = contratos.filter(status="vigente", data_fim_vigencia__range=(hoje, d60)).count()
        vencendo_90  = contratos.filter(status="vigente", data_fim_vigencia__range=(hoje, d90)).count()
        vencendo_120 = contratos.filter(status="vigente", data_fim_vigencia__range=(hoje, d120)).count()

        valor_local     = contratos.filter(status="vigente").aggregate(v=Sum("valor_atual"))["v"] or 0
        saldo_disponivel = contratos.filter(status="vigente").aggregate(v=Sum("saldo_disponivel"))["v"] or 0

        por_tipo = list(
            contratos.filter(status="vigente")
            .values("tipo")
            .annotate(qtd=Count("id"), valor=Sum("valor_atual"))
            .order_by("-valor")
        )

        # Alertas: TI → 120 dias; outros → 90 dias
        alertas_ti = list(
            contratos.filter(
                status="vigente", tipo="solucao_ti",
                data_fim_vigencia__range=(hoje, d120),
            ).order_by("data_fim_vigencia")[:5]
        )
        alertas_outros = list(
            contratos.filter(
                status="vigente",
                data_fim_vigencia__range=(hoje, d90),
            ).exclude(tipo="solucao_ti").order_by("data_fim_vigencia")[:5]
        )

        recentes = list(contratos.order_by("-criado_em")[:8])

        # ── Contratos Comprasnet (importados) ─────────────────────────────
        if _tem_dados_externos:
            cc_qs = ContratoComprasnet.objects.all()
            total_comprasnet   = cc_qs.count()
            ativos_comprasnet  = cc_qs.filter(situacao="Ativo").count()
            inativos_comprasnet = cc_qs.filter(situacao="Inativo").count()
            valor_comprasnet   = cc_qs.filter(situacao="Ativo").aggregate(v=Sum("valor_global"))["v"] or 0
            cc_venc_30 = cc_qs.filter(
                situacao="Ativo", vigencia_fim__range=(hoje, d30)
            ).count()
            cc_venc_90 = cc_qs.filter(
                situacao="Ativo", vigencia_fim__range=(hoje, d90)
            ).count()
            comprasnet_recentes = list(
                cc_qs.filter(situacao="Ativo").order_by("-data_assinatura")[:8]
            )
            comprasnet_vencendo = list(
                cc_qs.filter(situacao="Ativo", vigencia_fim__gte=hoje)
                .order_by("vigencia_fim")[:5]
            )
            ultima_importacao_cc = cc_qs.order_by("-importado_em").values_list(
                "importado_em", flat=True
            ).first()

            # ── Contratos decorrentes de ARP (importados) ─────────────────
            ca_qs = ContratoARP.objects.select_related("arp")
            total_contratos_arp  = ca_qs.count()
            caronas_cedidas      = ca_qs.filter(is_carona=True).count()
            proprios_arp         = ca_qs.filter(is_carona=False).count()
            valor_contratos_arp  = ca_qs.aggregate(v=Sum("valor_total"))["v"] or 0
            ca_vigentes          = ca_qs.filter(data_fim_vigencia__gte=hoje).count()
            ca_venc_30           = ca_qs.filter(
                is_carona=False, data_fim_vigencia__range=(hoje, d30)
            ).count()
            contratos_arp_recentes = list(
                ca_qs.filter(is_carona=False).order_by("-data_assinatura")[:6]
            )
            caronas_recentes = list(
                ca_qs.filter(is_carona=True).order_by("-data_assinatura")[:6]
            )
            ultima_importacao_arp = ca_qs.order_by("-importado_em").values_list(
                "importado_em", flat=True
            ).first()

        else:
            total_comprasnet = ativos_comprasnet = inativos_comprasnet = 0
            valor_comprasnet = cc_venc_30 = cc_venc_90 = 0
            comprasnet_recentes = comprasnet_vencendo = []
            ultima_importacao_cc = None
            total_contratos_arp = caronas_cedidas = proprios_arp = 0
            valor_contratos_arp = ca_vigentes = ca_venc_30 = 0
            contratos_arp_recentes = caronas_recentes = []
            ultima_importacao_arp = None

        # ── Conciliação: contratos no Comprasnet mas não cadastrados localmente ──
        # Heurística por número de contrato
        numeros_locais = set(contratos.values_list("numero_contrato", flat=True))
        nao_cadastrados = 0
        if _tem_dados_externos:
            nao_cadastrados = ContratoComprasnet.objects.filter(
                situacao="Ativo"
            ).exclude(numero__in=numeros_locais).count()

        context = {
            "hoje": hoje,
            # locais
            "total_local": total_local,
            "vigentes_local": vigentes_local,
            "encerrados": encerrados,
            "rescindidos": rescindidos,
            "valor_local": valor_local,
            "saldo_disponivel": saldo_disponivel,
            "vencendo_30": vencendo_30,
            "vencendo_60": vencendo_60,
            "vencendo_90": vencendo_90,
            "vencendo_120": vencendo_120,
            "por_tipo": por_tipo,
            "alertas_ti": alertas_ti,
            "alertas_outros": alertas_outros,
            "recentes": recentes,
            # comprasnet
            "total_comprasnet": total_comprasnet,
            "ativos_comprasnet": ativos_comprasnet,
            "inativos_comprasnet": inativos_comprasnet,
            "valor_comprasnet": valor_comprasnet,
            "cc_venc_30": cc_venc_30,
            "cc_venc_90": cc_venc_90,
            "comprasnet_recentes": comprasnet_recentes,
            "comprasnet_vencendo": comprasnet_vencendo,
            "ultima_importacao_cc": ultima_importacao_cc,
            # contratos arp
            "total_contratos_arp": total_contratos_arp,
            "caronas_cedidas": caronas_cedidas,
            "proprios_arp": proprios_arp,
            "valor_contratos_arp": valor_contratos_arp,
            "ca_vigentes": ca_vigentes,
            "ca_venc_30": ca_venc_30,
            "contratos_arp_recentes": contratos_arp_recentes,
            "caronas_recentes": caronas_recentes,
            "ultima_importacao_arp": ultima_importacao_arp,
            # conciliação
            "nao_cadastrados": nao_cadastrados,
            "tem_dados_externos": _tem_dados_externos,
        }
        return render(request, self.template_name, context)
