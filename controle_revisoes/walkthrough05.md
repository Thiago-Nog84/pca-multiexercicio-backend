# Walkthrough: Refatoração Arquitetural, API REST e Organização do Swagger por App

A refatoração arquitetural do projeto **PCA Multiexercício (MPPI)** foi concluída com sucesso. O sistema foi integralmente convertido em uma **API REST corporativa** padronizada pelo Django REST Framework (DRF), com divisão estrita em camadas (Clean Django Architecture), integração assíncrona com **Celery/Redis**, documentação interativa **OpenAPI 3 / Swagger com separação estrita por aplicativo**, e remoção completa de artefatos do frontend legado.

---

## 1. O que foi realizado

### A. Separação dos Endpoints no Swagger por Aplicativo
Atendendo à solicitação, os endpoints no Swagger UI deixaram de ser agrupados sob o prefixo genérico `v1` e passaram a ser organizados individualmente por **aplicativo/domínio**:

- **Autenticação**: Emissão e refresh de tokens JWT (`/api/auth/token/`, `/api/auth/token/refresh/`)
- **PCA**: Gestão de Planos, DFDs (`cadastro_grupo`), Itens, Análises, Suspensões, Catálogo e Dashboards
- **Planejamento**: Documentos de Oficialização da Demanda (DODs), ETPs, Termos de Referência, Matrizes de Risco e Equipes TIC
- **Licitação**: Processos licitatórios, vínculos com ARPs/Contratos, métricas e sincronização PNCP
- **SRP**: Atas de Registro de Preços, Itens, Contratações Decorrentes, Adesões (Caronas) e Dashboards
- **Contratos**: Contratos administrativos, empenhos, conformidade e sincronização SIAFE
- **SIAFE**: Consultas orçamentárias/contábeis e sincronização de execução orçamentária
- **Core**: Órgãos, Unidades requisitantes, Notificações e consulta de status de Tarefas Celery

A categorização foi implementada via hook dedicado em `config/spectacular.py` e configurada em `SPECTACULAR_SETTINGS` no `config/settings.py`.

---

### B. Remoção de Todo o Frontend Legado
- **Templates Removidos:** Exclusão da pasta `templates/` (raiz) e dos diretórios `templates/` de todos os aplicativos (`apps/core`, `apps/pca`, `apps/planejamento`, `apps/licitacao`, `apps/srp`, `apps/contratos`, `apps/siafe`).
- **Arquivos Estáticos Removidos:** Exclusão de `static/` raiz e saneamento da configuração `STATICFILES_DIRS`.
- **Views de Template Descontinuadas:** Exclusão de `views_template.py`, `views_cadastro.py`, `views_analise.py`, `views_prazos.py`, `views_relatorios.py`, `views_suspensas.py`, `views_validacao.py`, `views_workflow.py` e context processors de template (`apps/core/context_processors.py`).

---

### C. Arquitetura em Camadas por Módulo (The Django Way)

Cada aplicação agora segue uma separação rigorosa de responsabilidades:

| Camada | Papel Arquitetural | Implementação nos Módulos |
| :--- | :--- | :--- |
| **`models.py`** | Definição estrutural do banco de dados, `TextChoices`, índices e constraints | Todas as apps |
| **`selectors.py`** | Consultas, filtros e agregações puras sem side-effects (otimizado contra N+1) | `pca`, `planejamento`, `licitacao`, `srp`, `contratos`, `siafe` |
| **`services/`** | Regras de negócio, transações atômicas (`@transaction.atomic`), lock pessimista e mutações | `pca.services`, `planejamento.services`, `licitacao.services`, `srp.services`, `contratos.services` |
| **`serializers.py`** | Validação declarativa de entrada e formatação JSON de saída | Todas as apps |
| **`views.py`** | Controladores finos (Thin ViewSets) delegando para Services/Selectors | Todas as apps |
| **`urls.py`** | Roteamento RESTful padronizado com `DefaultRouter` | Todas as apps sob `/api/v1/` |
| **`tasks.py`** | Processamento em segundo plano orquestrado pelo Celery | `contratos`, `licitacao`, `srp`, `siafe` |
| **`exceptions.py`** | Tratamento uniforme de exceções de domínio no DRF | `apps/core/exceptions.py` |

---

## 2. Validação e Testes Automatizados

### Verificação do Django (`manage.py check`)
```bash
System check identified no issues (0 silenced).
```

### Validação do OpenAPI Schema (`drf-spectacular`)
```bash
=== TAGS DO SWAGGER ===
  - Autenticação: 2 endpoints
  - Contratos: 17 endpoints
  - Core: 8 endpoints
  - Licitação: 9 endpoints
  - PCA: 32 endpoints
  - Planejamento: 40 endpoints
  - SIAFE: 37 endpoints
  - SRP: 37 endpoints
```

### Suíte de Testes Automatizados (`manage.py test`)
Todos os 76 testes automatizados foram executados e aprovados:
```bash
Ran 76 tests in 15.450s
OK
```

### Verificação do Servidor Local
Testada a resposta HTTP 200 no endpoint de documentação OpenAPI do servidor ativo em `http://127.0.0.1:8000/api/docs/`.
