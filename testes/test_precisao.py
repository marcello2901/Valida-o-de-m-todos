"""Testes do módulo de precisão (CLSI EP15).

Os valores esperados foram escolhidos para serem conferíveis à mão, com papel e
calculadora, por quem entende do ensaio mas não lê Python.
"""

import math

import pytest

from motor import precisao


class TestResumoReplicas:
    def test_estatistica_de_uma_serie(self):
        # Série: 10, 12, 14 → média 12; DP amostral = sqrt(((-2)²+0²+2²)/2) = 2
        resumo = precisao.resumo_replicas([10, 12, 14])

        assert resumo["n"] == 3
        assert resumo["media"] == 12
        assert resumo["desvio_padrao"] == pytest.approx(2.0)
        assert resumo["cv"] == pytest.approx(2 / 12 * 100)
        assert resumo["minimo"] == 10
        assert resumo["maximo"] == 14

    def test_replica_unica_nao_tem_dispersao(self):
        # Uma única medição não permite estimar dispersão. O resultado precisa
        # ser ausente, nunca zero: zero afirmaria precisão perfeita.
        resumo = precisao.resumo_replicas([100.0])

        assert resumo["n"] == 1
        assert resumo["media"] == 100.0
        assert resumo["desvio_padrao"] is None
        assert resumo["cv"] is None

    def test_serie_vazia(self):
        resumo = precisao.resumo_replicas([])

        assert resumo["n"] == 0
        assert resumo["media"] is None
        assert resumo["cv"] is None

    def test_descarta_valores_nao_numericos(self):
        # Célula vazia ou com texto na planilha não pode entrar no cálculo.
        resumo = precisao.resumo_replicas([10, "", 12, None, "erro", 14])

        assert resumo["n"] == 3
        assert resumo["media"] == 12

    def test_media_zero_torna_cv_indefinido(self):
        # CV é DP dividido pela média: com média zero ele não existe.
        resumo = precisao.resumo_replicas([-1, 0, 1])

        assert resumo["media"] == 0
        assert resumo["desvio_padrao"] == pytest.approx(1.0)
        assert resumo["cv"] is None


class TestComponentesPrecisao:
    def test_anova_com_valores_conferiveis_a_mao(self):
        # Corrida 1: 10 e 12 (média 11) | Corrida 2: 14 e 16 (média 15)
        # Média geral = 13
        # SQ entre  = 2×(11−13)² + 2×(15−13)² = 16 ; gl = 1 ; QM entre  = 16
        # SQ dentro = 1+1+1+1 = 4              ; gl = 2 ; QM dentro = 2
        # DP repetibilidade = raiz(2)
        # Variância entre corridas = (16 − 2) / 2 = 7
        # DP intermediária = raiz(2 + 7) = 3
        resultado = precisao.componentes_precisao([[10, 12], [14, 16]])

        assert resultado["n_corridas"] == 2
        assert resultado["n_total"] == 4
        assert resultado["media"] == pytest.approx(13.0)
        assert resultado["desvio_padrao_repetibilidade"] == pytest.approx(math.sqrt(2))
        assert resultado["desvio_padrao_intermediaria"] == pytest.approx(3.0)
        assert resultado["variancia_entre_corridas"] == pytest.approx(7.0)
        assert resultado["graus_liberdade_repetibilidade"] == 2

    def test_intermediaria_nunca_menor_que_repetibilidade(self):
        # Corridas com a mesma média: a variação entre corridas estimada sai
        # negativa e precisa ser truncada em zero. Sem esse tratamento o DP
        # intermediário sairia menor que o intra-ensaio, o que é impossível.
        resultado = precisao.componentes_precisao([[10, 12], [10, 12]])

        assert resultado["variancia_entre_corridas"] == 0.0
        assert resultado["desvio_padrao_intermediaria"] == pytest.approx(
            resultado["desvio_padrao_repetibilidade"]
        )

    def test_desenho_desbalanceado_e_aceito(self):
        # Corridas com número diferente de réplicas ainda produzem estimativa.
        resultado = precisao.componentes_precisao([[10, 12, 11], [14, 16]])

        assert resultado["n_corridas"] == 2
        assert resultado["n_total"] == 5
        assert resultado["desvio_padrao_repetibilidade"] is not None
        assert resultado["desvio_padrao_intermediaria"] is not None

    def test_uma_unica_corrida_nao_separa_as_fontes(self):
        # Com uma corrida só não há como distinguir variação intra de entre
        # corridas — o cálculo precisa recusar, não inventar.
        resultado = precisao.componentes_precisao([[10, 12, 14]])

        assert resultado["desvio_padrao_intermediaria"] is None
        assert resultado["observacao"] is not None

    def test_corridas_sem_replicas_nao_estimam_repetibilidade(self):
        # Uma medição por corrida não deixa graus de liberdade internos.
        resultado = precisao.componentes_precisao([[10], [14]])

        assert resultado["desvio_padrao_repetibilidade"] is None
        assert "réplicas" in resultado["observacao"]

    def test_cv_acompanha_os_desvios(self):
        resultado = precisao.componentes_precisao([[10, 12], [14, 16]])

        assert resultado["cv_repetibilidade"] == pytest.approx(math.sqrt(2) / 13 * 100)
        assert resultado["cv_intermediaria"] == pytest.approx(3.0 / 13 * 100)
