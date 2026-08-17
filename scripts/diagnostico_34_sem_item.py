"""
Diagnostico READ-ONLY das demandas do PDF homologado que seguem sem item.

Motivo: a passada anterior de cruzamento so comparava candidatos DENTRO do
mesmo setor. Se a unidade cadastrou a demanda sob outra unidade requisitante,
o item existente passaria despercebido. Aqui o cruzamento e feito contra todos
os itens pendentes do exercicio 2026, por valor unitario exato e por
similaridade de texto sem acento.

Nao altera nada no banco. Rodar com:
    .\.venv\Scripts\python.exe manage.py shell -c "import runpy; runpy.run_path('scripts/diagnostico_34_sem_item.py')"
"""

import csv
import difflib
import unicodedata
from decimal import Decimal

from apps.pca.models import ItemPCA

# Codigos ja investigados a fundo e encaminhados (aba "Decidir" da planilha).
DECIDIR = {"C5CC", "6F6F", "2FE7", "7SMD"}
LIMITE_TEXTO = 0.60


def sem_acento(texto):
    return (
        unicodedata.normalize("NFKD", texto or "")
        .encode("ascii", "ignore")
        .decode()
        .lower()
        .strip()
    )


with open("pdf_pca2026_demandas.csv", encoding="utf-8") as f:
    demandas_pdf = list(csv.DictReader(f))

with open("itens_para_aprovar_final.csv", encoding="utf-8") as f:
    resolvidos = {linha["cod_pca_pdf"] for linha in csv.DictReader(f)}

pendentes = list(
    ItemPCA.objects.filter(dfd__pca__exercicio=2026, status_aprovacao="pendente")
    .select_related("dfd__unidade")
)

alvos = [
    d for d in demandas_pdf
    if d["cod_pca_pdf"] not in resolvidos and d["cod_pca_pdf"] not in DECIDIR
]

print(f"demandas no PDF: {len(demandas_pdf)}")
print(f"ja resolvidas:   {len(resolvidos)}")
print(f"itens 2026 ainda pendentes: {len(pendentes)}")
print(f"alvos a investigar: {len(alvos)}\n")

cache = [(p, sem_acento(p.descricao)) for p in pendentes]
achados = 0

for d in alvos:
    cod = d["cod_pca_pdf"]
    alvo_txt = sem_acento(d["objeto"])
    vu_pdf = Decimal(d["valor_unit"])

    por_valor = [p for p in pendentes if p.valor_unitario_estimado == vu_pdf]

    melhor, melhor_score = None, 0.0
    for item, texto in cache:
        score = difflib.SequenceMatcher(None, alvo_txt, texto).ratio()
        if score > melhor_score:
            melhor, melhor_score = item, score

    if not por_valor and melhor_score < LIMITE_TEXTO:
        continue

    achados += 1
    print("=" * 72)
    print(f"{cod} [{d['setor']}] qtd={d['qtd']} unit={vu_pdf}")
    print(f"  PDF     : {alvo_txt[:96]}")
    for p in por_valor:
        sigla = p.dfd.unidade.sigla if p.dfd and p.dfd.unidade else "?"
        print(f"  = VALOR : id={p.pk} {p.codigo_pca} [{sigla}] qtd={p.quantidade_estimada} :: {sem_acento(p.descricao)[:78]}")
    if melhor_score >= LIMITE_TEXTO:
        sigla = melhor.dfd.unidade.sigla if melhor.dfd and melhor.dfd.unidade else "?"
        print(f"  ~ TEXTO {melhor_score:.2f}: id={melhor.pk} {melhor.codigo_pca} [{sigla}] unit={melhor.valor_unitario_estimado} :: {sem_acento(melhor.descricao)[:78]}")

print("\n" + "=" * 72)
print(f"alvos com algum candidato: {achados} de {len(alvos)}")
