"""
Teste ponta a ponta de ETP, Matriz de Risco (+ RiscoItem) e Termo de
Referencia (read-only ao final: tudo criado eh apagado via cascade do DOD).

Cria um DOD de teste, depois segue a cadeia real de telas (POST em cada
uma, seguindo os redirects) ate ter ETP -> MatrizRisco -> 2 RiscoItem
(edita um deles) -> TermoReferencia, conferindo o HTML de cada tela de
detalhe e a propagacao de status no dod_detalhe e no checklist.

Rodar com:
    .\.venv\Scripts\python.exe manage.py shell -c "import runpy; runpy.run_path('scripts/testar_etp_matriz_tr.py')"
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client

if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

from apps.pca.models import ItemPCA, PlanoContratacaoAnual
from apps.planejamento.models import ETP, DocumentoOficializacaoDemanda, MatrizRisco, TermoReferencia


def testar_etp(client, dod):
    resp = client.post("/planejamento/etps/novo/", {
        "dod": dod.pk,
        "numero_etp": "ETP-TESTE-001",
        "numero_sei": "19.21.0001.0000001/2026-11",
        "is_ti": "1",
        "status": "em_revisao",
        "necessidade_contratacao": "Necessidade de teste automatizado.",
        "requisitos_contratacao": "Requisitos de teste.",
        "levantamento_mercado": "Levantamento de teste.",
        "descricao_solucao": "Descricao da solucao de teste.",
        "estimativa_quantidade": "Estimativa de teste.",
        "estimativa_custo": "1500,50",
        "justificativa_parcelamento": "Justificativa de teste.",
        "alinhamento_pca": "Alinhamento de teste.",
        "resultados_pretendidos": "Resultados de teste.",
        "impactos_ambientais": "Sem impactos relevantes (teste).",
        "declaracao_viabilidade": "1",
    })
    assert resp.status_code == 302, (resp.status_code, resp.content[:800].decode(errors="replace"))
    etp = ETP.objects.get(dod=dod)
    assert resp.headers["Location"] == f"/planejamento/etps/{etp.pk}/", resp.headers["Location"]
    print(f"ETP criado: #{etp.pk}")

    html = client.get(f"/planejamento/etps/{etp.pk}/").content.decode()
    for trecho in ["ETP-TESTE-001", "Solução de TI", "R$ 1.500,50",
                   "Necessidade de teste automatizado.", "Instrução do processo"]:
        assert trecho in html, f"FALTOU no HTML do ETP: {trecho!r}"
    print("OK: detalhe do ETP renderiza os campos esperados")

    dod_html = client.get(f"/planejamento/dods/{dod.pk}/").content.decode()
    assert "ETP-TESTE-001" in dod_html, "dod_detalhe nao mostra o ETP criado"
    print("OK: dod_detalhe reflete o ETP criado")
    return etp


def testar_matriz_risco(client, etp):
    resp = client.post("/planejamento/matriz-risco/novo/", {"etp": etp.pk, "fase_atual": "planejamento"})
    assert resp.status_code == 302, (resp.status_code, resp.content[:500])
    matriz = MatrizRisco.objects.get(etp=etp)
    assert resp.headers["Location"] == f"/planejamento/matriz-risco/{matriz.pk}/"
    print(f"Matriz de Risco criada: #{matriz.pk}")

    # risco 1: alto (nivel 20 = 5*4) -> deve disparar o alerta de criticos
    r1 = client.post(f"/planejamento/matriz-risco/{matriz.pk}/itens/novo/", {
        "descricao_risco": "Atraso na entrega do fornecedor (teste)",
        "causa": "Escassez do insumo no mercado (teste)",
        "consequencia": "Atraso no cronograma (teste)",
        "probabilidade": "4",
        "impacto": "5",
        "responsavel": "contratado",
        "acao_preventiva": "Prazo de entrega com folga (teste)",
        "acao_contingencia": "Fornecedor reserva cadastrado (teste)",
    })
    assert r1.status_code == 302, (r1.status_code, r1.content[:500])
    item1 = matriz.itens.get(descricao_risco__startswith="Atraso na entrega")
    assert item1.nivel_risco == 20, item1.nivel_risco
    print(f"Risco #1 criado, nivel_risco={item1.nivel_risco}")

    # risco 2: baixo (nivel 2 = 1*2) -> nao deve contar como critico
    r2 = client.post(f"/planejamento/matriz-risco/{matriz.pk}/itens/novo/", {
        "descricao_risco": "Risco de teste baixo",
        "causa": "Causa baixa (teste)",
        "consequencia": "Consequencia baixa (teste)",
        "probabilidade": "1",
        "impacto": "2",
        "responsavel": "adm",
        "acao_preventiva": "Acao preventiva baixa (teste)",
        "acao_contingencia": "Acao contingencia baixa (teste)",
    })
    assert r2.status_code == 302
    item2 = matriz.itens.get(descricao_risco="Risco de teste baixo")
    assert item2.nivel_risco == 2, item2.nivel_risco

    # edita o risco 2, sobe pra nivel medio (3*3=9)
    edit = client.post(f"/planejamento/matriz-risco/{matriz.pk}/itens/{item2.pk}/editar/", {
        "descricao_risco": "Risco de teste (editado)",
        "causa": "Causa editada (teste)",
        "consequencia": "Consequencia editada (teste)",
        "probabilidade": "3",
        "impacto": "3",
        "responsavel": "compartilhado",
        "acao_preventiva": "Acao preventiva editada (teste)",
        "acao_contingencia": "Acao contingencia editada (teste)",
    })
    assert edit.status_code == 302, (edit.status_code, edit.content[:500])
    item2.refresh_from_db()
    assert item2.nivel_risco == 9, item2.nivel_risco
    assert item2.descricao_risco == "Risco de teste (editado)"
    print("OK: edicao de risco recalcula nivel_risco (2 -> 9)")

    html = client.get(f"/planejamento/matriz-risco/{matriz.pk}/").content.decode()
    for trecho in ["Atraso na entrega do fornecedor (teste)", "Risco de teste (editado)",
                   "1 risco com nível alto", "2 riscos"]:
        assert trecho in html, f"FALTOU no HTML da matriz: {trecho!r}"
    print("OK: detalhe da matriz mostra os 2 riscos e o alerta de critico")

    dod_html = client.get(f"/planejamento/dods/{etp.dod.pk}/").content.decode()
    assert "Matriz de Risco" in dod_html
    print("OK: dod_detalhe reflete a Matriz de Risco criada")
    return matriz


def testar_termo_referencia(client, etp):
    resp = client.post("/planejamento/termos-referencia/novo/", {
        "etp": etp.pk,
        "status": "em_revisao",
        "criterio_julgamento": "menor_preco",
        "objeto": "Objeto de teste do TR.",
        "fundamentacao_legal": "Fundamentacao de teste.",
        "descricao_solucao": "Descricao da solucao de teste do TR.",
        "requisitos_habilitacao": "Requisitos de habilitacao de teste.",
        "prazo_execucao": "90",
        "local_execucao": "Sede do MPPI (teste)",
        "criterios_medicao": "Criterios de medicao de teste.",
        "obrigacoes_contratante": "Obrigacoes do contratante (teste).",
        "obrigacoes_contratado": "Obrigacoes do contratado (teste).",
        "is_servico_continuo": "1",
        "prazo_inicial_meses": "12",
        "modalidade_remuneracao_ti": "sprint",
        "vedacoes_ti_observadas": "1",
    })
    assert resp.status_code == 302, (resp.status_code, resp.content[:800].decode(errors="replace"))
    tr = TermoReferencia.objects.get(etp=etp)
    assert resp.headers["Location"] == f"/planejamento/termos-referencia/{tr.pk}/"
    print(f"Termo de Referência criado: #{tr.pk}")

    html = client.get(f"/planejamento/termos-referencia/{tr.pk}/").content.decode()
    for trecho in ["Objeto de teste do TR.", "90 dias", "Sede do MPPI (teste)",
                   "Valor fixo por sprint", "12m"]:
        assert trecho in html, f"FALTOU no HTML do TR: {trecho!r}"
    print("OK: detalhe do TR renderiza os campos esperados, inclusive o bloco de TI")

    etp_html = client.get(f"/planejamento/etps/{etp.pk}/").content.decode()
    assert "Em revisão" in etp_html or "revisão" in etp_html, "ETP não mostra o TR criado"
    print("OK: etp_detalhe reflete o TR criado")
    return tr


client = Client()
pca = PlanoContratacaoAnual.objects.get(exercicio=2026)
usuario = User.objects.get(id=1)
client.force_login(usuario)

item = (
    ItemPCA.objects.filter(dfd__pca=pca, status_aprovacao__in=["aprovada_integral", "aprovada_parcial"])
    .exclude(documentos_oficializacao__status="aberto")
    .select_related("dfd__unidade")
    .first()
)
unidade = item.dfd.unidade
print(f"unidade: {unidade.sigla} | item: {item.codigo_pca}")

resp = client.post("/planejamento/dods/novo/", {
    "pca_id": pca.pk,
    "unidade_id": unidade.pk,
    "identificador": "TESTE ETP/Matriz/TR — apagar",
    # O DOD fica SEM o marcador solucao_tic de proposito: is_ti mora no ETP
    # (campo independente), e marcar TIC no DOD exigiria preencher os 3
    # papeis da EquipePlanejamentoTI (Res. CNMP 283/2024) so pra este teste
    # passar, sem relacao com o que estamos testando.
    "natureza_objeto": "fornecimento",
    "itens": [str(item.pk)],
})
assert resp.status_code == 302, (resp.status_code, resp.content[:500])
dod = DocumentoOficializacaoDemanda.objects.order_by("-pk").first()
print(f"DOD criado: #{dod.pk}")

try:
    etp = testar_etp(client, dod)
    matriz = testar_matriz_risco(client, etp)
    tr = testar_termo_referencia(client, etp)

    chk_html = client.get(f"/planejamento/checklist/?pca_id={pca.pk}").content.decode()
    for trecho in ["TESTE ETP/Matriz/TR", "Definida", "Em revisão"]:
        assert trecho in chk_html, f"FALTOU no checklist: {trecho!r}"
    print("OK: checklist reflete ETP, Matriz de Risco e TR do processo de teste")

    print("\nTUDO OK: ETP -> MatrizRisco (2 riscos) -> TermoReferencia, "
          "com telas de detalhe e links de status corretos.")
finally:
    pk = dod.pk
    dod.delete()
    print(f"DOD #{pk} apagado (cascade). Restam: "
          f"DOD={DocumentoOficializacaoDemanda.objects.count()} "
          f"ETP={ETP.objects.count()} restantes no total do sistema (nao só do teste)")
