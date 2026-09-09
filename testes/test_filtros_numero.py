"""O sinal do número é informação, não decoração.

Um bias sem sinal não diz o que importa — se o método lê acima ou abaixo do
grupo de pares — e dois traços diferentes na mesma linha fazem o leitor
desconfiar do documento.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from estudos.templatetags.numeros import MENOS, com_menos, sinalizado  # noqa: E402


class TestSinalizado:
    def test_positivo_ganha_mais(self):
        assert sinalizado(1.4839) == "+1,48"

    def test_negativo_ganha_o_menos_tipografico(self):
        assert sinalizado(-1.4839) == f"{MENOS}1,48"
        assert "-" not in sinalizado(-1.4839)

    def test_zero_nao_ganha_sinal(self):
        # "+0,00" afirma um sentido que o número não tem.
        assert sinalizado(0) == "0,00"

    def test_valor_que_arredonda_para_zero_tambem_nao_ganha_sinal(self):
        assert sinalizado(-0.001) == "0,00"

    def test_casas_configuraveis(self):
        assert sinalizado(-1.23456, 4) == f"{MENOS}1,2346"

    def test_sem_valor_devolve_travessao(self):
        assert sinalizado(None) == "—"
        assert sinalizado("") == "—"


class TestComMenos:
    def test_troca_o_hifen_pelo_menos(self):
        assert com_menos(-0.009) == f"{MENOS}0,0090"

    def test_positivo_fica_como_esta(self):
        assert com_menos(0.601) == "0,6010"

    def test_sem_valor_devolve_travessao(self):
        assert com_menos(None) == "—"
