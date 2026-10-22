import { render } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import { resolveConfig } from '../config';
import type { AudioPlayer } from '../live2d/AudioPlayer';
import type { ExpressionController } from '../live2d/ExpressionController';
import type { GazeController } from '../live2d/GazeController';
import type { IdleController } from '../live2d/IdleController';
import type { LipSync } from '../live2d/LipSync';
import type { Live2DStage } from '../live2d/Live2DStage';
import type { MotionController, MotionPriority } from '../live2d/MotionController';
import {
  getEmotionPoints,
  getEmotionSnapshot,
  ingestEmotion,
  loadEmotionHistory,
  subscribeEmotion,
  type EmotionSnapshot,
} from './emotionStore';

interface DebugHandles {
  live2d: Live2DStage;
  motion: MotionController;
  expression: ExpressionController;
  idle: IdleController;
  gaze: GazeController;
  lipSync: LipSync;
  audio: AudioPlayer;
}

interface Props {
  onClose: () => void;
}

type Tab = 'performance' | 'emotion';

interface EmotionLabelDef {
  name: string;
  pad: { valence: number; arousal: number; dominance: number };
  radius: number;
  tau: number;
  tts: Record<string, number>;
  style: string[];
}

interface StimulusDef {
  tag: string;
  category: string;
  dval: number;
  darousal: number;
  ddominance: number;
  habituate: boolean;
}

interface PersonaView {
  reactivity: Record<string, number>;
  decay_multiplier: number;
  refractory_seconds: number;
  dominance_recovery: number;
  label_bias: Record<string, number>;
}

interface TransitionDef {
  from: string[];
  to: string;
  guards: string[];
}

interface Catalog {
  labels: EmotionLabelDef[];
  high_intensity_labels: string[];
  stimuli: StimulusDef[];
  persona: PersonaView;
  transitions: TransitionDef[];
  blocked_direct: string[][];
}

interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
}

const config = resolveConfig();

function apiHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (config.token) headers['X-Mochi-Token'] = config.token;
  return headers;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getHandles(): DebugHandles | null {
  const mochi = (window as unknown as { mochi?: Partial<DebugHandles> }).mochi;
  if (!mochi?.live2d || !mochi.motion || !mochi.expression || !mochi.lipSync) return null;
  if (!mochi.idle || !mochi.gaze || !mochi.audio) return null;
  return mochi as DebugHandles;
}

const LABEL_COLORS: Record<string, string> = {
  neutral: '#9aa4b2',
  happy: '#f2b84b',
  excited: '#f08a3c',
  amused: '#e8c547',
  affectionate: '#ef7fa8',
  shy: '#e58fb8',
  proud: '#b38ae0',
  curious: '#55b6d9',
  sleepy: '#8e9bd6',
  bored: '#9c9c8f',
  lonely: '#6f86c9',
  sad: '#5f7fa8',
  worried: '#c98c5a',
  angry: '#d9534f',
  hurt: '#b65c7a',
  surprised: '#e6a23c',
};

function labelColor(label: string | undefined | null): string {
  return LABEL_COLORS[label ?? 'neutral'] ?? '#9aa4b2';
}

function formatClock(ts: number | undefined): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false });
}

// ── 表现 / Live2D 自检（S2）───────────────────────────────────────────────
function PerformanceTab({ handles }: { handles: DebugHandles | null }) {
  const [level, setLevel] = useState(0);
  const [rms, setRms] = useState(0);
  const [motionName, setMotionName] = useState('');
  const [expressionName, setExpressionName] = useState('');
  const [weight, setWeight] = useState(100);
  const [status, setStatus] = useState('就绪');
  const [results, setResults] = useState<CheckResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [motionStatus, setMotionStatus] = useState('idle');
  const [activeExpressions, setActiveExpressions] = useState('');
  const ticking = useRef(true);

  useEffect(() => {
    ticking.current = true;
    const timer = setInterval(() => {
      if (!ticking.current || !handles) return;
      setLevel(handles.lipSync.level);
      setRms(handles.lipSync.rms);
      const motion = handles.motion.status;
      setMotionStatus(
        `${motion.playing ?? '—'}${motion.queue.length ? ` + queued(${motion.queue.join(',')})` : ''}`,
      );
      const active = handles.expression.status();
      setActiveExpressions(
        active.map((item) => `${item.name}:${item.weight.toFixed(2)}`).join(' ') || '—',
      );
    }, 120);
    return () => {
      ticking.current = false;
      clearInterval(timer);
    };
  }, [handles]);

  useEffect(() => {
    if (!handles) return;
    const motions = handles.live2d.getMotionNames();
    setMotionName(motions.includes('touch_head') ? 'touch_head' : (motions[0] ?? ''));
    const expressions = handles.live2d.getExpressionNames();
    setExpressionName(expressions[0] ?? '');
  }, [handles]);

  const caps = handles?.live2d.caps;
  const motions = handles?.live2d.getMotionNames() ?? [];
  const expressions = handles?.live2d.getExpressionNames() ?? [];

  function play(priority: MotionPriority): void {
    if (!handles || !motionName) return;
    const ok = handles.motion.request(motionName, priority);
    setStatus(`request(${motionName}, ${priority}) → ${ok ? 'accepted' : 'rejected(cooldown)'}`);
  }

  function playExpression(): void {
    if (!handles || !expressionName) return;
    handles.expression.play(expressionName, weight / 100, { fadeMs: 300 });
    setStatus(`expression ${expressionName} weight=${(weight / 100).toFixed(2)}`);
  }

  async function runSelfCheck(): Promise<void> {
    if (!handles || busy) return;
    setBusy(true);
    const out: CheckResult[] = [];
    try {
      const capsNow = handles.live2d.caps;
      out.push({
        name: '模型已加载',
        ok: Boolean(capsNow),
        detail: capsNow ? `${capsNow.name} params=${capsNow.parameterCount}` : '未加载',
      });
      if (!capsNow) {
        setResults(out);
        return;
      }

      out.push({
        name: '动作能力',
        ok: capsNow.motionGroups.length > 0,
        detail: `groups=${capsNow.motionGroups.length} expressions=${capsNow.expressions.length}`,
      });

      const breathStart = handles.live2d.getParameter('ParamBreath');
      const bodyStart = handles.live2d.getParameter('ParamBodyAngleX');
      await sleep(1500);
      const breathEnd = handles.live2d.getParameter('ParamBreath');
      const bodyEnd = handles.live2d.getParameter('ParamBodyAngleX');
      const breathDelta = Math.abs(breathEnd - breathStart);
      const bodyDelta = Math.abs(bodyEnd - bodyStart);
      out.push({
        name: '待机（呼吸/微摆）',
        ok: breathDelta > 0.01 || bodyDelta > 0.01,
        detail: `Δbreath=${breathDelta.toFixed(3)} Δbody=${bodyDelta.toFixed(3)}`,
      });

      let minEye = 1;
      const blinkStart = performance.now();
      while (performance.now() - blinkStart < 6000) {
        minEye = Math.min(minEye, handles.live2d.getParameter('ParamEyeLOpen'));
        await sleep(80);
      }
      out.push({
        name: '眨眼',
        ok: minEye < 0.5,
        detail: `minEyeOpen=${minEye.toFixed(2)}（6s 采样）`,
      });

      const beforeAudio = handles.lipSync.level;
      await handles.audio.playTestSequence();
      let maxLevel = 0;
      let minLevel = 1;
      const lipStart = performance.now();
      while (performance.now() - lipStart < 3000) {
        maxLevel = Math.max(maxLevel, handles.lipSync.level);
        minLevel = Math.min(minLevel, handles.lipSync.level);
        await sleep(60);
      }
      handles.audio.stop();
      out.push({
        name: '口型振幅法',
        ok: maxLevel > 0.15 && maxLevel - minLevel > 0.1,
        detail: `level max=${maxLevel.toFixed(2)} min=${minLevel.toFixed(2)} before=${beforeAudio.toFixed(2)}`,
      });

      const target = capsNow.motionGroups.includes('touch_head')
        ? 'touch_head'
        : capsNow.motionGroups[0];
      if (target) {
        handles.motion.clearCooldown(target);
        const first = handles.motion.request(target, 'normal');
        const second = handles.motion.request(target, 'normal');
        out.push({
          name: '动作冷却去重',
          ok: first && !second,
          detail: `first=${first} second=${second}（${target}）`,
        });
      }

      const failed = out.filter((item) => !item.ok).length;
      setStatus(failed === 0 ? `自检通过（${out.length} 项）` : `自检失败 ${failed} 项`);
    } finally {
      setResults(out);
      setBusy(false);
    }
  }

  if (!handles) {
    return <p class="settings-status">模型还没准备好（window.mochi 不可用）</p>;
  }

  return (
    <>
      <p class="settings-hint">
        {caps
          ? `${caps.name} · 动作 ${caps.motionGroups.length} · 表情 ${caps.expressions.length} · 参数 ${caps.parameterCount}`
          : '模型未加载'}
        <br />
        嘴部参数：{caps?.mouthParamIds.join(', ') || '（模型未声明 LipSync）'}
        <br />
        命中区：{caps?.hitAreaNames.join(', ') || '（未定义，使用包围盒分区）'}
      </p>

      <details class="settings-motions" open>
        <summary>口型（振幅法）level={level.toFixed(2)} rms={rms.toFixed(3)}</summary>
        <div class="debug-meter">
          <div class="debug-meter-fill" style={{ width: `${Math.round(level * 100)}%` }} />
        </div>
        <div class="settings-motion-row">
          <button type="button" onClick={() => void handles.audio.playTestSequence()}>
            播放测试音频
          </button>
          <button type="button" onClick={() => handles.audio.stop()}>
            停止
          </button>
        </div>
      </details>

      <details class="settings-motions">
        <summary>动作队列：{motionStatus}</summary>
        <div class="settings-motion-row">
          <select value={motionName} onChange={(event) => setMotionName(event.currentTarget.value)}>
            {motions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        <div class="settings-motion-row">
          <button type="button" onClick={() => play('force')}>
            force
          </button>
          <button type="button" onClick={() => play('high')}>
            high
          </button>
          <button type="button" onClick={() => play('normal')}>
            normal
          </button>
        </div>
      </details>

      <details class="settings-motions">
        <summary>表情叠加：{activeExpressions}</summary>
        <div class="settings-motion-row">
          <select
            value={expressionName}
            onChange={(event) => setExpressionName(event.currentTarget.value)}
          >
            {expressions.length === 0 && <option value="">模型无表情文件</option>}
            {expressions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <input
            type="number"
            min="0"
            max="100"
            value={weight}
            onInput={(event) => setWeight(Number(event.currentTarget.value))}
          />
        </div>
        <div class="settings-motion-row">
          <button type="button" onClick={playExpression}>
            叠加
          </button>
          <button
            type="button"
            onClick={() => {
              handles.expression.releaseAll();
              setStatus('已释放全部表情');
            }}
          >
            释放全部
          </button>
        </div>
      </details>

      <label class="settings-checkbox">
        <input
          type="checkbox"
          checked={handles.gaze.isEnabled}
          onChange={(event) => handles.gaze.setEnabled(event.currentTarget.checked)}
        />
        <span>视线跟随鼠标（150ms 平滑）</span>
      </label>

      <div class="settings-actions">
        <button type="button" class="primary" disabled={busy} onClick={() => void runSelfCheck()}>
          {busy ? '自检中…' : '运行 S2 自检'}
        </button>
      </div>

      <p class="settings-status">{status}</p>

      {results.length > 0 && (
        <ul class="debug-results">
          {results.map((item) => (
            <li key={item.name} class={item.ok ? 'ok' : 'fail'}>
              {item.ok ? '✓' : '✗'} {item.name} — {item.detail}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

// ── 情感引擎面板（S3）────────────────────────────────────────────────────
function PadChart({ points }: { points: readonly EmotionSnapshot[] }) {
  const recent = points.slice(-240);
  if (recent.length < 2) {
    return <p class="settings-hint">还没有足够的 PAD 数据；说句话或在下方注入刺激。</p>;
  }
  const width = 520;
  const height = 150;
  const pad = 10;
  const t0 = Number(recent[0].ts ?? 0);
  const t1 = Number(recent[recent.length - 1].ts ?? t0 + 1);
  const x = (point: EmotionSnapshot, index: number): number => {
    if (t1 > t0) {
      return pad + ((Number(point.ts ?? t0) - t0) / (t1 - t0)) * (width - pad * 2);
    }
    return pad + (index / Math.max(1, recent.length - 1)) * (width - pad * 2);
  };
  const yValence = (value: number): number =>
    pad + (1 - (value + 1) / 2) * (height - pad * 2);
  const yUnit = (value: number): number => pad + (1 - value) * (height - pad * 2);
  const line = (
    getter: (point: EmotionSnapshot) => number,
    yGetter: (value: number) => number,
  ): string =>
    recent
      .map(
        (point, index) =>
          `${x(point, index).toFixed(1)},${yGetter(getter(point)).toFixed(1)}`,
      )
      .join(' ');
  const last = recent[recent.length - 1];
  return (
    <div class="emotion-chart-wrap">
      <svg class="emotion-chart" viewBox={`0 0 ${width} ${height}`} role="img">
        <line
          x1={pad}
          x2={width - pad}
          y1={yValence(0)}
          y2={yValence(0)}
          class="chart-grid"
        />
        <line x1={pad} x2={pad} y1={pad} y2={height - pad} class="chart-axis" />
        <polyline
          points={line((p) => p.pad.valence, yValence)}
          class="chart-line valence"
        />
        <polyline
          points={line((p) => p.pad.arousal, yUnit)}
          class="chart-line arousal"
        />
        <polyline
          points={line((p) => p.pad.dominance, yUnit)}
          class="chart-line dominance"
        />
      </svg>
      <div class="emotion-legend">
        <span class="valence">愉悦 {last.pad.valence.toFixed(2)}</span>
        <span class="arousal">唤醒 {last.pad.arousal.toFixed(2)}</span>
        <span class="dominance">支配 {last.pad.dominance.toFixed(2)}</span>
        <span class="emotion-chart-time">
          {formatClock(Number(recent[0].ts ?? 0))} – {formatClock(Number(last.ts ?? 0))}
        </span>
      </div>
    </div>
  );
}

function LabelTimeline({ points }: { points: readonly EmotionSnapshot[] }) {
  const recent = points.slice(-80);
  if (recent.length === 0) return <p class="settings-hint">暂无标签时间轴。</p>;
  const segments: { label: string; count: number; cause?: string }[] = [];
  for (const point of recent) {
    const label = point.label ?? 'neutral';
    const last = segments[segments.length - 1];
    const cause = point.causes?.[point.causes.length - 1];
    if (last && last.label === label) {
      last.count += 1;
      if (cause) last.cause = cause.stimulus;
    } else {
      segments.push({ label, count: 1, cause: cause?.stimulus });
    }
  }
  return (
    <div class="emotion-timeline">
      {segments.map((segment, index) => (
        <div
          key={`${segment.label}-${index}`}
          class="timeline-seg"
          style={{ flexGrow: segment.count, background: labelColor(segment.label) }}
          title={`${segment.label} × ${segment.count}${segment.cause ? ` · ${segment.cause}` : ''}`}
        >
          {segment.count > 3 ? segment.label : ''}
        </div>
      ))}
    </div>
  );
}

function EmotionTab() {
  const [emotion, setEmotion] = useState<EmotionSnapshot | null>(getEmotionSnapshot());
  const [points, setPoints] = useState<readonly EmotionSnapshot[]>(getEmotionPoints());
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [status, setStatus] = useState('加载情感目录…');
  const [busy, setBusy] = useState(false);
  const [injectTag, setInjectTag] = useState('user_praise');
  const [injectMagnitude, setInjectMagnitude] = useState(1);
  const [advanceSeconds, setAdvanceSeconds] = useState(3600);
  const [decay, setDecay] = useState(1);
  const [refractory, setRefractory] = useState(8);
  const [recovery, setRecovery] = useState(0);
  const [reactivity, setReactivity] = useState<Record<string, number>>({});

  useEffect(() => subscribeEmotion((snapshot, nextPoints) => {
    setEmotion(snapshot);
    setPoints(nextPoints);
  }), []);

  useEffect(() => {
    void refreshCatalog();
    void refreshHistory();
  }, []);

  async function refreshHistory(): Promise<void> {
    try {
      const response = await fetch(`${config.apiBase}/api/v1/emotion/history?limit=600`, {
        headers: apiHeaders(),
      });
      if (!response.ok) return;
      const data = (await response.json()) as { history: EmotionSnapshot[] };
      loadEmotionHistory(data.history ?? []);
    } catch (error) {
      console.warn('[emotion] history load failed', error);
    }
  }

  async function refreshCatalog(): Promise<void> {
    try {
      const response = await fetch(`${config.apiBase}/api/v1/emotion/catalog`, { headers: apiHeaders() });
      if (!response.ok) {
        setStatus('情感目录读取失败');
        return;
      }
      const data = (await response.json()) as Catalog;
      setCatalog(data);
      setDecay(data.persona.decay_multiplier);
      setRefractory(data.persona.refractory_seconds);
      setRecovery(data.persona.dominance_recovery);
      setReactivity({ ...data.persona.reactivity });
      setInjectTag((current) =>
        data.stimuli.some((item) => item.tag === current)
          ? current
          : (data.stimuli[0]?.tag ?? 'user_praise'),
      );
      setStatus(`已加载 ${data.labels.length} 个标签 / ${data.stimuli.length} 个刺激`);
    } catch (error) {
      setStatus(`情感目录读取失败：${String(error)}`);
    }
  }

  async function inject(): Promise<void> {
    if (busy) return;
    setBusy(true);
    try {
      const response = await fetch(`${config.apiBase}/api/v1/emotion/stimulus`, {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({ tag: injectTag, magnitude: injectMagnitude }),
      });
      if (!response.ok) {
        setStatus(`注入失败：HTTP ${response.status}`);
        return;
      }
      const snapshot = (await response.json()) as EmotionSnapshot;
      ingestEmotion(snapshot);
      setStatus(`已注入 ${injectTag} × ${injectMagnitude} → ${snapshot.label}`);
    } catch (error) {
      setStatus(`注入失败：${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function advance(): Promise<void> {
    if (busy) return;
    setBusy(true);
    try {
      const response = await fetch(`${config.apiBase}/api/v1/emotion/advance`, {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({ seconds: advanceSeconds }),
      });
      if (!response.ok) {
        setStatus(`时间旅行失败：HTTP ${response.status}`);
        return;
      }
      const snapshot = (await response.json()) as EmotionSnapshot;
      ingestEmotion(snapshot);
      await refreshHistory();
      setStatus(
        `已推进 ${advanceSeconds}s → ${snapshot.label}` +
          (snapshot.pending_greeting ? `（待播放 ${snapshot.pending_greeting}）` : ''),
      );
    } catch (error) {
      setStatus(`时间旅行失败：${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function applyPersona(): Promise<void> {
    if (busy) return;
    setBusy(true);
    try {
      const response = await fetch(`${config.apiBase}/api/v1/emotion/persona`, {
        method: 'PATCH',
        headers: apiHeaders(),
        body: JSON.stringify({
          reactivity,
          decay_multiplier: decay,
          refractory_seconds: refractory,
          dominance_recovery: recovery,
        }),
      });
      if (!response.ok) {
        setStatus(`人格参数保存失败：HTTP ${response.status}`);
        return;
      }
      const data = (await response.json()) as { persona: PersonaView };
      setCatalog((current) => (current ? { ...current, persona: data.persona } : current));
      setStatus('人格参数已即时生效（下一轮对话使用）');
    } catch (error) {
      setStatus(`人格参数保存失败：${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function savePersona(): Promise<void> {
    if (busy) return;
    setBusy(true);
    try {
      const response = await fetch(`${config.apiBase}/api/v1/emotion/persona/save`, {
        method: 'POST',
        headers: apiHeaders(),
      });
      if (!response.ok) {
        setStatus(`写回角色卡失败：HTTP ${response.status}`);
        return;
      }
      const data = (await response.json()) as { saved: string; backup: string };
      setStatus(`已写回 ${data.saved}（备份 ${data.backup}）`);
    } catch (error) {
      setStatus(`写回角色卡失败：${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function exportTrace(): Promise<void> {
    try {
      const response = await fetch(`${config.apiBase}/api/v1/emotion/export?limit=1200`, {
        headers: apiHeaders(),
      });
      if (!response.ok) {
        setStatus(`导出失败：HTTP ${response.status}`);
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'mochi-emotion-trace.json';
      anchor.click();
      URL.revokeObjectURL(url);
      setStatus('轨迹已导出');
    } catch (error) {
      setStatus(`导出失败：${String(error)}`);
    }
  }

  const currentLabel = emotion?.label ?? 'neutral';
  const causes = [...(emotion?.causes ?? [])].slice(-6).reverse();
  const possible = (catalog?.transitions ?? []).filter(
    (item) => item.from.includes(currentLabel) || item.from.includes('*'),
  );
  const currentDef = catalog?.labels.find((item) => item.name === currentLabel);
  const pad = emotion?.pad ?? { valence: 0.1, arousal: 0.35, dominance: 0.55 };

  return (
    <>
      <div class="emotion-summary">
        <div class="emotion-current">
          <span class="emotion-badge" style={{ background: labelColor(currentLabel) }}>
            {currentLabel}
          </span>
          {emotion?.secondary_label && (
            <span class="emotion-secondary">+ {emotion.secondary_label}</span>
          )}
          <div class="emotion-meta">
            <span>强度 {(emotion?.intensity ?? 0).toFixed(2)}</span>
            <span>闲置 {(emotion?.idle_seconds ?? 0).toFixed(0)}s</span>
            <span>亲密 {(emotion?.affinity ?? 0).toFixed(2)}</span>
            <span>信任 {(emotion?.trust ?? 0).toFixed(2)}</span>
          </div>
        </div>
        <div class="emotion-bars">
          <PADBar label="V" value={pad.valence} color="#5b8def" bipolar />
          <PADBar label="A" value={pad.arousal} color="#e8a33d" />
          <PADBar label="D" value={pad.dominance} color="#49a078" />
          {currentDef && <span class="emotion-tau">τ={currentDef.tau}s</span>}
        </div>
      </div>

      <PadChart points={points} />
      <LabelTimeline points={points} />

      <div class="emotion-controls">
        <details class="settings-motions" open>
          <summary>刺激注入器</summary>
          <div class="settings-motion-row">
            <select value={injectTag} onChange={(event) => setInjectTag(event.currentTarget.value)}>
              {(catalog?.stimuli ?? []).map((item) => (
                <option key={item.tag} value={item.tag}>
                  {item.tag}（{item.category}）
                </option>
              ))}
            </select>
            <input
              type="number"
              min="0"
              max="3"
              step="0.1"
              value={injectMagnitude}
              onInput={(event) => setInjectMagnitude(Number(event.currentTarget.value))}
            />
            <button type="button" disabled={busy} onClick={() => void inject()}>
              注入
            </button>
          </div>
        </details>

        <details class="settings-motions">
          <summary>时间旅行（{advanceSeconds}s）</summary>
          <div class="settings-motion-row">
            <input
              type="number"
              min="1"
              step="60"
              value={advanceSeconds}
              onInput={(event) => setAdvanceSeconds(Number(event.currentTarget.value))}
            />
            <button type="button" disabled={busy} onClick={() => void advance()}>
              推进
            </button>
            <button type="button" disabled={busy} onClick={() => void exportTrace()}>
              导出轨迹
            </button>
          </div>
        </details>
      </div>

      <details class="settings-motions">
        <summary>人格滑杆（即时生效）</summary>
        {(["praise", "insult", "tease"] as const).map((key) => (
          <label class="emotion-slider" key={key}>
            <span>
              {key} 反应增益 <b>{(reactivity[key] ?? 1).toFixed(2)}</b>
            </span>
            <input
              type="range"
              min="0.2"
              max="2"
              step="0.05"
              value={reactivity[key] ?? 1}
              onInput={(event) =>
                setReactivity({ ...reactivity, [key]: Number(event.currentTarget.value) })
              }
            />
          </label>
        ))}
        <label class="emotion-slider">
          <span>
            衰减倍率 <b>{decay.toFixed(2)}</b>
          </span>
          <input
            type="range"
            min="0.5"
            max="2"
            step="0.05"
            value={decay}
            onInput={(event) => setDecay(Number(event.currentTarget.value))}
          />
        </label>
        <label class="emotion-slider">
          <span>
            不应期 <b>{refractory.toFixed(0)}s</b>
          </span>
          <input
            type="range"
            min="0"
            max="30"
            step="1"
            value={refractory}
            onInput={(event) => setRefractory(Number(event.currentTarget.value))}
          />
        </label>
        <label class="emotion-slider">
          <span>
            支配恢复 <b>{recovery.toFixed(3)}</b>
          </span>
          <input
            type="range"
            min="0"
            max="0.05"
            step="0.001"
            value={recovery}
            onInput={(event) => setRecovery(Number(event.currentTarget.value))}
          />
        </label>
        <div class="settings-actions">
          <button type="button" class="primary" disabled={busy} onClick={() => void applyPersona()}>
            应用
          </button>
          <button type="button" disabled={busy} onClick={() => void savePersona()}>
            写回角色卡
          </button>
          <button type="button" disabled={busy} onClick={() => void refreshCatalog()}>
            重读目录
          </button>
        </div>
      </details>

      <div class="emotion-grid">
        <details class="settings-motions" open>
          <summary>状态机：从 {currentLabel} 出发</summary>
          <ul class="emotion-list">
            {possible.length === 0 && <li class="settings-hint">无显式规则（默认允许）</li>}
            {possible.slice(0, 8).map((item, index) => (
              <li key={`${item.to}-${index}`}>
                → <b>{item.to}</b>
                {item.guards.length > 0 && <span>（{item.guards.join(', ')}）</span>}
              </li>
            ))}
          </ul>
        </details>
        <details class="settings-motions" open>
          <summary>触发源（最近 6 条）</summary>
          <ul class="emotion-list">
            {causes.length === 0 && <li class="settings-hint">暂无</li>}
            {causes.map((cause, index) => (
              <li key={`${cause.ts}-${index}`}>
                <span class="cause-time">{formatClock(cause.ts)}</span> {cause.stimulus}
                <span class="cause-delta">
                  {' '}
                  Δv {cause.delta.valence.toFixed(2)} / Δa {cause.delta.arousal.toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      </div>

      <p class="settings-status">{status}</p>
    </>
  );
}

function PADBar({
  label,
  value,
  color,
  bipolar = false,
}: {
  label: string;
  value: number;
  color: string;
  bipolar?: boolean;
}) {
  const percent = bipolar ? ((value + 1) / 2) * 100 : value * 100;
  return (
    <div class="pad-bar">
      <span>{label}</span>
      <div class="pad-track">
        <div class="pad-fill" style={{ width: `${Math.max(0, Math.min(100, percent))}%`, background: color }} />
      </div>
      <b>{value.toFixed(2)}</b>
    </div>
  );
}

export function DevPanel({ onClose }: Props) {
  const [tab, setTab] = useState<Tab>('performance');
  const handles = getHandles();

  return (
    <div class="settings-mask" onClick={onClose}>
      <div class="settings-panel debug-panel" onClick={(event) => event.stopPropagation()}>
        <header>
          <h2>调试面板</h2>
          <button type="button" class="settings-close" onClick={onClose}>
            ×
          </button>
        </header>
        <div class="debug-tabs">
          <button
            type="button"
            class={tab === 'performance' ? 'active' : ''}
            onClick={() => setTab('performance')}
          >
            表现 / Live2D
          </button>
          <button
            type="button"
            class={tab === 'emotion' ? 'active' : ''}
            onClick={() => setTab('emotion')}
          >
            情感 / PAD
          </button>
        </div>
        {tab === 'performance' ? <PerformanceTab handles={handles} /> : <EmotionTab />}
      </div>
    </div>
  );
}

export function mountDevPanel(root: HTMLElement): () => void {
  render(<DevPanel onClose={() => render(null, root)} />, root);
  return () => render(null, root);
}
