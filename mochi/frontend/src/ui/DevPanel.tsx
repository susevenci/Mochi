import { render } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import type { AudioPlayer } from '../live2d/AudioPlayer';
import type { ExpressionController } from '../live2d/ExpressionController';
import type { GazeController } from '../live2d/GazeController';
import type { IdleController } from '../live2d/IdleController';
import type { LipSync } from '../live2d/LipSync';
import type { Live2DStage } from '../live2d/Live2DStage';
import type { MotionController, MotionPriority } from '../live2d/MotionController';

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

function getHandles(): DebugHandles | null {
  const mochi = (window as unknown as { mochi?: Partial<DebugHandles> }).mochi;
  if (!mochi?.live2d || !mochi.motion || !mochi.expression || !mochi.lipSync) return null;
  if (!mochi.idle || !mochi.gaze || !mochi.audio) return null;
  return mochi as DebugHandles;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
}

/**
 * S2 调试面板（T2-14 取证工具）。
 *
 * 三件事：① 实时看参数/电平 ② 手动触发动作与表情 ③ 一键自检，
 * 把"静置不静止、口型随音量、动作去重"这些验收口径变成可截图的结果。
 */
export function DevPanel({ onClose }: Props) {
  const handles = getHandles();
  const [level, setLevel] = useState(0);
  const [rms, setRms] = useState(0);
  const [motionName, setMotionName] = useState('');
  const [expressionName, setExpressionName] = useState('');
  const [weight, setWeight] = useState(100);
  const [status, setStatus] = useState('就绪');
  const [results, setResults] = useState<CheckResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [motionStatus, setMotionStatus] = useState('idle');
  const [activeExpressions, setActiveExpressions] = useState<string>('');
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

  if (!handles) {
    return (
      <div class="settings-mask" onClick={onClose}>
        <div class="settings-panel">
          <header>
            <h2>S2 调试面板</h2>
            <button type="button" class="settings-close" onClick={onClose}>
              ×
            </button>
          </header>
          <p class="settings-status">模型还没准备好（window.mochi 不可用）</p>
        </div>
      </div>
    );
  }

  const caps = handles.live2d.caps;
  const motions = handles.live2d.getMotionNames();
  const expressions = handles.live2d.getExpressionNames();

  function play(priority: MotionPriority): void {
    if (!motionName) return;
    const ok = handles!.motion.request(motionName, priority);
    // 冷却期内的请求会被拒绝，这不是错误，但要让人看见
    setStatus(`request(${motionName}, ${priority}) → ${ok ? 'accepted' : 'rejected(cooldown)'}`);
  }

  function playExpression(): void {
    if (!expressionName) return;
    handles!.expression.play(expressionName, weight / 100, { fadeMs: 300 });
    setStatus(`expression ${expressionName} weight=${(weight / 100).toFixed(2)}`);
  }

  async function runSelfCheck(): Promise<void> {
    if (busy) return;
    setBusy(true);
    const out: CheckResult[] = [];
    try {
      const capsNow = handles!.live2d.caps;
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

      // 静置不静止：呼吸/微摆在 1.5s 内必须有变化
      const breathStart = handles!.live2d.getParameter('ParamBreath');
      const bodyStart = handles!.live2d.getParameter('ParamBodyAngleX');
      await sleep(1500);
      const breathEnd = handles!.live2d.getParameter('ParamBreath');
      const bodyEnd = handles!.live2d.getParameter('ParamBodyAngleX');
      const breathDelta = Math.abs(breathEnd - breathStart);
      const bodyDelta = Math.abs(bodyEnd - bodyStart);
      out.push({
        name: '待机（呼吸/微摆）',
        ok: breathDelta > 0.01 || bodyDelta > 0.01,
        detail: `Δbreath=${breathDelta.toFixed(3)} Δbody=${bodyDelta.toFixed(3)}`,
      });

      // 眨眼：6s 内至少闭眼一次
      let minEye = 1;
      const blinkStart = performance.now();
      while (performance.now() - blinkStart < 6000) {
        minEye = Math.min(minEye, handles!.live2d.getParameter('ParamEyeLOpen'));
        await sleep(80);
      }
      out.push({
        name: '眨眼',
        ok: minEye < 0.5,
        detail: `minEyeOpen=${minEye.toFixed(2)}（6s 采样）`,
      });

      // 口型：播测试音，电平必须有起伏
      const beforeAudio = handles!.lipSync.level;
      await handles!.audio.playTestSequence();
      let maxLevel = 0;
      let minLevel = 1;
      const lipStart = performance.now();
      while (performance.now() - lipStart < 3000) {
        maxLevel = Math.max(maxLevel, handles!.lipSync.level);
        minLevel = Math.min(minLevel, handles!.lipSync.level);
        await sleep(60);
      }
      handles!.audio.stop();
      out.push({
        name: '口型振幅法',
        ok: maxLevel > 0.15 && maxLevel - minLevel > 0.1,
        detail: `level max=${maxLevel.toFixed(2)} min=${minLevel.toFixed(2)} before=${beforeAudio.toFixed(2)}`,
      });

      // 动作去重：同一动作 10s 内第二次应被拒绝（force 除外）
      const target = capsNow.motionGroups.includes('touch_head')
        ? 'touch_head'
        : capsNow.motionGroups[0];
      if (target) {
        handles!.motion.clearCooldown(target);
        const first = handles!.motion.request(target, 'normal');
        const second = handles!.motion.request(target, 'normal');
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

  return (
    <div class="settings-mask" onClick={onClose}>
      <div class="settings-panel debug-panel" onClick={(event) => event.stopPropagation()}>
        <header>
          <h2>S2 调试面板</h2>
          <button type="button" class="settings-close" onClick={onClose}>
            ×
          </button>
        </header>

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
                handles!.expression.releaseAll();
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
      </div>
    </div>
  );
}

export function mountDevPanel(root: HTMLElement): () => void {
  render(<DevPanel onClose={() => render(null, root)} />, root);
  return () => render(null, root);
}
