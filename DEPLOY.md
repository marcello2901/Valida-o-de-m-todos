# Colocar o sistema no ar

Guia para publicar o programa num endereço da internet, no plano **gratuito** do
Render. Não precisa saber administrar servidor: você clica, cola duas coisas e
espera.

---

## Antes de começar, o que o plano gratuito é e o que não é

Vale ler estes três parágrafos antes de investir tempo, porque eles decidem se
esta é a hospedagem certa para você.

**O site dorme.** Depois de 15 minutos sem ninguém acessar, o Render desliga o
programa. A visita seguinte demora perto de um minuto para responder, enquanto
ele acorda. Para você abrir e testar, tudo bem. Para mostrar a um cliente numa
reunião, abra o site cinco minutos antes.

**O banco de dados gratuito é apagado depois de 30 dias.** Não é aviso de letra
miúda: o Render remove mesmo. Quando isso acontecer, você cria outro banco e o
sistema volta vazio. **Nada que você lançar aqui pode ser insubstituível.**

**Este endereço não deve receber dado real de paciente.** Identificação de
amostra em estudo de validação é dado pessoal sensível pela LGPD. Um ambiente
que dorme, some em 30 dias e fica em servidor nos Estados Unidos não é o lugar
disso. Quando um laboratório de verdade for usar, conversamos sobre hospedagem
paga e, de preferência, em território nacional.

---

## Passo 1 — Aceitar as mudanças no GitHub

O código de implantação está na branch de desenvolvimento. Primeiro faça o
merge, como você já fez antes:

1. Abra <https://github.com/marcello2901/Valida-o-de-m-todos>
2. Se houver um pull request aberto, aceite (**Merge pull request**).
3. Se não houver, clique em **Compare & pull request** na faixa amarela, ou vá
   em **Pull requests → New pull request**, escolha a branch
   `claude/instalar-como-skill-leleth` e aceite.

Confira que o arquivo `render.yaml` aparece na raiz do repositório. É ele que o
Render lê.

## Passo 2 — Criar a conta no Render

1. Abra <https://render.com> e clique em **Get Started**.
2. Entre com **GitHub** — assim ele já enxerga seus repositórios.
3. Autorize o acesso quando o GitHub perguntar.

Não pede cartão para o plano gratuito.

## Passo 3 — Apontar para o repositório

1. No painel do Render, clique em **New +** → **Blueprint**.
2. Escolha o repositório `Valida-o-de-m-todos`.
3. O Render lê o `render.yaml` e mostra o que vai criar: um site
   (`validacao-metodos`) e um banco (`validacao-banco`).
4. Ele vai pedir **uma** informação, porque é a única que não pode ficar
   guardada no repositório:

   | Campo | O que colocar |
   |---|---|
   | `ADMIN_SENHA` | A senha que **você** vai usar para entrar. Mínimo 10 caracteres. Anote antes de continuar. |

5. Clique em **Apply**.

## Passo 4 — Esperar

A primeira construção leva de 3 a 6 minutos. Você vê o registro passando na
tela. Ao final aparece **Live** e um endereço parecido com:

```
https://validacao-metodos.onrender.com
```

Se aparecer **Failed**, role o registro até a primeira linha em vermelho e me
mande — o erro está sempre lá, não no fim.

## Passo 5 — Entrar

Abra o endereço. Você cai na tela de entrada:

- **Usuário:** `admin`
- **Senha:** a que você definiu no passo 3

O sistema estará **vazio**: nenhum laboratório, nenhum analito, nenhuma
validação. É o esperado — dados de demonstração não sobem por padrão.

---

## Se quiser o sistema com os dados de demonstração

Serve para mostrar o programa funcionando sem precisar cadastrar nada.

1. No painel do Render, abra o serviço `validacao-metodos`.
2. **Environment** → encontre `PERMITIR_DADOS_EXEMPLO` → mude de `0` para `1`.
3. **Manual Deploy** → **Deploy latest commit**.

Depois disso o site sobe com o laboratório de demonstração, quatro validações e
o usuário `analista.demo` (senha `demonstracao-2026`).

**Essa senha é pública — está escrita aqui e no código.** Enquanto essa variável
estiver em `1`, qualquer pessoa que descubra o endereço entra no sistema. É
aceitável num ambiente de demonstração e inaceitável em qualquer outro.

---

## O dia a dia depois de no ar

**Publicar uma mudança:** todo envio para a branch principal do GitHub dispara
uma nova construção sozinho. Você não precisa fazer nada no Render.

**Ver o que está acontecendo:** aba **Logs** do serviço. É onde aparece qualquer
erro que o site tenha dado.

**Quando o banco expirar (30 dias):** o site vai começar a dar erro de conexão.
No Render: **New +** → **PostgreSQL** → plano `free`; depois, no serviço
`validacao-metodos`, **Environment** → aponte `DATABASE_URL` para o banco novo →
**Manual Deploy**. O sistema volta vazio e você entra com a conta `admin` de
novo.

---

## Como isso funciona por dentro

Não é preciso ler para usar. Está aqui para quando algo der errado.

O `render.yaml` descreve o site e o banco. A cada envio o Render roda o
`build.sh`, que faz quatro coisas, nesta ordem e parando no primeiro erro:

1. Instala as dependências do `requirements.txt`.
2. `collectstatic` — reúne CSS e JavaScript num diretório só. Sem esse passo o
   painel de cadastros sobe sem estilo nenhum.
3. `migrate` — ajusta o banco à versão atual do código.
4. `criar_admin` — cria a conta de administração a partir das variáveis de
   ambiente. Existe porque o plano gratuito não tem terminal no servidor, então
   não dá para rodar `createsuperuser` e responder às perguntas.

Depois o site é servido pelo `gunicorn`, e os arquivos estáticos pelo
`whitenoise`, no mesmo processo — é o que dispensa um segundo servidor.

Com `DJANGO_DEBUG=0`, três coisas mudam automaticamente: o programa se recusa a
subir se a chave secreta ainda for a de desenvolvimento, os cookies de sessão
passam a exigir HTTPS, e a página de erro do Django para de mostrar a
configuração inteira para quem visitar o site.

O endereço do site não precisa ser configurado: o Render o publica na variável
`RENDER_EXTERNAL_HOSTNAME` e o programa lê de lá. É o erro mais comum de
primeira implantação — subir tudo certo e receber `DisallowedHost` — e ele não
acontece aqui.
