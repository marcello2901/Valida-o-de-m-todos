"""Gráficos do relatório de validação, gerados como SVG em Python puro.

Sem biblioteca de plotagem e sem JavaScript: o SVG sai pronto do servidor, entra
direto no HTML e no PDF, e fica idêntico nos dois. Um relatório de validação é
documento impresso antes de ser tela — se o gráfico depender de renderização no
navegador, o PDF assinado e a tela podem divergir, e é o PDF que vai para a
auditoria.

Decisões de codificação visual, e o porquê de cada uma:

- **Cor carrega identidade do dado, não decoração.** Só duas cores aparecem:
  amostra dentro do limite e amostra fora do limite. A paleta foi verificada com
  o validador de acessibilidade (ΔE 31,6 em visão normal, 23,8 sob simulação de
  daltonismo — bem acima dos pisos de 15 e 8).
- **Estar fora do limite nunca é indicado só pela cor.** O ponto fora muda de
  forma (losango) e é nomeado na legenda. Um leitor com deficiência de visão de
  cores, ou uma impressão em preto e branco, continuam legíveis.
- **Retas de referência são anotação, não série.** Identidade, regressão, viés e
  limites de concordância saem em tinta neutra, diferenciadas por padrão de
  traço e com rótulo escrito ao lado — nunca dependendo de cor para serem
  identificadas.
- **Paleta clara única, assumida.** O destino é papel. Um tema escuro que
  invertesse as cores produziria um PDF diferente da tela.
"""

from __future__ import annotations

import math
from typing import Sequence

# Dimensões e margens da área de desenho.
LARGURA = 680
ALTURA = 480
MARGEM_ESQUERDA = 74
MARGEM_DIREITA = 24
MARGEM_SUPERIOR = 52
MARGEM_INFERIOR = 104

# Paleta (superfície clara, validada).
SUPERFICIE = "#fcfcfb"
TINTA_PRIMARIA = "#0b0b0b"
TINTA_SECUNDARIA = "#52514e"
TINTA_SUAVE = "#898781"
GRADE = "#e1e0d9"
EIXO = "#c3c2b7"
DADO_DENTRO = "#2a78d6"
DADO_FORA = "#d03b3b"

FONTE = 'system-ui, -apple-system, "Segoe UI", sans-serif'
RAIO_MARCA = 4  # marcas de 8px de diâmetro


def _escapar(texto) -> str:
    """Escapa texto para XML — identificações de amostra vêm digitadas pelo usuário."""
    return (
        str(texto)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _formatar(valor: float | None, casas: int = 2) -> str:
    """Formata número no padrão brasileiro, com vírgula decimal."""
    if valor is None or not math.isfinite(valor):
        return "—"
    return f"{valor:,.{casas}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _passo_agradavel(intervalo: float, alvo: int = 5) -> float:
    """Escolhe um passo de escala que caia em números redondos."""
    if intervalo <= 0:
        return 1.0
    bruto = intervalo / max(alvo, 1)
    magnitude = 10 ** math.floor(math.log10(bruto))
    normalizado = bruto / magnitude
    if normalizado <= 1:
        passo = 1
    elif normalizado <= 2:
        passo = 2
    elif normalizado <= 5:
        passo = 5
    else:
        passo = 10
    return passo * magnitude


def _casas_decimais(passo: float) -> int:
    if passo >= 1:
        return 0
    return min(4, int(math.ceil(-math.log10(passo))))


class _Escala:
    """Converte valores dos dados em coordenadas de tela."""

    def __init__(self, minimo: float, maximo: float, pixel_inicio: float, pixel_fim: float, folga: float = 0.06):
        if minimo == maximo:
            minimo, maximo = minimo - 1, maximo + 1
        margem = (maximo - minimo) * folga
        self.minimo = minimo - margem
        self.maximo = maximo + margem
        self.pixel_inicio = pixel_inicio
        self.pixel_fim = pixel_fim

    def __call__(self, valor: float) -> float:
        proporcao = (valor - self.minimo) / (self.maximo - self.minimo)
        return self.pixel_inicio + proporcao * (self.pixel_fim - self.pixel_inicio)

    def marcas(self, alvo: int = 5) -> list[float]:
        passo = _passo_agradavel(self.maximo - self.minimo, alvo)
        primeira = math.ceil(self.minimo / passo) * passo
        marcas = []
        atual = primeira
        while atual <= self.maximo + passo * 1e-9:
            marcas.append(round(atual, 10))
            atual += passo
        return marcas


def _moldura(titulo: str, descricao: str, corpo: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {LARGURA} {ALTURA}" '
        f'width="100%" style="max-width:{LARGURA}px;font-family:{FONTE}" '
        f'role="img" aria-label="{_escapar(titulo)}">'
        f"<desc>{_escapar(descricao)}</desc>"
        f'<rect width="{LARGURA}" height="{ALTURA}" fill="{SUPERFICIE}"/>'
        f'<text x="{MARGEM_ESQUERDA}" y="30" font-size="15" font-weight="600" '
        f'fill="{TINTA_PRIMARIA}">{_escapar(titulo)}</text>'
        f"{corpo}</svg>"
    )


def _eixos(escala_x: _Escala, escala_y: _Escala, rotulo_x: str, rotulo_y: str) -> str:
    """Grade discreta, eixos em fio fino e rótulos em tinta suave."""
    topo = MARGEM_SUPERIOR
    base = ALTURA - MARGEM_INFERIOR
    esquerda = MARGEM_ESQUERDA
    direita = LARGURA - MARGEM_DIREITA

    partes = []

    marcas_y = escala_y.marcas()
    casas_y = _casas_decimais(_passo_agradavel(escala_y.maximo - escala_y.minimo))
    for marca in marcas_y:
        y = escala_y(marca)
        partes.append(
            f'<line x1="{esquerda}" y1="{y:.1f}" x2="{direita}" y2="{y:.1f}" '
            f'stroke="{GRADE}" stroke-width="1"/>'
        )
        partes.append(
            f'<text x="{esquerda - 10}" y="{y + 4:.1f}" font-size="11" text-anchor="end" '
            f'fill="{TINTA_SUAVE}">{_formatar(marca, casas_y)}</text>'
        )

    marcas_x = escala_x.marcas()
    casas_x = _casas_decimais(_passo_agradavel(escala_x.maximo - escala_x.minimo))
    for marca in marcas_x:
        x = escala_x(marca)
        partes.append(
            f'<line x1="{x:.1f}" y1="{topo}" x2="{x:.1f}" y2="{base}" '
            f'stroke="{GRADE}" stroke-width="1"/>'
        )
        partes.append(
            f'<text x="{x:.1f}" y="{base + 20}" font-size="11" text-anchor="middle" '
            f'fill="{TINTA_SUAVE}">{_formatar(marca, casas_x)}</text>'
        )

    partes.append(
        f'<line x1="{esquerda}" y1="{base}" x2="{direita}" y2="{base}" '
        f'stroke="{EIXO}" stroke-width="1"/>'
    )
    partes.append(
        f'<line x1="{esquerda}" y1="{topo}" x2="{esquerda}" y2="{base}" '
        f'stroke="{EIXO}" stroke-width="1"/>'
    )
    partes.append(
        f'<text x="{(esquerda + direita) / 2:.0f}" y="{base + 42}" font-size="12" '
        f'text-anchor="middle" fill="{TINTA_SECUNDARIA}">{_escapar(rotulo_x)}</text>'
    )
    partes.append(
        f'<text transform="translate(18,{(topo + base) / 2:.0f}) rotate(-90)" font-size="12" '
        f'text-anchor="middle" fill="{TINTA_SECUNDARIA}">{_escapar(rotulo_y)}</text>'
    )

    return "".join(partes)


def _marca(x: float, y: float, fora: bool, dica: str) -> str:
    """Ponto de dado. Fora do limite muda de FORMA além de cor."""
    cor = DADO_FORA if fora else DADO_DENTRO
    titulo = f"<title>{_escapar(dica)}</title>"
    if fora:
        # Losango: distinguível em preto e branco e sob daltonismo.
        d = RAIO_MARCA + 1.5
        pontos = f"{x:.1f},{y - d:.1f} {x + d:.1f},{y:.1f} {x:.1f},{y + d:.1f} {x - d:.1f},{y:.1f}"
        return (
            f'<polygon points="{pontos}" fill="{cor}" stroke="{SUPERFICIE}" '
            f'stroke-width="2">{titulo}</polygon>'
        )
    return (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{RAIO_MARCA}" fill="{cor}" '
        f'fill-opacity="0.85" stroke="{SUPERFICIE}" stroke-width="1.5">{titulo}</circle>'
    )


def _legenda(itens: Sequence[tuple[str, str]]) -> str:
    """Legenda no rodapé, quebrando em duas linhas quando não couber em uma.

    ``itens`` são pares (tipo, texto). Tipos: ``ponto``, ``losango``,
    ``linha_solida``, ``linha_tracejada``.

    A quebra existe porque a legenda cresce com o conteúdo do estudo: sem ela, o
    último item — que costuma ser justamente a reta de identidade — sai cortado
    na borda direita, e o leitor perde a referência mais importante do gráfico.
    """
    limite_direito = LARGURA - MARGEM_DIREITA
    linhas: list[list[tuple[str, str, float]]] = [[]]
    largura_atual = MARGEM_ESQUERDA

    for tipo, texto in itens:
        marca = 30 if tipo in ("linha_solida", "linha_tracejada") else 16
        # 5,9px por caractere aproxima a largura do texto em system-ui a 11px.
        largura_item = marca + len(texto) * 5.9 + 22
        if largura_atual + largura_item > limite_direito and linhas[-1]:
            linhas.append([])
            largura_atual = MARGEM_ESQUERDA
        linhas[-1].append((tipo, texto, largura_item))
        largura_atual += largura_item

    partes = []
    for indice_linha, linha in enumerate(linhas):
        y = ALTURA - 32 + indice_linha * 18
        x = MARGEM_ESQUERDA

        for tipo, texto, largura_item in linha:
            if tipo == "ponto":
                partes.append(
                    f'<circle cx="{x + 5}" cy="{y - 4}" r="{RAIO_MARCA}" fill="{DADO_DENTRO}"/>'
                )
            elif tipo == "losango":
                d = RAIO_MARCA + 1.5
                cx, cy = x + 5, y - 4
                pontos = f"{cx},{cy - d} {cx + d},{cy} {cx},{cy + d} {cx - d},{cy}"
                partes.append(f'<polygon points="{pontos}" fill="{DADO_FORA}"/>')
            elif tipo == "linha_solida":
                partes.append(
                    f'<line x1="{x}" y1="{y - 4}" x2="{x + 22}" y2="{y - 4}" '
                    f'stroke="{TINTA_PRIMARIA}" stroke-width="2"/>'
                )
            else:
                partes.append(
                    f'<line x1="{x}" y1="{y - 4}" x2="{x + 22}" y2="{y - 4}" '
                    f'stroke="{TINTA_SUAVE}" stroke-width="2" stroke-dasharray="6 4"/>'
                )

            deslocamento = 30 if tipo in ("linha_solida", "linha_tracejada") else 16
            partes.append(
                f'<text x="{x + deslocamento}" y="{y}" font-size="11" '
                f'fill="{TINTA_SECUNDARIA}">{_escapar(texto)}</text>'
            )
            x += largura_item

    return "".join(partes)


def grafico_regressao(
    comparacao: Sequence[float],
    teste: Sequence[float],
    inclinacao: float | None = None,
    intercepto: float | None = None,
    fora_do_limite: Sequence[bool] | None = None,
    identificacoes: Sequence[str] | None = None,
    unidade: str = "",
    titulo: str = "Comparação de métodos — regressão",
) -> str:
    """Dispersão dos pares com a reta de regressão e a reta de identidade.

    A reta de identidade (y = x) é o que o olho precisa para julgar concordância:
    sem ela, qualquer nuvem de pontos parece alinhada. A distância entre as duas
    retas é o erro sistemático, e é isso que o gráfico existe para mostrar.
    """
    pares = [
        (float(x), float(y))
        for x, y in zip(comparacao, teste)
        if _e_numero(x) and _e_numero(y)
    ]
    if not pares:
        return _moldura(titulo, "Sem dados suficientes para o gráfico.", _sem_dados())

    marcados = list(fora_do_limite) if fora_do_limite else []
    nomes = list(identificacoes) if identificacoes else []

    valores = [v for par in pares for v in par]
    minimo, maximo = min(valores), max(valores)

    escala_x = _Escala(minimo, maximo, MARGEM_ESQUERDA, LARGURA - MARGEM_DIREITA)
    escala_y = _Escala(minimo, maximo, ALTURA - MARGEM_INFERIOR, MARGEM_SUPERIOR)

    corpo = [
        _eixos(
            escala_x,
            escala_y,
            f"Sistema de comparação{f' ({unidade})' if unidade else ''}",
            f"Sistema em teste{f' ({unidade})' if unidade else ''}",
        )
    ]

    # Reta de identidade: tracejada, tinta suave, rotulada.
    corpo.append(
        f'<line x1="{escala_x(escala_x.minimo):.1f}" y1="{escala_y(escala_x.minimo):.1f}" '
        f'x2="{escala_x(escala_x.maximo):.1f}" y2="{escala_y(escala_x.maximo):.1f}" '
        f'stroke="{TINTA_SUAVE}" stroke-width="2" stroke-dasharray="6 4"/>'
    )

    if inclinacao is not None and intercepto is not None:
        x0, x1 = escala_x.minimo, escala_x.maximo
        corpo.append(
            f'<line x1="{escala_x(x0):.1f}" y1="{escala_y(inclinacao * x0 + intercepto):.1f}" '
            f'x2="{escala_x(x1):.1f}" y2="{escala_y(inclinacao * x1 + intercepto):.1f}" '
            f'stroke="{TINTA_PRIMARIA}" stroke-width="2"/>'
        )
        sinal = "+" if intercepto >= 0 else "−"
        equacao = f"y = {_formatar(inclinacao, 4)}x {sinal} {_formatar(abs(intercepto), 4)}"
        corpo.append(
            f'<text x="{LARGURA - MARGEM_DIREITA}" y="30" font-size="12" '
            f'text-anchor="end" fill="{TINTA_SECUNDARIA}">{_escapar(equacao)}</text>'
        )

    for indice, (x, y) in enumerate(pares):
        fora = bool(marcados[indice]) if indice < len(marcados) else False
        nome = nomes[indice] if indice < len(nomes) else f"amostra {indice + 1}"
        dica = f"{nome}: comparação {_formatar(x, 3)} · teste {_formatar(y, 3)} {unidade}".strip()
        corpo.append(_marca(escala_x(x), escala_y(y), fora, dica))

    itens = [("ponto", "amostra dentro do limite")]
    if any(marcados):
        itens.append(("losango", "fora do erro total permitido"))
    if inclinacao is not None:
        itens.append(("linha_solida", "regressão"))
    itens.append(("linha_tracejada", "identidade (y = x)"))
    corpo.append(_legenda(itens))

    descricao = (
        f"Dispersão de {len(pares)} amostras medidas nos dois sistemas, com reta de "
        "regressão e reta de identidade para comparação visual do erro sistemático."
    )
    return _moldura(titulo, descricao, "".join(corpo))


def grafico_bland_altman(
    comparacao: Sequence[float],
    teste: Sequence[float],
    vies: float | None = None,
    limite_inferior: float | None = None,
    limite_superior: float | None = None,
    fora_do_limite: Sequence[bool] | None = None,
    identificacoes: Sequence[str] | None = None,
    unidade: str = "",
    titulo: str = "Comparação de métodos — diferenças (Bland-Altman)",
) -> str:
    """Diferença entre os métodos contra o valor do método de comparação.

    Mostra o que a dispersão esconde: se o erro é constante ao longo da faixa ou
    se cresce com a concentração. Uma nuvem em funil indica erro proporcional,
    que nenhum viés médio revela.
    """
    pares = [
        (float(x), float(y))
        for x, y in zip(comparacao, teste)
        if _e_numero(x) and _e_numero(y)
    ]
    if not pares:
        return _moldura(titulo, "Sem dados suficientes para o gráfico.", _sem_dados())

    marcados = list(fora_do_limite) if fora_do_limite else []
    nomes = list(identificacoes) if identificacoes else []

    diferencas = [y - x for x, y in pares]
    referencias = [v for v in (vies, limite_inferior, limite_superior) if v is not None]

    escala_x = _Escala(
        min(x for x, _ in pares), max(x for x, _ in pares), MARGEM_ESQUERDA, LARGURA - MARGEM_DIREITA
    )
    escala_y = _Escala(
        min(diferencas + referencias + [0.0]),
        max(diferencas + referencias + [0.0]),
        ALTURA - MARGEM_INFERIOR,
        MARGEM_SUPERIOR,
    )

    corpo = [
        _eixos(
            escala_x,
            escala_y,
            f"Sistema de comparação{f' ({unidade})' if unidade else ''}",
            f"Diferença (teste − comparação){f' ({unidade})' if unidade else ''}",
        )
    ]

    # As retas de referência dividem a mesma lista, para que rótulos próximos
    # sejam deslocados em vez de escritos um por cima do outro.
    rotulos: list[float] = []
    if vies is not None:
        corpo.append(
            _linha_referencia(
                escala_x, escala_y, vies, f"viés {_formatar(vies, 3)}",
                tracejada=False, rotulos_usados=rotulos,
            )
        )
    if limite_superior is not None:
        corpo.append(
            _linha_referencia(
                escala_x, escala_y, limite_superior,
                f"+1,96 DP {_formatar(limite_superior, 3)}", rotulos_usados=rotulos,
            )
        )
    if limite_inferior is not None:
        corpo.append(
            _linha_referencia(
                escala_x, escala_y, limite_inferior,
                f"−1,96 DP {_formatar(limite_inferior, 3)}", rotulos_usados=rotulos,
            )
        )
    # A linha do zero entra por último e sem rótulo: ela é referência de leitura,
    # não um resultado, e disputar rótulo com o viés só atrapalharia.
    corpo.append(
        f'<line x1="{MARGEM_ESQUERDA}" y1="{escala_y(0.0):.1f}" '
        f'x2="{LARGURA - MARGEM_DIREITA}" y2="{escala_y(0.0):.1f}" '
        f'stroke="{EIXO}" stroke-width="1"/>'
    )

    for indice, ((x, y), diferenca) in enumerate(zip(pares, diferencas)):
        fora = bool(marcados[indice]) if indice < len(marcados) else False
        nome = nomes[indice] if indice < len(nomes) else f"amostra {indice + 1}"
        dica = f"{nome}: diferença {_formatar(diferenca, 3)} {unidade}".strip()
        corpo.append(_marca(escala_x(x), escala_y(diferenca), fora, dica))

    itens = [("ponto", "amostra dentro do limite")]
    if any(marcados):
        itens.append(("losango", "fora do erro total permitido"))
    itens.append(("linha_solida", "viés médio"))
    itens.append(("linha_tracejada", "limites de concordância"))
    corpo.append(_legenda(itens))

    descricao = (
        f"Diferenças entre os dois sistemas em {len(pares)} amostras, com viés médio e "
        "limites de concordância de 95%."
    )
    return _moldura(titulo, descricao, "".join(corpo))


def grafico_levey_jennings(
    valores: Sequence[float],
    media: float | None = None,
    desvio_padrao: float | None = None,
    unidade: str = "",
    titulo: str = "Precisão — carta de Levey-Jennings",
) -> str:
    """Réplicas na ordem de medição, com a média e as faixas de ±1, ±2 e ±3 DP.

    A ordem importa: uma tendência crescente ao longo das réplicas indica deriva
    do sistema, que o CV sozinho não distingue de dispersão aleatória.
    """
    dados = [float(v) for v in valores if _e_numero(v)]
    if not dados:
        return _moldura(titulo, "Sem dados suficientes para o gráfico.", _sem_dados())

    if media is None:
        media = sum(dados) / len(dados)
    if desvio_padrao is None and len(dados) >= 2:
        desvio_padrao = math.sqrt(sum((v - media) ** 2 for v in dados) / (len(dados) - 1))

    faixas = []
    if desvio_padrao:
        for multiplo in (1, 2, 3):
            faixas.extend([media - multiplo * desvio_padrao, media + multiplo * desvio_padrao])

    escala_x = _Escala(1, len(dados), MARGEM_ESQUERDA, LARGURA - MARGEM_DIREITA, folga=0.04)
    escala_y = _Escala(
        min(dados + faixas), max(dados + faixas), ALTURA - MARGEM_INFERIOR, MARGEM_SUPERIOR
    )

    corpo = [_eixos(escala_x, escala_y, "Réplica (ordem de medição)", f"Valor{f' ({unidade})' if unidade else ''}")]

    rotulos: list[float] = []
    corpo.append(
        _linha_referencia(
            escala_x, escala_y, media, f"média {_formatar(media, 3)}",
            tracejada=False, rotulos_usados=rotulos, ancorar_esquerda=True,
        )
    )
    if desvio_padrao:
        for multiplo in (1, 2, 3):
            for sinal in (1, -1):
                valor = media + sinal * multiplo * desvio_padrao
                rotulo = f"{'+' if sinal > 0 else '−'}{multiplo} DP"
                corpo.append(
                    _linha_referencia(
                        escala_x, escala_y, valor, rotulo,
                        rotulos_usados=rotulos, ancorar_esquerda=True,
                    )
                )

    pontos = " ".join(
        f"{escala_x(indice + 1):.1f},{escala_y(valor):.1f}" for indice, valor in enumerate(dados)
    )
    corpo.append(
        f'<polyline points="{pontos}" fill="none" stroke="{DADO_DENTRO}" stroke-width="2" '
        f'stroke-opacity="0.55"/>'
    )

    for indice, valor in enumerate(dados):
        fora = bool(desvio_padrao) and abs(valor - media) > 2 * desvio_padrao
        dica = f"Réplica {indice + 1}: {_formatar(valor, 3)} {unidade}".strip()
        corpo.append(_marca(escala_x(indice + 1), escala_y(valor), fora, dica))

    itens = [("ponto", "réplica dentro de ±2 DP")]
    if any(bool(desvio_padrao) and abs(v - media) > 2 * desvio_padrao for v in dados):
        itens.append(("losango", "além de ±2 DP"))
    itens.append(("linha_solida", "média"))
    itens.append(("linha_tracejada", "faixas de desvio padrão"))
    corpo.append(_legenda(itens))

    descricao = f"Sequência de {len(dados)} réplicas com média e faixas de desvio padrão."
    return _moldura(titulo, descricao, "".join(corpo))


def _linha_referencia(
    escala_x: _Escala,
    escala_y: _Escala,
    valor: float,
    rotulo: str,
    tracejada: bool = True,
    suave: bool = False,
    rotulos_usados: list[float] | None = None,
    ancorar_esquerda: bool = False,
) -> str:
    """Reta horizontal de anotação, com rótulo escrito — nunca só cor.

    ``rotulos_usados`` acumula as alturas já rotuladas. Quando duas retas caem
    perto uma da outra — o que acontece sempre que o viés é próximo de zero — o
    segundo rótulo é deslocado para a esquerda em vez de ser escrito por cima do
    primeiro, que deixaria os dois ilegíveis.
    """
    y = escala_y(valor)
    x0 = MARGEM_ESQUERDA
    x1 = LARGURA - MARGEM_DIREITA
    cor = TINTA_SUAVE if (tracejada or suave) else TINTA_PRIMARIA
    traco = ' stroke-dasharray="6 4"' if tracejada else ""
    largura = 1 if suave else 2

    if rotulos_usados is None:
        rotulos_usados = []

    colide = any(abs(y - usado) < 12 for usado in rotulos_usados)
    rotulos_usados.append(y)

    if ancorar_esquerda:
        # Séries que avançam da esquerda para a direita terminam encostadas na
        # borda direita; ali o rótulo cairia em cima do último ponto medido.
        x_rotulo, ancora = (x0 + 6, "start")
    else:
        x_rotulo, ancora = ((x0 + (x1 - x0) * 0.42) if colide else (x1 - 4), "end")

    return (
        f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{cor}" '
        f'stroke-width="{largura}"{traco}/>'
        f'<text x="{x_rotulo:.1f}" y="{y - 5:.1f}" font-size="10" text-anchor="{ancora}" '
        f'fill="{TINTA_SUAVE}">{_escapar(rotulo)}</text>'
    )


def _sem_dados() -> str:
    return (
        f'<text x="{LARGURA / 2}" y="{ALTURA / 2}" font-size="13" text-anchor="middle" '
        f'fill="{TINTA_SUAVE}">Sem dados suficientes para gerar o gráfico.</text>'
    )


def _e_numero(valor) -> bool:
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError):
        return False
