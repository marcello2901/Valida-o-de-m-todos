"""Motor de cálculo da validação de métodos analíticos.

Pacote puro em Python padrão, sem dependências externas e sem qualquer código de
interface. Toda a estatística que decide a aprovação de um método vive aqui,
separada da aplicação web de propósito: assim ela pode ser testada, auditada e
conferida número a número sem subir servidor nenhum.

Módulos:

- ``estatistica``      — utilitários de base (média, DP, mediana, Wilson)
- ``precisao``         — CLSI EP15: repetibilidade e precisão intermediária
- ``comparabilidade``  — CLSI EP09: Deming, Passing-Bablok, Bland-Altman, bias
- ``qualitativo``      — CLSI EP12: tabela 2×2, sensibilidade, kappa
- ``especificacoes``   — EQA: limites de aceitação e suas referências
- ``concordancia``     — Lin, concordância analítica e concordância clínica
- ``veredito``         — decisão de aprovação, reprovação ou indeterminação
- ``graficos``         — gráficos SVG do relatório, gerados sem dependências
"""

from . import (  # noqa: F401
    comparabilidade,
    concordancia,
    especificacoes,
    estatistica,
    graficos,
    precisao,
    qualitativo,
    veredito,
)

__all__ = [
    "estatistica",
    "precisao",
    "comparabilidade",
    "concordancia",
    "qualitativo",
    "especificacoes",
    "veredito",
    "graficos",
]
