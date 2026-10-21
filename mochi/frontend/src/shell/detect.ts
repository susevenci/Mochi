import type { ShellAdapter } from './ShellAdapter';
import { TauriAdapter } from './TauriAdapter';
import { WebAdapter } from './WebAdapter';

export function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

export function detectShell(): ShellAdapter {
  return isTauri() ? new TauriAdapter() : new WebAdapter();
}
