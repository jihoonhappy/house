// 대시보드 검증 — 브라우저 없이 페이지 JS를 실제로 실행해 확인한다.
//   node tools/verify_dashboard.mjs [html경로]
// 헤더/셀 개수가 어긋나면 표 전체가 한 칸씩 밀린다. 실제로 두 번 발생한 버그다.
// 파이썬 테스트는 정적 HTML만 보므로, JS로 생성되는 그룹 열까지 보려면 이 스크립트가 필요하다.

import { readFileSync } from 'fs';
const target = process.argv[2] ?? 'docs/index.html';
const html = readFileSync(target, 'utf8');

// 페이지가 실제로 쓰는 값 그대로 추출
const GROUPS = JSON.parse(html.match(/const GROUPS = (\[.*?\]);/s)[1]);
const DATA = JSON.parse(html.match(/const DATA = (\[.*?\]);\n/s)[1].replace(/\\u003c/g, '<'));
const c = DATA[0];

// --- 1) 정적 헤더 개수 ---
const thead = html.match(/<thead>.*?<\/thead>/s)[0];
const staticTh = [...thead.matchAll(/<th\b[^>]*>.*?<\/th>/gs)].length;

// --- 2) 헤더 삽입 코드가 만드는 헤더 (페이지의 템플릿 문자열 그대로) ---
const headerHtml = [...GROUPS].reverse().map(g =>
  `<th class="grp-h" data-k="score_${g.key}">${g.label}<span class="sub">/${g.max}</span></th>`);

// --- 3) 행 셀: 페이지의 행 템플릿을 그대로 평가 ---
const esc = s => String(s ?? '').replace(/[&<>"']/g, x =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[x]));
const eok = mw => (mw / 10000).toFixed(2).replace(/0$/, '') + '억';
const n = v => v == null ? '<span class="far">-</span>' : v;
const m = v => v == null ? '<span class="far">-</span>' : v + 'm';
const links = () => '<span class="links"><a>네이버</a></span>';
const pct = v => v == null ? '' : (v > 0 ? '+' : '') + v.toFixed(1) + '%';
// 페이지의 spark()를 그대로 가져와 실행한다
const sparkSrc = html.match(/function spark\(series\) \{[\s\S]*?\n\}/)[0];
globalThis.spark = eval(`(${sparkSrc.replace(/^function spark/, 'function')})`);
const mixed = (c.complex_type || '').includes('주상복합');

const rowTpl = html.match(/return `(<tr data-i=.*?<\/tr>)`;/s)[1];
const row = eval('`' + rowTpl.replace(/\$\{i\}/g, '0') + '`');
const cells = [...row.matchAll(/<td\b[^>]*>.*?<\/td>/gs)].length;

console.log(`정적 헤더            ${staticTh}개`);
console.log(`동적 헤더(그룹)       ${headerHtml.length}개  ${GROUPS.map(g=>g.label+'/'+g.max).join(' ')}`);
console.log(`헤더 합계            ${staticTh + headerHtml.length}개`);
console.log(`행 셀(그룹 포함)      ${cells}개`);
const ok = staticTh + headerHtml.length === cells;
console.log(ok ? '\n[OK] 헤더와 셀 개수 일치' : '\n[FAIL] 헤더와 셀 개수 불일치');
if (!ok) process.exitCode = 1;

// --- 4) 그룹 점수 합 = 총점 검증 ---
let bad = 0;
for (const x of DATA) {
  const sum = GROUPS.reduce((a, g) => a + (x['score_' + g.key] ?? 0), 0);
  if (Math.abs(sum - x.score) > 0.35) bad++;
}
console.log(`그룹 합 = 총점 검증: ${DATA.length - bad}/${DATA.length}곳 일치`);
if (bad) process.exitCode = 1;
console.log('\n렌더된 첫 행 셀 내용:');
[...row.matchAll(/<td\b[^>]*>(.*?)<\/td>/gs)].forEach((mm, i) =>
  console.log(`  ${String(i+1).padStart(2)}. ${mm[1].replace(/<[^>]*>/g,'').trim().slice(0,34)}`));
