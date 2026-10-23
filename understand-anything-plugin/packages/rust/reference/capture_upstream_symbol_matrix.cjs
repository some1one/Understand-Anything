const fs = require('fs');
const vm = require('vm');
// Capture upstream source/status assertions without loading its removed TS engine.
// Usage: node capture_upstream_symbol_matrix.cjs <upstream-test.mjs> <output.json>
if (process.argv.length !== 4) throw new Error('Expected upstream test and output paths');
let source = fs.readFileSync(process.argv[2], 'utf8');
const sourceSha256 = require('crypto').createHash('sha256').update(source).digest('hex');
if (sourceSha256 !== 'f32e28abb56e2be6d4a5486e5a5253e164d63eda4ce378adc1a342b9de617526') throw new Error('Upstream matrix changed; audit cases and native differences before regenerating');
source = source.replace(/^import .*;\n/gm,'').replace(/let parser;[\s\S]*?const oldSource =/, 'const oldSource =');
const start=source.indexOf('function classify('), end=source.indexOf('\nconst matrix =',start);
source=source.slice(0,start)+`function classify(extension,currentSource,options={}) {
 const family=['ts','tsx','js','jsx'].includes(extension)?'ts':extension;
 const testCase={extension,currentSource,beforeSource:options.beforeSource??oldSource[family],name:options.name??'A.run',newNodes:options.newNodes??[],oldExtra:options.oldExtra??{}};
 return {result:{missing:[{status:{testCase},evidence:[]}]},after:{symbolEvidence:{coverage:{gaps:[]}}}};
}
`+source.slice(end);
const cases=[],skipped=[];let title='';
function test(label,fn,args=[]) { if(fn.toString().includes('compareFileSymbols(')) {skipped.push(label);return;} title=label;fn(...args); }
function it(label,fn){test(label,fn);}
it.each=rows=>(label,fn)=>rows.forEach(row=>test(label,fn,Array.isArray(row)?row:[row]));
function expect(actual){return {toBe(expected){if(actual?.testCase)cases.push({...actual.testCase,expected,test:title});},toContainEqual(){}};}
expect.objectContaining=x=>x;
vm.runInNewContext(source,{it,describe:(_,fn)=>fn(),expect});
for (const [index, testCase] of cases.entries()) {
 if (testCase.expected === 'unknown' && testCase.test === 'retains classes and methods rewritten as %s class expressions') {
  testCase.rustExpected = 'still-present';
  testCase.difference = 'Rust inventories directly bound class expressions and their methods.';
 }
 if (index === 360) {
  testCase.rustExpected = 'still-present';
  testCase.difference = 'Rust inventories generator function declarations.';
 }
 if (index === 152) {
  testCase.rustExpected = 'deleted';
  testCase.difference = 'Rust retains the exact N::A receiver qualifier in scoped callable evidence; its removal is verifiable.';
 }
}
fs.writeFileSync(process.argv[3],JSON.stringify({upstream:'e24fcf6',sourceSha256,source:'tests/skill/understand/test_symbol_evidence_matrix.test.mjs',skipped,cases},null,2)+'\n');
console.log(JSON.stringify({cases:cases.length,skipped}));
