"""
Registry de templates de notificação WhatsApp (Sprint 7).

**PRECISA DE REVISÃO HUMANA.** O conteúdo dos dois templates abaixo é
placeholder estrutural — texto de exemplo para o pipeline (renderizar,
registrar, enviar, receber status) funcionar de ponta a ponta, não texto
aprovado para uso real com propagandista.

Duas coisas ficam de fora de propósito, e continuam de fora até alguém
decidir por elas:

1. **Redação final** — quem aprova copy de mensagem para o propagandista
   não é este código.
2. **Aprovação de Template na Twilio/Meta.** Fora da janela de 24h desde a
   última mensagem do destinatário, a API do WhatsApp exige um Template
   pré-aprovado pela Meta (`ContentSid`), não aceita mais texto livre —
   veja `TwilioSendError` com código 63016 em `client.py`. Os templates
   daqui são `string.Template` Python, renderizados client-side; nenhum
   dos dois foi submetido à aprovação da Meta. Enviar via `service.py` hoje
   só funciona dentro da janela de 24h (ex.: sandbox de teste, conversa já
   iniciada pelo destinatário) — habilitar fora da janela é trabalho novo,
   não uma troca de configuração.
"""
from __future__ import annotations

from string import Template
from typing import Mapping


class TemplateNotFoundError(Exception):
    """`template_key` não existe no registry."""


# PRECISA DE REVISÃO HUMANA — texto placeholder, não aprovado para produção.
_TEMPLATES: dict[str, Template] = {
    "entrada_painel": Template(
        "Olá, $nome_propagandista! O Dr(a). $nome_medico entrou no seu "
        "painel de recomendações neste ciclo ($ciclo). Confira os detalhes "
        "no portal PedAI."
    ),
    "revisao_painel": Template(
        "Olá, $nome_propagandista! O Dr(a). $nome_medico está marcado para "
        "revisão no seu painel neste ciclo ($ciclo) — motivo: "
        "$motivo_revisao. Confira os detalhes no portal PedAI."
    ),
}


def render_template(template_key: str, context: Mapping[str, str]) -> str:
    """Renderiza `template_key` com `context`.

    `string.Template.substitute` (não `safe_substitute`) de propósito: uma
    variável faltando no `context` precisa estourar `KeyError` alto e cedo,
    não virar `$variavel` literal na mensagem que o propagandista recebe.
    """
    template = _TEMPLATES.get(template_key)
    if template is None:
        raise TemplateNotFoundError(
            f"template_key {template_key!r} não existe no registry. "
            f"Disponíveis: {', '.join(sorted(_TEMPLATES))}."
        )
    return template.substitute(context)
