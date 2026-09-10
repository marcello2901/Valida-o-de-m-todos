"""Testes dos gráficos SVG do motor.

O módulo de gráficos passou a existir sem teste nenhum, o que se sustentou
enquanto ele só desenhava. Com a faixa em destaque ele passou a ter regra —
quem entra na conta, quem esmaece, o que a legenda promete — e regra sem teste
é regra que se perde na próxima mudança.
"""

from motor import graficos

class TestFaixaDestacadaNaRegressao:
    """O gráfico do recorte mostra a nuvem inteira, com a faixa em destaque.

    Mostrar só os pontos da faixa esconderia justamente o que motivou o
    recorte: a amostra distante que estava puxando a reta.
    """

    def _pares(self):
        x = [10.0, 20.0, 30.0, 40.0, 200.0]
        y = [10.5, 20.4, 30.6, 40.2, 201.0]
        return x, y

    def test_a_faixa_aparece_como_destaque_e_nao_como_corte(self):
        x, y = self._pares()

        svg = graficos.grafico_regressao(x, y, 1.0, 0.3, faixa=(10.0, 40.0))

        # Os cinco pontos continuam desenhados; quatro dentro, um esmaecido.
        assert svg.count("<circle") >= 5
        assert "fora da faixa examinada" in svg

    def test_a_legenda_do_ponto_fora_da_faixa_nao_usa_a_cor_do_incluido(self):
        x, y = self._pares()

        svg = graficos.grafico_regressao(x, y, 1.0, 0.3, faixa=(10.0, 40.0))

        posicao = svg.index("amostra fora da faixa examinada")
        anterior = svg[:posicao]
        assert 'fill-opacity="0.35"' in anterior

    def test_sem_faixa_o_grafico_nao_muda(self):
        x, y = self._pares()

        svg = graficos.grafico_regressao(x, y, 1.0, 0.3)

        assert "fora da faixa examinada" not in svg
        assert "data-selecionavel" not in svg

    def test_a_escala_so_sai_quando_a_tela_pede(self):
        x, y = self._pares()

        semente = graficos.grafico_regressao(x, y, 1.0, 0.3)
        tela = graficos.grafico_regressao(x, y, 1.0, 0.3, selecionavel=True)

        assert "data-x-minimo" not in semente
        assert 'data-selecionavel="regressao"' in tela
        assert "data-pixel-inicio" in tela
