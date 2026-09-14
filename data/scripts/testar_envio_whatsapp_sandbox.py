"""
Validação manual de envio real contra o sandbox do WhatsApp/Twilio
(Sprint 7). NÃO faz parte da suíte automatizada (pytest) de propósito —
bate na API real da Twilio e manda uma mensagem de verdade.

Pré-requisitos:
  1. TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_NUMBER
     exportados no ambiente (nunca em .env commitado).
  2. O número de destino precisa ter entrado no sandbox da Twilio antes
     (enviando a palavra-código do sandbox para o número da Twilio pelo
     WhatsApp) — a Twilio recusa mensagem para quem não entrou.
  3. Postgres local no ar (mesmo docker-compose do resto do projeto) —
     o envio grava em tb_notificacoes_whatsapp antes e depois de mandar.

Uso:
    python data/scripts/testar_envio_whatsapp_sandbox.py +5511999999999
"""
import sys

sys.path.insert(0, ".")

from backend.app.integrations.whatsapp.config import TwilioConfigError
from backend.app.integrations.whatsapp.service import send_whatsapp_notification


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    destinatario = sys.argv[1]
    contexto = {
        "nome_propagandista": "Teste Manual",
        "nome_medico": "Dr(a). Sandbox",
        "ciclo": "202608",
    }

    print(f"Enviando template 'entrada_painel' para {destinatario}...")
    try:
        resultado = send_whatsapp_notification(
            destinatario=destinatario,
            template_key="entrada_painel",
            context=contexto,
            tipo_notificacao="TESTE_MANUAL_SANDBOX",
        )
    except TwilioConfigError as exc:
        print(f"Configuração ausente/incorreta: {exc}")
        sys.exit(1)

    print(f"registro_id  = {resultado.registro_id}")
    print(f"status       = {resultado.status}")
    print(f"sid_twilio   = {resultado.sid_twilio}")
    print(f"erro         = {resultado.erro}")
    print(f"sucesso      = {resultado.sucesso}")

    if resultado.sucesso:
        print(
            "\nEnviado. O status pode continuar mudando de forma assíncrona "
            "(sent -> delivered) via webhook em POST /webhooks/twilio/status, "
            "se TWILIO_STATUS_CALLBACK_URL estiver configurado e alcançável "
            "pela Twilio (ex.: ngrok em desenvolvimento local)."
        )
    else:
        print(
            "\nFalhou. Causa comum em sandbox: o número de destino ainda não "
            "entrou no sandbox (ver pré-requisito 2 no topo deste arquivo), "
            "ou fora da janela de 24h sem Template aprovado (ver PRECISA DE "
            "REVISÃO HUMANA em integrations/whatsapp/templates.py)."
        )


if __name__ == "__main__":
    main()
