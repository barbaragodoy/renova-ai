-- =============================================================
-- tb_notificacoes_whatsapp — Sprint 7 (integração WhatsApp via Twilio)
--
-- Rastreia cada notificação de WhatsApp enviada a um propagandista: o que
-- foi enviado (tipo_notificacao/template_usado), o resultado (status,
-- sid_twilio) e, quando aplicável, o erro. Uma linha por tentativa de
-- envio — igual ao espírito de tb_envios_recomendacoes_piloto (Sprint 5),
-- mas no grão de UMA mensagem Twilio, não de um disparo com várias
-- recomendações juntas.
--
-- status como TEXT simples (queued/sent/delivered/failed/undelivered), não
-- enum de banco — mesma decisão de simplicidade de schema já usada em
-- outras tabelas locais deste projeto (ex.: tb_recomendacoes_painel.status_
-- recomendacao também é VARCHAR livre). Validação de valor fica no Python
-- (constante/Pydantic em backend/app/services/registro_notificacao_whatsapp.py),
-- não em CHECK constraint — mais simples de evoluir conforme a Twilio manda
-- novos status de callback.
--
-- Só Postgres local por enquanto — decisão explícita da Sprint 7, sem
-- tocar Databricks real nesta fase (ver docs/context/decisions-log.md).
-- =============================================================

CREATE TABLE IF NOT EXISTS tb_notificacoes_whatsapp (
    id                  UUID         NOT NULL DEFAULT gen_random_uuid(),
    destinatario        TEXT         NOT NULL,
    tipo_notificacao    TEXT         NOT NULL,
    template_usado      TEXT         NOT NULL,
    status              TEXT         NOT NULL,
    sid_twilio          TEXT,
    erro                TEXT,
    criado_em           TIMESTAMP    NOT NULL DEFAULT now(),
    atualizado_em       TIMESTAMP,

    CONSTRAINT pk_notificacoes_whatsapp PRIMARY KEY (id)
);

COMMENT ON TABLE  tb_notificacoes_whatsapp                    IS 'Rastreabilidade de notificações WhatsApp enviadas via Twilio (Sprint 7). Uma linha por mensagem/tentativa de envio.';
COMMENT ON COLUMN tb_notificacoes_whatsapp.destinatario       IS 'Número do destinatário em E.164 (ex.: +5511999999999), sem o prefixo whatsapp: da API da Twilio.';
COMMENT ON COLUMN tb_notificacoes_whatsapp.tipo_notificacao   IS 'Motivo de negócio da notificação (ex.: ENTRADA_PAINEL, REVISAO_PAINEL) — livre, não FK para tb_recomendacoes_painel nesta fase.';
COMMENT ON COLUMN tb_notificacoes_whatsapp.template_usado     IS 'Chave do template em integrations/whatsapp/templates.py no momento do envio (ex.: entrada_painel) — guardado mesmo que o registry mude depois, para auditoria.';
COMMENT ON COLUMN tb_notificacoes_whatsapp.status             IS 'queued (registrado, antes de enviar) | sent | delivered | failed | undelivered. TEXT livre de propósito — validação de valor é responsabilidade do Python, não de CHECK de banco.';
COMMENT ON COLUMN tb_notificacoes_whatsapp.sid_twilio         IS 'SID da mensagem na Twilio (ex.: SMxxxx). NULL enquanto o envio falha antes da Twilio aceitar a chamada. É por este campo que o webhook de status encontra o registro (não pelo id interno).';
COMMENT ON COLUMN tb_notificacoes_whatsapp.erro               IS 'Mensagem de erro (TwilioSendError ou ErrorCode do callback de status), quando status = failed/undelivered. NULL nos demais casos.';
COMMENT ON COLUMN tb_notificacoes_whatsapp.atualizado_em      IS 'Timestamp da última mudança de status. NULL enquanto o registro nunca saiu de queued (criado_em = estado inicial).';

CREATE INDEX IF NOT EXISTS idx_notificacoes_whatsapp_sid_twilio ON tb_notificacoes_whatsapp (sid_twilio);
CREATE INDEX IF NOT EXISTS idx_notificacoes_whatsapp_destinatario ON tb_notificacoes_whatsapp (destinatario);
