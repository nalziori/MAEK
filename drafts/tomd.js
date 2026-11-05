const fs=require('fs');
const html=fs.readFileSync(process.argv[2],'utf8');
const m=html.match(/var TYPES = (\{[\s\S]*?\});\s*var DATA = (\[[\s\S]*?\]);\s*function esc/);
const TYPES=eval('('+m[1]+')'), DATA=eval('('+m[2]+')');
let o=['# 포스코 제철소 안전사고 아카이브','','포항·광양제철소에서 2018~2026년 보도된 안전사고 22건(사망 20명, 그중 협력·하청·용역 16명)을 기사·보도자료 링크와 함께 정리했습니다. 언론 보도 기준 집계이며 공식 통계가 아닙니다. 조사일 2026-11-04.',''];
let year='';
for(const it of [...DATA].sort((a,b)=>b.d.localeCompare(a.d))){
  const y=it.d.slice(0,4); if(y!==year){year=y;o.push('## '+y,'');}
  const sev=it.deaths>0?`사망 ${it.deaths}`+(it.injured?` · 부상 ${it.injured}`:''):(it.injured?`부상 ${it.injured}`:'인명피해 없음');
  o.push(`### ${it.date} ${it.site} · ${it.title}`,'',`- **피해:** ${sev} (${it.who})`,`- **유형:** ${it.types.map(t=>TYPES[t].label).join(', ')}`+(it.flag?` · ${it.flag}`:''),`- **장소:** ${it.place}`,`- **경위:** ${it.summary}`);
  if(it.issue)o.push(`- **원인·쟁점:** ${it.issue}`);
  if(it.follow)o.push(`- **후속 조치:** ${it.follow}`);
  o.push('- **자료:**');
  for(const s of it.src)o.push(`  - [${s[2]}](${s[3]}) · ${s[0]}${s[1]?' '+s[1]:''}`);
  o.push('');
}
fs.writeFileSync(process.argv[3],o.join('\n'));
