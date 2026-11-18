import {build} from 'esbuild';
import {writeFile} from 'node:fs/promises';
import {scenarios,simulations} from './plan-scenarios.mjs';

const compile = async path => {
  const result = await build({entryPoints:[path],bundle:true,write:false,format:'esm',platform:'node'});
  return (await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`)).describePlan;
};
const describe = await compile('src/plan.ts');
const previous = process.argv[2] ? await compile(process.argv[2]) : null;
let simulated = 0;
for (const s of simulations()) { describe(s.operations,s.limits,s.compression); simulated++; }
const report = ['# Output plan examples','',`Reviewed ${scenarios.length} representative scenarios and generated ${simulated.toLocaleString('en-US')} plans: all 781 step combinations through four steps, across four output formats and three limit configurations. The UI tests check ordering, row preservation, fixed counts, and compression across this matrix. Regenerate with \`cd ui && npm run simulate:plan\`. These descriptions use configuration only; they do not predict data-dependent file counts.`,''];
for (const s of scenarios) {
  const pipeline = s.operations.map(op => op.type === 'shuffle' ? `shuffle (${op.strategy})` : op.type).join(' → ') || 'no steps';
  report.push(`## ${s.name}`,'',`Pipeline: ${pipeline}. Limits: rows=${s.limits.rows || 'none'}, bytes=${s.limits.bytes || 'none'}, compressed=${s.limits.compressed || 'none'}. Compression: ${s.compression}.`,'');
  if (previous) report.push('Before:','',previous(s.operations,s.limits,s.compression),'','After:','');
  report.push(describe(s.operations,s.limits,s.compression),'');
}
await writeFile(previous ? '../scratch/output-plan-comparison.md' : '../docs/output-plan-examples.md',report.join('\n'));
console.log(`Wrote ${scenarios.length} examples; generated ${simulated.toLocaleString('en-US')} plans.`);
