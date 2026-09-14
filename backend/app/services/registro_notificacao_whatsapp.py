"""
Serviço de registro/rastreabilidade de notificações WhatsApp (Sprint 7).

Mesmo padrão de acesso a banco de `registro_envio.py` (Sprint 5): SQL
parametrizado via `get_engine()` + `text()`, sem ORM — não existe `Base`,
`Column` nem `Session` em nenhum lugar deste projeto (ver
docs/context/decisions-log.md).

`registrar_notificacao()` cria quando `registro_id is None` e atualiza
quando não é — mesma assinatura conceitual usada pelo restante do projeto
para "upsert simples" (a alternativa seria duas funções, mas o chamador em
`service.py` já sabe naturalmente se está criando ou reagindo a um envio
anterior, então uma função só reduz a decisão a um parâmetro).

`buscar_por_sid_twilio()` existe porque o webhook de status da Twilio
(`routers/webhooks_twilio.py`) recebe `MessageSid`, nunca o `id` interno —
sem esta função não haveria como o webhook encontrar qual registro
atualizar.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Row

from backend.app.db.databricks_connection import get_engine


def _engine():
    return get_engine()


def registrar_notificacao(
    registro_id: Optional[str],
    destinatario: str,
    tipo_notificacao: str,
    template_usado: str,
    status: str,
    sid_twilio: Optional[str] = None,
    erro: Optional[str] = None,
) -> str:
    """Cria (`registro_id is None`) ou atualiza (`registro_id` informado) um
    registro de notificação. Devolve o `id` (novo, na criação; o mesmo
    recebido, na atualização) — quem chama sempre sai com um id em mãos,
    sem precisar de um segundo caminho de código só para o retorno.

    Na atualização, `sid_twilio`/`erro` sobrescrevem o valor anterior mesmo
    quando `None` — o chamador é responsável por repassar o valor que quer
    manter (ex.: o webhook, que já leu a linha via `buscar_por_sid_twilio()`
    antes de decidir o que muda). Não fizemos `COALESCE` implícito aqui de
    propósito: um `COALESCE` esconderia um `None` passado por engano em vez
    de limpar o campo quando é isso que o chamador quer.
    """
    with _engine().connect() as conn:
        if registro_id is None:
            linha = conn.execute(
                text(
                    """
                    INSERT INTO tb_notificacoes_whatsapp (
                        destinatario, tipo_notificacao, template_usado,
                        status, sid_twilio, erro
                    ) VALUES (
                        :destinatario, :tipo_notificacao, :template_usado,
                        :status, :sid_twilio, :erro
                    )
                    RETURNING id
                    """
                ),
                {
                    "destinatario": destinatario,
                    "tipo_notificacao": tipo_notificacao,
                    "template_usado": template_usado,
                    "status": status,
                    "sid_twilio": sid_twilio,
                    "erro": erro,
                },
            ).fetchone()
            conn.commit()
            return str(linha.id)

        conn.execute(
            text(
                """
                UPDATE tb_notificacoes_whatsapp
                   SET destinatario = :destinatario,
                       tipo_notificacao = :tipo_notificacao,
                       template_usado = :template_usado,
                       status = :status,
                       sid_twilio = :sid_twilio,
                       erro = :erro,
                       atualizado_em = :atualizado_em
                 WHERE id = :id
                """
            ),
            {
                "id": registro_id,
                "destinatario": destinatario,
                "tipo_notificacao": tipo_notificacao,
                "template_usado": template_usado,
                "status": status,
                "sid_twilio": sid_twilio,
                "erro": erro,
                "atualizado_em": datetime.now(timezone.utc),
            },
        )
        conn.commit()
        return registro_id


def buscar_por_sid_twilio(sid_twilio: str) -> Optional[Row]:
    """Devolve a linha (todas as colunas) do registro com este `sid_twilio`,
    ou `None` se não existir. `sid_twilio` não é único a nível de banco (sem
    `UNIQUE` na tabela — ver script 17), mas é único na prática: cada envio
    bem-sucedido gera um SID novo pela Twilio. Se algum dia houver mais de
    uma linha para o mesmo SID, pega a mais recente por `criado_em`."""
    with _engine().connect() as conn:
        return conn.execute(
            text(
                """
                SELECT id, destinatario, tipo_notificacao, template_usado,
                       status, sid_twilio, erro, criado_em, atualizado_em
                  FROM tb_notificacoes_whatsapp
                 WHERE sid_twilio = :sid_twilio
                 ORDER BY criado_em DESC
                 LIMIT 1
                """
            ),
            {"sid_twilio": sid_twilio},
        ).fetchone()
