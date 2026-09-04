"""Executor de testes do projeto.

Os testes rodam com ``DEBUG`` desligado, e nesse modo o armazenamento de
estáticos do whitenoise exige o manifesto que só o ``collectstatic`` gera. Sem
ele, qualquer teste que renderize uma página com ``{% static %}`` quebra com
"Missing staticfiles manifest entry" — um erro que não tem nada a ver com o que
o teste está verificando.

A alternativa seria repetir ``@override_settings`` em cada classe de teste que
renderiza uma página, e lembrar de repetir na próxima. Isso já falhou uma vez
aqui: bastou um ``<script>`` novo numa tela para sete testes quebrarem. Trocar o
armazenamento uma vez, no executor, resolve para todos — inclusive os que ainda
não foram escritos.

O que se perde: os testes não conferem o manifesto. Isso é aceitável porque o
manifesto é assunto de implantação, não de aplicação — e o ``collectstatic``
está no roteiro de deploy, onde uma falha aparece antes de o site subir.
"""

from django.test.runner import DiscoverRunner
from django.test.utils import override_settings

ESTATICOS_SEM_MANIFESTO = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class Executor(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        self._estaticos = override_settings(STORAGES=ESTATICOS_SEM_MANIFESTO)
        self._estaticos.enable()
        super().setup_test_environment(**kwargs)

    def teardown_test_environment(self, **kwargs):
        super().teardown_test_environment(**kwargs)
        self._estaticos.disable()
