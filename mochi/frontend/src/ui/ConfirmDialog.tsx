import { render } from 'preact';
import { useEffect, useState } from 'preact/hooks';

export interface ConfirmRequest {
  request_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  timeout_seconds?: number;
}

interface Props {
  request: ConfirmRequest;
  onRespond: (approved: boolean) => void;
}

function ConfirmDialog({ request, onRespond }: Props) {
  const total = Math.max(1, Math.round(request.timeout_seconds ?? 60));
  const [remaining, setRemaining] = useState(total);

  useEffect(() => {
    const timer = setInterval(() => {
      setRemaining((value) => {
        if (value <= 1) {
          clearInterval(timer);
          onRespond(false);
          return 0;
        }
        return value - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [onRespond]);

  return (
    <div class="confirm-mask">
      <div class="confirm-panel">
        <h3>需要确认</h3>
        <p>桌宠想执行高风险操作：</p>
        <pre class="confirm-tool">{request.tool}</pre>
        <pre class="confirm-args">{JSON.stringify(request.arguments, null, 2)}</pre>
        <div class="confirm-actions">
          <button type="button" class="danger" onClick={() => onRespond(false)}>
            拒绝（{remaining}s）
          </button>
          <button type="button" class="primary" onClick={() => onRespond(true)}>
            允许
          </button>
        </div>
      </div>
    </div>
  );
}

export function mountConfirm(
  root: HTMLElement,
  request: ConfirmRequest,
  onRespond: (approved: boolean) => void,
): () => void {
  const handle = (approved: boolean) => {
    render(null, root);
    onRespond(approved);
  };
  render(<ConfirmDialog request={request} onRespond={handle} />, root);
  return () => render(null, root);
}
