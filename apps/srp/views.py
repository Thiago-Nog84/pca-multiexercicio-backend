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
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from .models import AtaRegistroPrecos, ItemARP


@method_decorator(login_required, name="dispatch")
class DashboardSRPView(View):
    """
    Dashboard principal do módulo SRP.
    Exibe estatísticas gerais e lista todas as ARPs do MPPI.
    """

    template_name = "srp/dashboard.html"

    def get(self, request):
        arps = (
            AtaRegistroPrecos.objects.select_related("orgao_gerenciador")
            .prefetch_related("itens")
            .order_by("-data_inicio_vigencia")
        )

        total_arps = arps.count()
        arps_vigentes = arps.filter(status="vigente").count()
        arps_encerradas = arps.filter(status__in=["encerrada", "cancelada"]).count()

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

        hoje = date.today()
        arps_lista = []
        for arp in arps:
            itens = arp.itens.all()
            valor_arp = sum(i.quantidade_registrada * i.valor_unitario for i in itens)
            dias_restantes = (arp.data_fim_vigencia - hoje).days if arp.data_fim_vigencia else None
            arps_lista.append(
                {
                    "arp": arp,
                    "total_itens": itens.count(),
                    "valor_total": valor_arp,
                    "importada": arp.importada_da_api,
                    "dias_restantes": dias_restantes,
                }
            )

        context = {
            "arps_lista": arps_lista,
            "total_arps": total_arps,
            "arps_vigentes": arps_vigentes,
            "arps_encerradas": arps_encerradas,
            "valor_total": valor_total,
            "total_itens": total_itens,
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

        context = {
            "arp": arp,
            "itens_detalhados": itens_detalhados,
            "valor_total_arp": valor_total_arp,
            "qtd_total_registrada": qtd_total_registrada,
            "qtd_total_contratada": qtd_total_contratada,
            "total_itens": len(itens_detalhados),
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
