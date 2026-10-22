import { render } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { resolveConfig } from '../config';
import type { ShellAdapter } from '../shell/ShellAdapter';

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

interface MemorySession {
  id: string;
  title: string;
  message_count: number;
  updated_at: number;
}

interface MemoryItem {
  id: number;
  type: string;
  content: string;
  importance: number;
}

interface MochiGlobal {
  live2d?: StageHandle;
  switchModel?: (id: string) => Promise<boolean>;
  shell?: ShellAdapter;
  recorder?: {
    setDeviceId: (id: string) => void;
    setMode: (mode: 'push_to_talk' | 'always_on') => void;
  };
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
  const [avatarLoaded, setAvatarLoaded] = useState(false);
  const [currentAvatar, setCurrentAvatar] = useState('');
  const [audioInputs, setAudioInputs] = useState<MediaDeviceInfo[]>([]);
  const [selectedMic, setSelectedMic] = useState(
    () => localStorage.getItem('mochi.micDevice') ?? '',
  );
  const [alwaysOn, setAlwaysOn] = useState(
    () => localStorage.getItem('mochi.voiceMode') === 'always_on',
  );
  const [status, setStatus] = useState('加载中…');
  const [busy, setBusy] = useState(false);
  const [autostart, setAutostart] = useState(false);
  const [clickThrough, setClickThrough] = useState(false);
  const [windowBusy, setWindowBusy] = useState(false);
  const [sessions, setSessions] = useState<MemorySession[]>([]);
  const [currentSession, setCurrentSession] = useState('');
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [profile, setProfile] = useState<Record<string, string>>({});
  const [routeMode, setRouteMode] = useState('auto');

  useEffect(() => {
    void loadConfig();
    void loadAvatarModels();
    void loadAudioDevices();
    void loadShellState();
    void loadMemory();
    const names = getStage()?.getMotionNames() ?? [];
    setMotions(names);
    setSelectedMotion(names.includes('wedding') ? 'wedding' : (names[0] ?? ''));
  }, []);

  async function loadAudioDevices(): Promise<void> {
    try {
      if (!navigator.mediaDevices?.enumerateDevices) return;
      const devices = await navigator.mediaDevices.enumerateDevices();
      setAudioInputs(devices.filter((device) => device.kind === 'audioinput'));
    } catch (error) {
      console.warn('[voice] 设备枚举失败', error);
    }
  }

  function changeMic(deviceId: string): void {
    setSelectedMic(deviceId);
    localStorage.setItem('mochi.micDevice', deviceId);
    getMochi().recorder?.setDeviceId(deviceId);
    setStatus(deviceId ? '已切换麦克风（下一次录音生效）' : '已使用系统默认麦克风');
  }

  async function loadMemory(): Promise<void> {
    try {
      const [sessionResponse, memoryResponse] = await Promise.all([
        fetch(`${config.apiBase}/api/v1/memory/sessions`, { headers: apiHeaders() }),
        fetch(`${config.apiBase}/api/v1/memory/memories?limit=30`, { headers: apiHeaders() }),
      ]);
      if (sessionResponse.ok) {
        const data = (await sessionResponse.json()) as {
          sessions: MemorySession[];
          current: string;
        };
        setSessions(data.sessions);
        setCurrentSession(data.current);
      }
      if (memoryResponse.ok) {
        const data = (await memoryResponse.json()) as {
          memories: MemoryItem[];
          profile: Record<string, string>;
        };
        setMemories(data.memories);
        setProfile(data.profile);
      }
    } catch (error) {
      console.warn('[memory] load failed', error);
    }
  }

  async function switchMemorySession(id: string): Promise<void> {
    try {
      const response = await fetch(
        `${config.apiBase}/api/v1/memory/sessions/${encodeURIComponent(id)}/switch`,
        { method: 'POST', headers: apiHeaders() },
      );
      if (!response.ok) {
        setStatus('切换会话失败');
        return;
      }
      setCurrentSession(id);
      setStatus('已切换会话');
      await loadMemory();
    } catch (error) {
      setStatus(`切换会话失败：${String(error)}`);
    }
  }

  async function deleteMemorySession(id: string): Promise<void> {
    await fetch(`${config.apiBase}/api/v1/memory/sessions/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: apiHeaders(),
    });
    await loadMemory();
    setStatus('会话已删除');
  }

  async function deleteMemoryItem(id: number): Promise<void> {
    await fetch(`${config.apiBase}/api/v1/memory/memories/${id}`, {
      method: 'DELETE',
      headers: apiHeaders(),
    });
    await loadMemory();
    setStatus('记忆已删除');
  }

  async function forgetAll(): Promise<void> {
    await fetch(`${config.apiBase}/api/v1/memory/forget`, {
      method: 'POST',
      headers: apiHeaders(),
    });
    await loadMemory();
    setStatus('长期记忆已清空');
  }

  async function changeRouteMode(mode: string): Promise<void> {
    setRouteMode(mode);
    await fetch(`${config.apiBase}/api/v1/config/agent`, {
      method: 'PATCH',
      headers: apiHeaders(),
      body: JSON.stringify({ route_mode: mode }),
    });
    setStatus(`路由模式：${mode}`);
  }

  async function loadShellState(): Promise<void> {
    const shell = getMochi().shell;
    if (!shell?.isDesktop) return;
    try {
      setAutostart(await shell.getAutostart());
    } catch (error) {
      console.warn('[shell] getAutostart failed', error);
    }
  }

  async function toggleAutostart(value: boolean): Promise<void> {
    const shell = getMochi().shell;
    if (!shell || windowBusy) return;
    setWindowBusy(true);
    try {
      await shell.setAutostart(value);
      setAutostart(await shell.getAutostart());
      setStatus(value ? '已开启开机自启' : '已关闭开机自启');
    } catch (error) {
      setStatus(`开机自启设置失败：${String(error)}`);
    } finally {
      setWindowBusy(false);
    }
  }

  async function toggleClickThrough(value: boolean): Promise<void> {
    const shell = getMochi().shell;
    if (!shell || windowBusy) return;
    setWindowBusy(true);
    try {
      await shell.setClickThrough(value);
      setClickThrough(value);
      setStatus(
        value
          ? '已穿透：右下角热区或 Ctrl+Shift+T 唤回交互'
          : '已恢复正常交互',
      );
    } catch (error) {
      setStatus(`穿透设置失败：${String(error)}`);
    } finally {
      setWindowBusy(false);
    }
  }

  async function hideToTray(): Promise<void> {
    const shell = getMochi().shell;
    if (!shell) return;
    await shell.minimizeToTray();
    setStatus('已隐藏到托盘；点击托盘图标或 Ctrl+Shift+M 唤回');
  }

  async function quitApp(): Promise<void> {
    await getMochi().shell?.quit();
  }

  function changeAlwaysOn(value: boolean): void {
    setAlwaysOn(value);
    localStorage.setItem('mochi.voiceMode', value ? 'always_on' : 'push_to_talk');
    getMochi().recorder?.setMode(value ? 'always_on' : 'push_to_talk');
    setStatus(value ? '常开麦克风：静音 700ms 后自动结束' : '按住说话模式');
  }

  async function loadAvatarModels(): Promise<void> {
    try {
      const response = await fetch(`${config.apiBase}/api/v1/live2d/models`, { headers: apiHeaders() });
      if (!response.ok) return;
      const data = (await response.json()) as { models: AvatarModel[] };
      setAvatarModels(data.models);
      const saved = localStorage.getItem('mochi.live2dModel');
      const valid = saved && data.models.some((item) => item.id === saved);
      setCurrentAvatar(valid ? String(saved) : (data.models[0]?.id ?? ''));
    } catch (error) {
      console.warn('[settings] 模型清单获取失败', error);
    } finally {
      setAvatarLoaded(true);
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
      const response = await fetch(`${config.apiBase}/api/v1/config/llm`, { headers: apiHeaders() });
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
      const response = await fetch(`${config.apiBase}/api/v1/config/llm`, {
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
      const response = await fetch(`${config.apiBase}/api/v1/llm/models`, { headers: apiHeaders() });
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
            {avatarModels.length === 0 && (
              <option value="">{avatarLoaded ? '未发现模型' : '加载中…'}</option>
            )}
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

        <details class="settings-motions">
          <summary>语音输入（S4：设备 / 模式）</summary>
          <label class="settings-checkbox">
            <input
              type="checkbox"
              checked={alwaysOn}
              onChange={(event) => changeAlwaysOn(event.currentTarget.checked)}
            />
            <span>常开麦克风（静音 700ms 自动结束；默认按住说话）</span>
          </label>
          <label class="settings-avatar">
            <span>麦克风设备</span>
            <select value={selectedMic} onChange={(event) => changeMic(event.currentTarget.value)}>
              <option value="">系统默认</option>
              {audioInputs.map((device, index) => (
                <option key={device.deviceId || index} value={device.deviceId}>
                  {device.label || `麦克风 ${index + 1}`}
                </option>
              ))}
            </select>
          </label>
          <div class="settings-motion-row">
            <button type="button" onClick={() => void loadAudioDevices()}>
              重新扫描设备
            </button>
          </div>
          <p class="settings-hint">
            语音识别在后端 faster-whisper 完成；播放回复期间麦克风自动关闭（半双工）。
          </p>
        </details>

        <details class="settings-motions">
          <summary>桌面壳（S5：自启 / 穿透 / 托盘）</summary>
          <label class="settings-checkbox">
            <input
              type="checkbox"
              checked={autostart}
              disabled={windowBusy}
              onChange={(event) => void toggleAutostart(event.currentTarget.checked)}
            />
            <span>开机自启（Windows 登录后自动启动）</span>
          </label>
          <label class="settings-checkbox">
            <input
              type="checkbox"
              checked={clickThrough}
              disabled={windowBusy}
              onChange={(event) => void toggleClickThrough(event.currentTarget.checked)}
            />
            <span>点击穿透（右下 90px 热区或 Ctrl+Shift+T 唤回）</span>
          </label>
          <div class="settings-motion-row">
            <button type="button" onClick={() => void hideToTray()}>
              隐藏到托盘
            </button>
            <button type="button" onClick={() => void quitApp()}>
              退出 Mochi
            </button>
          </div>
          <p class="settings-hint">
            全局快捷键：Ctrl+Shift+M 显隐 · Ctrl+Shift+T 穿透 · Ctrl+Shift+Space 按住说话。
          </p>
        </details>

        <details class="settings-motions">
          <summary>记忆与会话（S6：{sessions.length} 个会话 / {memories.length} 条记忆）</summary>
          <label>
            <span>路由模式</span>
            <select value={routeMode} onChange={(event) => void changeRouteMode(event.currentTarget.value)}>
              <option value="auto">auto（规则 + LLM 兜底）</option>
              <option value="chat_only">chat_only（只闲聊）</option>
              <option value="force_agent">force_agent（优先工具）</option>
            </select>
          </label>
          <p class="settings-hint">
            画像：{Object.entries(profile).map(([key, value]) => `${key}=${value}`).join('、') || '（空）'}
          </p>
          <div class="memory-list">
            {sessions.slice(0, 5).map((item) => (
              <div class={`memory-row${item.id === currentSession ? ' current' : ''}`} key={item.id}>
                <span>
                  {item.title} · {item.message_count} 条
                </span>
                <button type="button" onClick={() => void switchMemorySession(item.id)}>
                  切换
                </button>
                <button type="button" onClick={() => void deleteMemorySession(item.id)}>
                  删除
                </button>
              </div>
            ))}
          </div>
          <div class="memory-list">
            {memories.slice(0, 8).map((item) => (
              <div class="memory-row" key={item.id}>
                <span title={item.content}>{item.content}</span>
                <button type="button" onClick={() => void deleteMemoryItem(item.id)}>
                  删除
                </button>
              </div>
            ))}
            {memories.length === 0 && <p class="settings-hint">还没有长期记忆。</p>}
          </div>
          <div class="settings-motion-row">
            <button type="button" onClick={() => void loadMemory()}>
              刷新
            </button>
            <button type="button" onClick={() => void forgetAll()}>
              清空全部记忆
            </button>
          </div>
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
