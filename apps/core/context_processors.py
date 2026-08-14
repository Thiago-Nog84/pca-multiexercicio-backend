"""
Context processors globais do sistema.
"""

from .models import Notificacao, NotificacaoLida


def notificacoes(request):
    """
    Disponibiliza em todo template:
      - notificacoes_nao_lidas_qtd: contador para o sino do topbar
      - notificacoes_recentes: até 5 não lidas, para o dropdown
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"notificacoes_nao_lidas_qtd": 0, "notificacoes_recentes": []}

    lidas_ids = NotificacaoLida.objects.filter(usuario=user).values_list(
        "notificacao_id", flat=True
    )
    nao_lidas = Notificacao.visiveis_para(user).exclude(id__in=lidas_ids)

    return {
        "notificacoes_nao_lidas_qtd": nao_lidas.count(),
        "notificacoes_recentes": list(nao_lidas[:5]),
    }
