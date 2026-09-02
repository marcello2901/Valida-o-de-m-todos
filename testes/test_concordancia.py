"""Testes das medidas de concordância entre os dois métodos."""

import pytest

from motor import concordancia as conc
from motor import especificacoes as espec


class TestLin:
    def test_concordancia_perfeita(self):
        # Métodos idênticos: os pontos caem exatamente sobre y = x.
        resultado = conc.lin([10, 20, 30, 40], [10, 20, 30, 40])

        assert resultado["ccc"] == pytest.approx(1.0)
        assert resultado["componente_precisao"] == pytest.approx(1.0)
        assert resultado["componente_acuracia"] == pytest.approx(1.0)
        assert resultado["classificacao"] == "quase perfeita (ρc ≥ 0,99)"

    def test_correlacao_perfeita_com_vies_nao_e_concordancia(self):
        # O caso que o coeficiente r esconde: correlação 1,000 e mesmo assim
        # discordância, porque um método lê sempre 10 unidades acima do outro.
        resultado = conc.lin([10, 20, 30, 40], [20, 30, 40, 50])

        assert resultado["componente_precisao"] == pytest.approx(1.0)
        assert resultado["ccc"] < 0.75
        assert resultado["componente_acuracia"] < 0.75

    def test_valor_conferivel_a_mao(self):
        # x = 10,20,30,40 (média 25, variância populacional 125)
        # y = x + 10      (média 35, mesma variância, covariância 125)
        # ρc = 2×125 / (125 + 125 + (25−35)²) = 250 / 350 = 0,714285…
        resultado = conc.lin([10, 20, 30, 40], [20, 30, 40, 50])

        assert resultado["ccc"] == pytest.approx(250 / 350)

    def test_decomposicao_multiplica_de_volta(self):
        # Propriedade do coeficiente: ρc = ρ × Cb.
        resultado = conc.lin([10, 22, 31, 39, 52], [11, 21, 33, 40, 50])

        produto = resultado["componente_precisao"] * resultado["componente_acuracia"]
        assert produto == pytest.approx(resultado["ccc"])

    def test_dados_insuficientes(self):
        assert conc.lin([10], [10])["ccc"] is None
        assert conc.lin([], [])["ccc"] is None


class TestErroSistematicoMedio:
    def test_erro_absoluto_e_percentual(self):
        # Diferenças: +2 em todas as amostras.
        resultado = conc.erro_sistematico_medio([10, 20, 30, 40], [12, 22, 32, 42])

        assert resultado["erro_medio"] == pytest.approx(2.0)
        assert resultado["erro_medio_pct_ponderado"] == pytest.approx(2 / 25 * 100)

    def test_as_duas_formas_de_media_divergem(self):
        # Um desvio fixo de 1 unidade pesa 10% na amostra de concentração 10 e
        # 1% na de concentração 100. A média das porcentagens enxerga isso; a
        # razão das médias dilui no valor alto.
        resultado = conc.erro_sistematico_medio([10, 100], [11, 101])

        assert resultado["erro_medio_pct"] == pytest.approx((10 + 1) / 2)
        assert resultado["erro_medio_pct_ponderado"] == pytest.approx(1 / 55 * 100)
        assert resultado["erro_medio_pct"] > resultado["erro_medio_pct_ponderado"]

    def test_sem_dados(self):
        assert conc.erro_sistematico_medio([], [])["erro_medio"] is None


class TestConcordanciaAnalitica:
    def limite_12_pct(self):
        return espec.LimiteQualidade(valor_pct=12.0, referencia_pct="ControlLab")

    def test_conta_amostras_dentro_do_erro_total(self):
        # Erros: +10%, +5%, +20%, 0% → três dentro do limite de 12%, uma fora.
        resultado = conc.concordancia_analitica(
            comparacao=[100, 100, 100, 100],
            teste=[110, 105, 120, 100],
            limite=self.limite_12_pct(),
        )

        assert resultado["avaliadas"] == 4
        assert resultado["dentro_do_limite"] == 3
        assert resultado["fora_do_limite"] == 1
        assert resultado["concordancia_pct"] == pytest.approx(75.0)

    def test_identifica_a_amostra_discordante(self):
        resultado = conc.concordancia_analitica(
            comparacao=[100, 100],
            teste=[105, 130],
            limite=self.limite_12_pct(),
            identificacoes=["AM-001", "AM-002"],
        )

        assert len(resultado["discordantes"]) == 1
        assert resultado["discordantes"][0]["identificacao"] == "AM-002"
        assert resultado["discordantes"][0]["erro_pct"] == pytest.approx(30.0)

    def test_media_boa_pode_esconder_amostras_fora(self):
        # Erro sistemático médio zero e ainda assim metade das amostras fora do
        # limite — é justamente o que a média não mostra.
        comparacao = [100, 100, 100, 100]
        teste = [130, 70, 100, 100]

        media = conc.erro_sistematico_medio(comparacao, teste)
        analitica = conc.concordancia_analitica(comparacao, teste, self.limite_12_pct())

        assert media["erro_medio"] == pytest.approx(0.0)
        assert analitica["concordancia_pct"] == pytest.approx(50.0)

    def test_limite_absoluto_vale_em_concentracao_baixa(self):
        # Limite: 12% em geral, mas ±0,2 para resultados ≤ 1,0.
        # Amostra de 0,5 com erro de 0,15 (30%) fica DENTRO pelo critério absoluto.
        limite = espec.LimiteQualidade(
            valor_pct=12.0,
            referencia_pct="ControlLab",
            limiar_absoluto=1.0,
            valor_absoluto=0.2,
            referencia_absoluto="Estado da arte",
        )

        resultado = conc.concordancia_analitica([0.5], [0.65], limite)

        assert resultado["dentro_do_limite"] == 1
        assert resultado["concordancia_pct"] == pytest.approx(100.0)


class TestConcordanciaClinica:
    def test_conta_amostras_com_a_mesma_interpretacao(self):
        # Intervalo de referência 0,8–1,8.
        # AM-1: 1,0 → 1,1  ambos dentro          (concorda)
        # AM-2: 1,7 → 1,9  dentro → acima        (discorda)
        # AM-3: 0,5 → 0,6  ambos abaixo          (concorda)
        # AM-4: 2,5 → 2,4  ambos acima           (concorda)
        resultado = conc.concordancia_clinica(
            comparacao=[1.0, 1.7, 0.5, 2.5],
            teste=[1.1, 1.9, 0.6, 2.4],
            limite_inferior=0.8,
            limite_superior=1.8,
            identificacoes=["AM-1", "AM-2", "AM-3", "AM-4"],
        )

        assert resultado["concordantes"] == 3
        assert resultado["discordantes"] == 1
        assert resultado["concordancia_pct"] == pytest.approx(75.0)

    def test_mostra_a_direcao_da_reclassificacao(self):
        # O relatório precisa dizer se o método novo cria falsos alterados ou
        # deixa de sinalizar alteração real.
        resultado = conc.concordancia_clinica(
            comparacao=[1.7],
            teste=[1.9],
            limite_inferior=0.8,
            limite_superior=1.8,
            identificacoes=["AM-2"],
        )

        reclassificacao = resultado["reclassificacoes"][0]
        assert reclassificacao["classificacao_comparacao"] == conc.DENTRO
        assert reclassificacao["classificacao_teste"] == conc.ACIMA

    def test_diferenca_pequena_no_ponto_de_corte_muda_a_conduta(self):
        # A mesma diferença absoluta de 0,1: irrelevante no meio da faixa,
        # decisiva sobre o limite superior. É o argumento de existir esta medida.
        meio = conc.concordancia_clinica([1.2], [1.3], 0.8, 1.8)
        borda = conc.concordancia_clinica([1.75], [1.85], 0.8, 1.8)

        assert meio["concordancia_pct"] == pytest.approx(100.0)
        assert borda["concordancia_pct"] == pytest.approx(0.0)

    def test_sem_intervalo_de_referencia_nao_calcula(self):
        # Sem o intervalo informado a medida não existe — e o motivo é dito.
        resultado = conc.concordancia_clinica([1.0], [1.1], None, None)

        assert resultado["concordancia_pct"] is None
        assert "intervalo de referência" in resultado["observacao"]

    def test_intervalo_invertido_e_recusado(self):
        resultado = conc.concordancia_clinica([1.0], [1.1], 1.8, 0.8)

        assert resultado["concordancia_pct"] is None
        assert "inválido" in resultado["observacao"]
