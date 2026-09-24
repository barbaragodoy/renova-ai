import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface AcessoBloqueadoProps {
  /** Mensagem devolvida pelo backend (`ApiError.message`), preferida à
   *  padrão porque é a mesma fonte única definida em
   *  `backend/app/auth/status_acesso.py`. */
  mensagem?: string;
  onSair: () => void;
}

const MENSAGEM_PADRAO =
  "Seu acesso ao Ped.AI está bloqueado temporariamente. Aguarde a ativação da sua conta ou o fim do período de testes.";

/**
 * Tela mostrada quando a API devolve 403 `ACESSO_BLOQUEADO`
 * (`backend/app/auth/status_acesso.py`) — STATUS_ACESSO diferente de
 * 'ATIVO' em `tb_perfil_portal`, ou ausência de linha (deny-by-default).
 *
 * Mesma tela nos dois pontos de integração e nos dois modos de
 * autenticação: `Login.tsx` a mostra quando `POST /auth/login` (modo senha)
 * devolve o 403, e `src/auth/entraId.ts` quando `GET /auth/contexto` (modo
 * entra_id) devolve o mesmo 403 antes mesmo de qualquer sessão existir.
 */
export function AcessoBloqueado({ mensagem, onSair }: AcessoBloqueadoProps) {
  return (
    <div className="grid min-h-dvh place-items-center px-6 py-12">
      <Card className="w-full max-w-md p-6 text-center sm:p-8">
        <p className="text-sm font-semibold tracking-[0.08em] text-[var(--color-primary)] uppercase">
          Ped.AI
        </p>
        <h1 className="mt-6 text-2xl leading-tight font-semibold">
          Acesso bloqueado
        </h1>
        <p className="mt-4 text-sm text-[var(--color-muted-foreground)]">
          {mensagem ?? MENSAGEM_PADRAO}
        </p>
        <Button type="button" size="lg" className="mt-8 w-full" onClick={onSair}>
          Sair
        </Button>
      </Card>
    </div>
  );
}
