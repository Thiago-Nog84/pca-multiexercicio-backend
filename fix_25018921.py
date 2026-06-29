"""
Script pontual: corrige o contrato 25018921
  - tipo: solucao_ti → fornecimento
  - unidade_requisitante: → CAA
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.contratos.models import Contrato
from apps.core.models import UnidadeRequisitante

try:
    c = Contrato.objects.get(numero_contrato="25018921")
except Contrato.DoesNotExist:
    print("ERRO: contrato 25018921 não encontrado.")
    raise SystemExit(1)

try:
    caa = UnidadeRequisitante.objects.get(sigla="CAA")
except UnidadeRequisitante.DoesNotExist:
    print("ERRO: UnidadeRequisitante CAA não encontrada.")
    raise SystemExit(1)

print(f"Antes → tipo={c.tipo!r}, ur={c.unidade_requisitante}")
c.tipo = "fornecimento"
c.unidade_requisitante = caa
c.save()
print(f"Depois → tipo={c.tipo!r}, ur={c.unidade_requisitante}")
print("OK — contrato 25018921 corrigido.")
