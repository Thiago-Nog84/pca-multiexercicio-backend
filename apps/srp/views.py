"""
Views do módulo SRP — Dashboard de Atas de Registro de Preços

Acesso: requer login (session auth via admin Django).
Rotas:
    /srp/                   → DashboardSRPView
    /srp/arp/<pk>/          → ARPDetalheView
    /srp/importar/          → ImportarARPView
"""

import io
from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from .models import AtaRegistroPrecos, ContratoARP, ItemARP


@method_decorator(login_required, name="dispatch")
class DashboardSRPView(View):
    """
    Dashboard principal do módulo SRP.
    Exibe estatísticas gerais e lista todas as ARPs do MPPI.
    """

    template_name = "srp/dashboard.html"

    def get(self, request):
        hoje = date.today()
        arps = (
            AtaRegistroPrecos.objects.select_related("orgao_gerenciador")
            .prefetch_related("itens")
            .order_by("-data_inicio_vigencia")
        )

        total_arps = arps.count()
        # Conta vigentes pela data real, não pelo campo armazenado
        arps_vigentes = arps.filter(data_fim_vigencia__gte=hoje).exclude(status__in=["cancelada", "suspensa"]).count()
        arps_encerradas = arps.filter(
            Q(data_fim_vigencia__lt=hoje) | Q(status__in=["encerrada", "cancelada"])
        ).count()

        valor_total = (
            ItemARP.objects.aggregate(
                total=Sum(
                    ExpressionWrapper(
                        F("quantidade_registrada") * F("valor_unitario"),
                        output_field=DecimalField(max_digits=18, decimal_places=2),
                    )
                )
            )["total"]
            or 0
        )

        total_itens = ItemARP.objects.count()

        arps_lista = []
        for arp in arps:
            itens = arp.itens.all()
            valor_arp = sum(i.quantidade_registrada * i.valor_unitario for i in itens)
            dias_restantes = (arp.data_fim_vigencia - hoje).days if arp.data_fim_vigencia else None

            # Deriva status efetivo das datas (ignora valor armazenado para exibição)
            if arp.status in ("cancelada", "suspensa"):
                status_efetivo = arp.status
            elif arp.data_fim_vigencia and arp.data_fim_vigencia < hoje:
                status_efetivo = "encerrada"
            else:
                status_efetivo = "vigente"

            arps_lista.append(
                {
                    "arp": arp,
                    "total_itens": itens.count(),
                    "valor_total": valor_arp,
                    "importada": arp.importada_da_api,
                    "dias_restantes": dias_restantes,
                    "status_efetivo": status_efetivo,
                }
            )

        anos_disponiveis = sorted(
            {a["arp"].data_inicio_vigencia.year for a in arps_lista if a["arp"].data_inicio_vigencia},
            reverse=True,
        )

        context = {
            "arps_lista": arps_lista,
            "total_arps": total_arps,
            "arps_vigentes": arps_vigentes,
            "arps_encerradas": arps_encerradas,
            "valor_total": valor_total,
            "total_itens": total_itens,
            "anos_disponiveis": anos_disponiveis,
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class ARPDetalheView(View):
    """
    Detalhe de uma ARP: itens com saldos e vínculos PCA.
    """

    template_name = "srp/arp_detalhe.html"

    def get(self, request, pk):
        arp = get_object_or_404(
            AtaRegistroPrecos.objects.select_related("orgao_gerenciador", "criado_por"),
            pk=pk,
        )

        itens = (
            ItemARP.objects.filter(arp=arp)
            .prefetch_related("vinculos_pca__item_pca__dfd__unidade")
            .order_by("numero_lote", "numero_item")
        )

        itens_detalhados = []
        for item in itens:
            vinculos = item.vinculos_pca.select_related(
                "item_pca__dfd__unidade", "criado_por"
            ).all()

            itens_detalhados.append(
                {
                    "item": item,
                    "valor_total": item.quantidade_registrada * item.valor_unitario,
                    "comprometida_pca": item.quantidade_comprometida_pca,
                    "disponivel_eventual": item.quantidade_disponivel_eventual,
                    "disponivel": item.quantidade_disponivel,
                    "vinculos": vinculos,
                    "carona_bloqueada": (
                        item.maximo_adesao_api is not None
                        and item.maximo_adesao_api == 0
                    ),
                }
            )

        valor_total_arp = sum(d["valor_total"] for d in itens_detalhados)
        qtd_total_registrada = sum(i.quantidade_registrada for i in itens)
        qtd_total_contratada = sum(i.quantidade_contratada for i in itens)

        # Agrupa itens por lote para exibição no template.
        # Itens sem lote ficam num grupo com numero_lote="" (exibidos individualmente).
        # A ordem preserva a ordenação original (numero_lote, numero_item).
        lotes_agrupados = []
        lote_atual = None
        for det in itens_detalhados:
            nl = det["item"].numero_lote or ""
            if lote_atual is None or lote_atual["numero_lote"] != nl:
                lote_atual = {
                    "numero_lote": nl,
                    "tem_lote": bool(nl),
                    "itens": [],
                    "valor_total_lote": 0,
                    "qtd_registrada_lote": 0,
                    "qtd_contratada_lote": 0,
                }
                lotes_agrupados.append(lote_atual)
            lote_atual["itens"].append(det)
            lote_atual["valor_total_lote"] += det["valor_total"]
            lote_atual["qtd_registrada_lote"] += det["item"].quantidade_registrada
            lote_atual["qtd_contratada_lote"] += det["item"].quantidade_contratada

        # Contratos decorrentes desta ARP (com itens pré-carregados)
        contratos = (
            ContratoARP.objects.filter(arp=arp)
            .prefetch_related("itens__item_arp")
            .order_by("-data_assinatura", "uasg_contratante")
        )
        total_valor_contratos = sum(c.valor_total for c in contratos)

        context = {
            "arp": arp,
            "itens_detalhados": itens_detalhados,
            "lotes_agrupados": lotes_agrupados,
            "valor_total_arp": valor_total_arp,
            "qtd_total_registrada": qtd_total_registrada,
            "qtd_total_contratada": qtd_total_contratada,
            "total_itens": len(itens_detalhados),
            "total_lotes": sum(1 for l in lotes_agrupados if l["tem_lote"]),
            "contratos": contratos,
            "total_valor_contratos": total_valor_contratos,
            "total_contratos": contratos.count(),
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class ImportarARPView(View):
    """
    Formulário para importar uma ARP via API Compras.gov.br.
    """

    template_name = "srp/importar_arp.html"

    def get(self, request):
        return render(request, self.template_name, {"uasg_padrao": "926092"})

    def post(self, request):
        uasg = request.POST.get("uasg", "926092").strip()
        ano_inicio = request.POST.get("ano_inicio", "2026").strip()
        atualizar = request.POST.get("atualizar") == "on"

        saida = io.StringIO()
        erro_cmd = None
        try:
            call_command(
                "importar_arp_compras_gov",
                uasg=uasg,
                ano_inicio=int(ano_inicio) if ano_inicio.isdigit() else 2026,
                atualizar=atualizar,
                stdout=saida,
                stderr=saida,
                no_color=True,
            )
        except Exception as exc:
            erro_cmd = str(exc)

        log = saida.getvalue()

        context = {
            "uasg_padrao": uasg,
            "ano_inicio": ano_inicio,
            "log": log,
            "erro_cmd": erro_cmd,
            "sucesso": erro_cmd is None,
        }
        return render(request, self.template_name, context)
