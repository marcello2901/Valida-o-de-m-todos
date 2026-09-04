#!/usr/bin/env bash
# Roteiro de construção da implantação. O Render executa este arquivo a cada
# envio para a branch configurada.
#
# "set -o errexit" existe para que um erro pare a construção. Sem ele, uma
# migração que falha seguiria para o próximo passo e o site subiria com o banco
# desatualizado — a pior combinação possível: no ar e errado.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

# Reúne CSS e JavaScript num diretório só. O whitenoise serve a partir dele, e
# sem este passo o painel administrativo sobe sem estilo nenhum.
python manage.py collectstatic --no-input

# Ajusta o banco à versão atual do código.
python manage.py migrate --no-input

# Cria a conta de administração a partir das variáveis de ambiente. Sem isso o
# site sobe sem usuário nenhum, e no plano gratuito não há terminal no servidor
# para criar um depois.
python manage.py criar_admin
