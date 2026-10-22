import assert from 'node:assert/strict';
import test from 'node:test';
import { HalfDuplex } from '../src/audio/HalfDuplex.ts';

test('legal transitions follow the five-state machine', () => {
  const machine = new HalfDuplex();
  assert.equal(machine.transition('listening'), true);
  assert.equal(machine.transition('thinking'), true);
  assert.equal(machine.transition('speaking'), true);
  assert.equal(machine.transition('interrupted'), true);
  assert.equal(machine.transition('idle'), true);
  assert.equal(machine.state, 'idle');
});

test('illegal transitions are rejected', () => {
  const machine = new HalfDuplex();
  // idle → speaking 合法：文字对话的服务端 TTS 可以直接开口
  assert.equal(machine.transition('speaking'), true);
  machine.transition('interrupted');
  machine.transition('idle');
  machine.transition('listening');
  assert.equal(machine.transition('speaking'), false);
  machine.transition('thinking');
  assert.equal(machine.transition('listening'), false);
  machine.transition('speaking');
  assert.equal(machine.transition('listening'), false);
});

test('canStartListening only in idle/interrupted', () => {
  const machine = new HalfDuplex();
  assert.equal(machine.canStartListening, true);
  machine.transition('listening');
  assert.equal(machine.canStartListening, false);
  machine.transition('thinking');
  assert.equal(machine.canStartListening, false);
  machine.transition('speaking');
  assert.equal(machine.canStartListening, false);
  machine.transition('interrupted');
  assert.equal(machine.canStartListening, true);
});

test('subscribers see every accepted transition', () => {
  const machine = new HalfDuplex();
  const seen: string[] = [];
  machine.subscribe((state) => seen.push(state));
  machine.transition('listening');
  machine.transition('thinking');
  assert.deepEqual(seen, ['idle', 'listening', 'thinking']);
});
