"""Views Django Templates — Módulo Contratos."""

import json
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

        valor_local      = contratos.filter(status="vigente").aggregate(v=Sum("valor_atual"))["v"] or 0
        saldo_disponivel = contratos.filter(status="vigente").aggregate(v=Sum("saldo_disponivel"))["v"] or 0
        valor_empenhado  = contratos.filter(status="vigente").aggregate(v=Sum("valor_empenhado"))["v"] or 0
        pct_empenhado    = round(float(valor_empenhado) / float(valor_local) * 100, 1) if valor_local else 0
        com_execucao     = contratos.filter(valor_empenhado__gt=0).count()
        ultima_sync_siafe = (
            contratos.filter(ultima_atualizacao_siafe__isnull=False)
            .order_by("-ultima_atualizacao_siafe")
            .values_list("ultima_atualizacao_siafe", flat=True)
            .first()
        )

        # Top contratos por valor empenhado (para tabela de execução)
        top_empenhados = list(
            contratos.filter(valor_empenhado__gt=0)
            .order_by("-valor_empenhado")[:10]
        )

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

        # ── Prazo Transparência CNMP: dias até dia 10 do mês subsequente ──
        if hoje.month == 12:
            dia_10_prox = date(hoje.year + 1, 1, 10)
        else:
            dia_10_prox = date(hoje.year, hoje.month + 1, 10)
        dias_ate_transparencia = (dia_10_prox - hoje).days

        # ── Contratos vigentes sem empenho registrado ──────────────────────
        contratos_sem_empenho = contratos.filter(
            status="vigente", valor_empenhado=0
        ).count()

        # ── Dados para gráfico de rosca — distribuição por status ─────────
        suspensos = contratos.filter(status="suspenso").count()
        grafico_status = json.dumps({
            "labels": ["Vigente", "Encerrado", "Rescindido", "Suspenso"],
            "data": [vigentes_local, encerrados, rescindidos, suspensos],
            "cores": ["#198754", "#6c757d", "#dc3545", "#f59e0b"],
        })

        # ── Dados para gráfico de barras — Empenhado vs Saldo (top 10) ───
        grafico_execucao = json.dumps({
            "labels": [c.numero_contrato for c in top_empenhados],
            "empenhado": [float(c.valor_empenhado or 0) for c in top_empenhados],
            "saldo": [float(c.saldo_disponivel or 0) for c in top_empenhados],
        })

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
            # execução orçamentária SIAFE
            "valor_empenhado": valor_empenhado,
            "pct_empenhado": pct_empenhado,
            "com_execucao": com_execucao,
            "top_empenhados": top_empenhados,
            "ultima_sync_siafe": ultima_sync_siafe,
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
            # novos: transparência, empenho pendente, gráficos
            "dias_ate_transparencia": dias_ate_transparencia,
            "dia_10_prox": dia_10_prox,
            "contratos_sem_empenho": contratos_sem_empenho,
            "grafico_status": grafico_status,
            "grafico_execucao": grafico_execucao,
        }
        return render(request, self.template_name, context)
