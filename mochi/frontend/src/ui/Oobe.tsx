import { render } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { resolveConfig } from '../config';
import type { ShellAdapter } from '../shell/ShellAdapter';

const config = resolveConfig();

interface CharacterInfo {
  id: string;
  name: string;
  greeting: string;
}

interface Props {
  onDone: () => void;
}

function headers(): Record<string, string> {
  const out: Record<string, string> = { 'Content-Type': 'application/json' };
  if (config.token) out['X-Mochi-Token'] = config.token;
  return out;
}

function Oobe({ onDone }: Props) {
  const [step, setStep] = useState(0);
  const [baseUrl, setBaseUrl] = useState('http://127.0.0.1:8080/v1');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('qwen2.5-7b-instruct');
  const [characters, setCharacters] = useState<CharacterInfo[]>([]);
  const [selected, setSelected] = useState('tsundere');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void loadExisting();
  }, []);

  async function loadExisting(): Promise<void> {
    try {
      const [charResponse, llmResponse] = await Promise.all([
        fetch(`${config.apiBase}/api/v1/characters`, { headers: headers() }),
        fetch(`${config.apiBase}/api/v1/config/llm`, { headers: headers() }),
      ]);
      if (charResponse.ok) {
        const data = (await charResponse.json()) as {
          characters: CharacterInfo[];
          current: string;
        };
        setCharacters(data.characters);
        setSelected(data.current);
      }
      if (llmResponse.ok) {
        const data = (await llmResponse.json()) as { base_url: string; model: string };
        setBaseUrl(data.base_url);
        setModel(data.model);
      }
    } catch (error) {
      console.warn('[oobe] load failed', error);
    }
  }

  async function saveLlm(): Promise<void> {
    if (busy) return;
    if (!baseUrl.trim() || !apiKey.trim()) {
      setStatus('请填写服务地址和 API Key');
      return;
    }
    setBusy(true);
    try {
      const response = await fetch(`${config.apiBase}/api/v1/config/llm`, {
        method: 'PATCH',
        headers: headers(),
        body: JSON.stringify({
          base_url: baseUrl.trim(),
          api_key: apiKey.trim(),
          model: model.trim(),
          disable_thinking: true,
        }),
      });
      if (!response.ok) {
        setStatus(`保存失败：HTTP ${response.status}`);
        return;
      }
      setStatus('');
      setStep(2);
    } finally {
      setBusy(false);
    }
  }

  async function chooseCharacter(): Promise<void> {
    setBusy(true);
    try {
      const response = await fetch(
        `${config.apiBase}/api/v1/characters/${encodeURIComponent(selected)}/select`,
        { method: 'POST', headers: headers() },
      );
      if (!response.ok) {
        setStatus(`选择失败：HTTP ${response.status}`);
        return;
      }
      setStep(3);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div class="oobe-mask">
      <div class="oobe-panel">
        <header>
          <h2>欢迎使用 Mochi</h2>
          <span class="oobe-step">{step + 1} / 4</span>
        </header>
        {step === 0 && (
          <div>
            <p>一个会呼吸、有情绪、记得你的桌面伙伴。</p>
            <p class="oobe-hint">
              接下来用 4 步完成配置。API Key 只写入本机 settings.json，不写日志。
            </p>
            <button type="button" class="primary" onClick={() => setStep(1)}>
              开始配置
            </button>
            <button type="button" class="link" onClick={onDone}>
              稍后设置
            </button>
          </div>
        )}
        {step === 1 && (
          <div>
            <h3>连接模型</h3>
            <label>
              <span>服务地址</span>
              <input
                value={baseUrl}
                onInput={(event) => setBaseUrl(event.currentTarget.value)}
                placeholder="http://127.0.0.1:8080/v1"
              />
            </label>
            <label>
              <span>API Key</span>
              <input
                type="password"
                value={apiKey}
                onInput={(event) => setApiKey(event.currentTarget.value)}
                placeholder="sk-..."
                autocomplete="off"
              />
            </label>
            <label>
              <span>模型</span>
              <input value={model} onInput={(event) => setModel(event.currentTarget.value)} />
            </label>
            <p class="oobe-hint">
              本地 LM Studio / Ollama 可以把 API Key 填任意非空字符串。
            </p>
            <div class="oobe-actions">
              <button type="button" onClick={() => setStep(0)}>
                上一步
              </button>
              <button type="button" class="primary" disabled={busy} onClick={() => void saveLlm()}>
                保存并继续
              </button>
            </div>
          </div>
        )}
        {step === 2 && (
          <div>
            <h3>选择角色</h3>
            <div class="oobe-characters">
              {characters.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  class={selected === item.id ? 'oobe-character active' : 'oobe-character'}
                  onClick={() => setSelected(item.id)}
                >
                  <b>{item.name}</b>
                  <small>{item.id}</small>
                </button>
              ))}
            </div>
            <div class="oobe-actions">
              <button type="button" onClick={() => setStep(1)}>
                上一步
              </button>
              <button type="button" class="primary" disabled={busy} onClick={() => void chooseCharacter()}>
                就选它
              </button>
            </div>
          </div>
        )}
        {step === 3 && (
          <div>
            <h3>准备完成</h3>
            <p>在输入框说句话试试。按住麦克风也可以说话（需后端配置语音）。</p>
            <p class="oobe-hint">快捷键：Ctrl+Shift+M 显隐 · Ctrl+Shift+T 穿透 · Ctrl+Shift+Space 按住说话。</p>
            <button type="button" class="primary" onClick={onDone}>
              开始聊天
            </button>
          </div>
        )}
        <p class="settings-status">{status}</p>
      </div>
    </div>
  );
}

export function mountOobe(root: HTMLElement, onDone: () => void): () => void {
  const finish = () => {
    render(null, root);
    onDone();
  };
  render(<Oobe onDone={finish} />, root);
  return () => render(null, root);
}

export type { ShellAdapter };
