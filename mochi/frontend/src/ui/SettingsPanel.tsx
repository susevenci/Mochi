import { render } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { resolveConfig } from '../config';

interface LlmConfigView {
  base_url: string;
  model: string;
  disable_thinking: boolean;
  api_key_set: boolean;
  api_key_hint: string;
  source: string;
}

interface Props {
  onClose: () => void;
}

interface StageHandle {
  getMotionNames(): string[];
  playMotion(name: string, priority?: 'normal' | 'high'): boolean;
}

interface AvatarModel {
  id: string;
  name: string;
  url: string;
  motions: number;
  expressions: number;
}

interface MochiGlobal {
  live2d?: StageHandle;
  switchModel?: (id: string) => Promise<boolean>;
}

function getMochi(): MochiGlobal {
  return (window as unknown as { mochi?: MochiGlobal }).mochi ?? {};
}

function getStage(): StageHandle | undefined {
  return getMochi().live2d;
}

const config = resolveConfig();

function apiHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (config.token) {
    headers['X-Mochi-Token'] = config.token;
  }
  return headers;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

/**
 * LLM 配置面板：base_url / api_key / 模型选择。
 * 保存走 PATCH /api/v1/config/llm，写 settings.json 后即时重建 Provider。
 */
export function SettingsPanel({ onClose }: Props) {
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [disableThinking, setDisableThinking] = useState(true);
  const [motions, setMotions] = useState<string[]>([]);
  const [selectedMotion, setSelectedMotion] = useState('');
  const [avatarModels, setAvatarModels] = useState<AvatarModel[]>([]);
  const [currentAvatar, setCurrentAvatar] = useState('');
  const [status, setStatus] = useState('加载中…');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void loadConfig();
    void loadAvatarModels();
    const names = getStage()?.getMotionNames() ?? [];
    setMotions(names);
    setSelectedMotion(names.includes('wedding') ? 'wedding' : (names[0] ?? ''));
  }, []);

  async function loadAvatarModels(): Promise<void> {
    try {
      const response = await fetch('/api/v1/live2d/models', { headers: apiHeaders() });
      if (!response.ok) return;
      const data = (await response.json()) as { models: AvatarModel[] };
      setAvatarModels(data.models);
      const saved = localStorage.getItem('mochi.live2dModel');
      const valid = saved && data.models.some((item) => item.id === saved);
      setCurrentAvatar(valid ? String(saved) : (data.models[0]?.id ?? ''));
    } catch (error) {
      console.warn('[settings] 模型清单获取失败', error);
    }
  }

  async function switchAvatar(id: string): Promise<void> {
    if (!id || id === currentAvatar) return;
    const ok = await getMochi().switchModel?.(id);
    if (!ok) {
      setStatus('切换模型失败，请查看控制台');
      return;
    }
    setCurrentAvatar(id);
    const names = getStage()?.getMotionNames() ?? [];
    setMotions(names);
    setSelectedMotion(names[0] ?? '');
    setStatus(`已切换模型：${id}（动作 ${names.length}）`);
  }

  function playSelectedMotion(): void {
    const stage = getStage();
    if (!stage || !selectedMotion) {
      setStatus('模型尚未加载完成');
      return;
    }
    stage.playMotion(selectedMotion, 'high');
    setStatus(`已播放动作：${selectedMotion}`);
  }

  async function loadConfig(): Promise<void> {
    try {
      const response = await fetch('/api/v1/config/llm', { headers: apiHeaders() });
      if (!response.ok) {
        setStatus(`读取失败：${await readError(response)}`);
        return;
      }
      const view = (await response.json()) as LlmConfigView;
      setBaseUrl(view.base_url);
      setModel(view.model);
      setDisableThinking(view.disable_thinking);
      setApiKey('');
      setStatus(
        view.api_key_set
          ? `已保存密钥 ${view.api_key_hint}（留空表示不修改）`
          : '尚未设置 API Key',
      );
    } catch (error) {
      setStatus(`读取失败：${String(error)}`);
    }
  }

  async function save(): Promise<boolean> {
    const payload: Record<string, unknown> = {
      base_url: baseUrl.trim(),
      disable_thinking: disableThinking,
    };
    if (apiKey.trim()) {
      payload.api_key = apiKey.trim();
    }
    if (model.trim()) {
      payload.model = model.trim();
    }
    try {
      const response = await fetch('/api/v1/config/llm', {
        method: 'PATCH',
        headers: apiHeaders(),
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        setStatus(`保存失败：${await readError(response)}`);
        return false;
      }
      const view = (await response.json()) as LlmConfigView;
      setStatus(`已保存并生效（模型：${view.model}）`);
      setApiKey('');
      return true;
    } catch (error) {
      setStatus(`保存失败：${String(error)}`);
      return false;
    }
  }

  async function saveAndFetchModels(): Promise<void> {
    if (busy) return;
    setBusy(true);
    setStatus('正在保存并获取模型列表…');
    try {
      if (!(await save())) return;
      const response = await fetch('/api/v1/llm/models', { headers: apiHeaders() });
      if (!response.ok) {
        setStatus(`获取模型失败：${await readError(response)}`);
        return;
      }
      const data = (await response.json()) as { models: string[]; count: number };
      setModels(data.models);
      setStatus(`已获取 ${data.count} 个模型`);
      if (!data.models.includes(model) && data.models.length > 0) {
        setModel(data.models[0]);
      }
    } catch (error) {
      setStatus(`获取模型失败：${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div class="settings-mask" onClick={onClose}>
      <div class="settings-panel" onClick={(event) => event.stopPropagation()}>
        <header>
          <h2>LLM 配置</h2>
          <button type="button" class="settings-close" onClick={onClose}>
            ×
          </button>
        </header>

        <label>
          <span>服务地址 base_url</span>
          <input
            type="text"
            value={baseUrl}
            placeholder="http://127.0.0.1:8080/v1"
            onInput={(event) => setBaseUrl(event.currentTarget.value)}
          />
        </label>

        <label>
          <span>API Key</span>
          <input
            type="password"
            value={apiKey}
            placeholder="留空表示不修改已保存的密钥"
            autocomplete="off"
            onInput={(event) => setApiKey(event.currentTarget.value)}
          />
        </label>

        <label>
          <span>模型</span>
          <select value={model} onChange={(event) => setModel(event.currentTarget.value)}>
            {model && !models.includes(model) && <option value={model}>{model}（当前）</option>}
            {models.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label class="settings-checkbox">
          <input
            type="checkbox"
            checked={disableThinking}
            onChange={(event) => setDisableThinking(event.currentTarget.checked)}
          />
          <span>关闭思考模式（推荐：首字更快，不浪费 token）</span>
        </label>

        <div class="settings-actions">
          <button type="button" class="primary" disabled={busy} onClick={() => void saveAndFetchModels()}>
            保存并获取模型
          </button>
          <button type="button" disabled={busy} onClick={() => void save()}>
            仅保存
          </button>
          <button type="button" disabled={busy} onClick={() => void loadConfig()}>
            重新读取
          </button>
        </div>

        <p class="settings-status">{status}</p>

        <label class="settings-avatar">
          <span>角色模型（衣柜）</span>
          <select value={currentAvatar} onChange={(event) => void switchAvatar(event.currentTarget.value)}>
            {avatarModels.length === 0 && <option value="">未发现模型</option>}
            {avatarModels.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id}（动作 {item.motions} / 表情 {item.expressions}）
              </option>
            ))}
          </select>
        </label>

        <details class="settings-motions">
          <summary>Live2D 动作试玩（{motions.length} 个）</summary>
          <div class="settings-motion-row">
            <select
              value={selectedMotion}
              onChange={(event) => setSelectedMotion(event.currentTarget.value)}
            >
              {motions.length === 0 && <option value="">模型未加载</option>}
              {motions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <button type="button" onClick={playSelectedMotion}>
              播放
            </button>
          </div>
          <p class="settings-hint">点击角色也会触发摸头 / 戳身体的动作。</p>
        </details>

        <p class="settings-hint">
          密钥只写本地 settings.json，不写日志、不回传明文；保存后下一轮对话立即生效。
        </p>
      </div>
    </div>
  );
}

/** 挂载到指定容器；返回卸载函数。 */
export function mountSettingsPanel(root: HTMLElement): () => void {
  render(<SettingsPanel onClose={() => render(null, root)} />, root);
  return () => render(null, root);
}
