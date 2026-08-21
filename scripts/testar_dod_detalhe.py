"""
Teste da tela de detalhe do DOD (read-only ao final: o DOD criado e apagado).

Cria um DOD de verdade com itens reais do backlog via a propria tela de
criacao (POST), segue o redirect e verifica se a tela de detalhe renderiza
com os dados certos. No fim remove o DOD para nao sujar o banco.

Rodar com:
    .\.venv\Scripts\python.exe manage.py shell -c "import runpy; runpy.run_path('scripts/testar_dod_detalhe.py')"
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client

# Rodando via `manage.py shell` (fora do test runner) o Django nao injeta
# "testserver" em ALLOWED_HOSTS sozinho, e todo request do Client volta 400.
# Ajuste so em memoria — settings.py nao e tocado.
if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

from apps.pca.models import ItemPCA, PlanoContratacaoAnual
from apps.planejamento.models import DocumentoOficializacaoDemanda

pca = PlanoContratacaoAnual.objects.get(exercicio=2026)
usuario = User.objects.get(id=1)

# Pega 3 itens aprovados da mesma unidade, incluindo um parcial se houver,
# para exercitar a coluna "de X" e o badge de parcial na tela.

def acompanhantes(item):
    """
    Itens que podem entrar no MESMO DOD que `item`: mesma unidade
    requisitante e mesma unidade orcamentaria. A trava de fonte unica entrou
    em 2026-08-18 (um DOD declara uma so fonte de recurso, e a UO do DOD e
    derivada dos itens - ver _validar_uo_unica em views_dod.py); antes disso
    bastava "mesma unidade", e o teste pegava 3 itens quaisquer.
    """
    return list(
        ItemPCA.objects.filter(
            dfd__pca=pca,
            dfd__unidade=item.dfd.unidade,
            unidade_orcamentaria=item.unidade_orcamentaria,
            status_aprovacao__in=["aprovada_integral", "aprovada_parcial"],
        ).exclude(pk=item.pk)[:2]
    )


# Entre os parciais, prefere um que tenha companheiros na mesma fonte - senao
# o DOD sai com 1 item so e o teste perde a comparacao entre varios itens.
parciais = list(
    ItemPCA.objects.filter(dfd__pca=pca, status_aprovacao="aprovada_parcial")
    .select_related("dfd__unidade")
)
assert parciais, "nenhum item aprovado parcialmente no PCA 2026"
parcial = max(parciais, key=lambda i: len(acompanhantes(i)))
unidade = parcial.dfd.unidade
itens = acompanhantes(parcial) + [parcial]
print(f"unidade: {unidade.sigla} | itens: {[i.codigo_pca for i in itens]}")

client = Client()
client.force_login(usuario)

resp = client.post("/planejamento/dods/novo/", {
    "pca_id": pca.pk,
    "unidade_id": unidade.pk,
    "identificador": "TESTE — apagar",
    "numero_sei": "19.21.0001.0000000/2026-99",
    "objeto": "DOD de teste automatizado da tela de detalhe.",
    # unidade_orcamentaria NAO vai mais no POST: e derivada dos itens.
    "natureza_objeto": "fornecimento",
    "grau_prioridade": "medio",
    "necessidade_contratacao": "Verificar a renderizacao da secao de fundamentacao.",
    "motivacao_justificativa": "Segunda secao preenchida, para conferir o loop de campos_texto.",
    "itens": [str(i.pk) for i in itens],
})
print("POST criacao ->", resp.status_code, resp.headers.get("Location"))
assert resp.status_code == 302, resp.status_code

dod = DocumentoOficializacaoDemanda.objects.order_by("-pk").first()
assert resp.headers["Location"] == f"/planejamento/dods/{dod.pk}/", resp.headers["Location"]
print(f"DOD criado: #{dod.pk} com {dod.itens.count()} itens, "
      f"valor total R$ {dod.valor_total_estimado}")

try:
    detalhe = client.get(f"/planejamento/dods/{dod.pk}/")
    print("GET detalhe ->", detalhe.status_code)
    assert detalhe.status_code == 200, detalhe.status_code
    html = detalhe.content.decode()

    esperado = [
        "TESTE — apagar",
        "19.21.0001.0000000/2026-99",
        unidade.sigla,
        "Necessidade da contratação",
        "Segunda secao preenchida",
        "Instrução do processo",
        "Depende do ETP",
        "Itens do PCA neste DOD",
    ]
    for trecho in esperado:
        assert trecho in html, f"FALTOU no HTML: {trecho!r}"
    for item in itens:
        assert item.codigo_pca in html, f"item ausente: {item.codigo_pca}"

    # o item parcial deve aparecer marcado como tal
    assert "parcial" in html.lower(), "badge de parcial nao apareceu"

    # a tela nao pode quebrar quando nao ha ETP: Matriz e TR mostram a
    # dependencia em vez de oferecer um link que nao levaria a lugar nenhum
    assert html.count("Depende do ETP") == 2, html.count("Depende do ETP")

    print("OK: todos os trechos esperados estao no HTML")

    # checklist tambem precisa renderizar com o DOD novo e linkar pra ele
    chk = client.get(f"/planejamento/checklist/?pca_id={pca.pk}")
    print("GET checklist ->", chk.status_code)
    assert chk.status_code == 200
    assert f'href="/planejamento/dods/{dod.pk}/"' in chk.content.decode(), "checklist nao linka o DOD"
    print("OK: checklist linka a tela de detalhe")
finally:
    pk = dod.pk
    dod.delete()
    print(f"DOD #{pk} apagado. DODs restantes:", DocumentoOficializacaoDemanda.objects.count())
