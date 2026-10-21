// 前端侧 ULID：与后端同构，保证消息 id 时间有序（计划书 6.1）。
const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

export function ulid(): string {
  const time = Date.now();
  const random = crypto.getRandomValues(new Uint8Array(10));
  let value = (BigInt(time) << 80n) | BigInt('0x' + Array.from(random, (b) => b.toString(16).padStart(2, '0')).join(''));
  const chars: string[] = [];
  for (let i = 0; i < 26; i += 1) {
    chars.push(ALPHABET[Number(value & 0x1fn)]);
    value >>= 5n;
  }
  return chars.reverse().join('');
}
