"""Cria ou atualiza a conta de administração a partir de variáveis de ambiente.

Existe por uma limitação concreta da hospedagem: no plano gratuito do Render não
há terminal no servidor, então não dá para rodar ``createsuperuser`` e responder
às perguntas. Sem isto, o site sobe sem nenhum usuário e ninguém consegue entrar.

O ``createsuperuser --noinput`` do próprio Django faria quase isso, mas falha
quando o usuário já existe — e o comando roda a cada implantação. Este aqui é
seguro de repetir: cria na primeira vez, atualiza a senha nas seguintes.

Não faz nada quando as variáveis não estão definidas, para não atrapalhar quem
roda na própria máquina.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

MINIMO_DA_SENHA = 10


class Command(BaseCommand):
    help = "Cria a conta de administração a partir de ADMIN_USUARIO e ADMIN_SENHA."

    def handle(self, *args, **opcoes):
        usuario = os.environ.get("ADMIN_USUARIO", "").strip()
        senha = os.environ.get("ADMIN_SENHA", "")
        email = os.environ.get("ADMIN_EMAIL", "").strip()

        if not usuario or not senha:
            self.stdout.write(
                "ADMIN_USUARIO/ADMIN_SENHA não definidos — nenhuma conta criada."
            )
            return

        # Uma senha curta aqui é a senha do administrador de um sistema exposto
        # na internet. Recusar é melhor do que criar e torcer.
        if len(senha) < MINIMO_DA_SENHA:
            raise CommandError(
                f"ADMIN_SENHA precisa de pelo menos {MINIMO_DA_SENHA} caracteres."
            )

        Usuario = get_user_model()
        conta, criada = Usuario.objects.get_or_create(
            username=usuario,
            defaults={"email": email, "is_staff": True, "is_superuser": True},
        )
        conta.is_staff = True
        conta.is_superuser = True
        if email:
            conta.email = email
        conta.set_password(senha)
        conta.save()

        verbo = "criada" if criada else "atualizada"
        self.stdout.write(self.style.SUCCESS(f"Conta de administração {verbo}: {usuario}"))
