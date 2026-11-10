// AES-128-ECB / PKCS7 / base64 — 复刻 ibrain-mm-cli src/auth/aes.ts。
// 用 stdin 收明文（避免明文出现在 argv / ps）。stdout 是 base64 密文。
import { createCipheriv } from 'node:crypto';

const KEY = Buffer.from('HGY12345HGY12345', 'utf8');

let plain = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (d) => { plain += d; });
process.stdin.on('end', () => {
  const cipher = createCipheriv('aes-128-ecb', KEY, null);
  const out = Buffer.concat([cipher.update(plain, 'utf8'), cipher.final()]);
  process.stdout.write(out.toString('base64'));
});
