"""Record structural calls exercised by the existing Python tests and grammar samples."""
import check_reference
import dataclasses,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];CORE=ROOT.parent/'core';sys.path.insert(0,str(CORE))
from understand_core import structure
from understand_core.extract_structure import build_result,count_lines
original=structure.analyze_file;calls=structure.extract_call_graph
samples={}
def capture(path,source):
    result=original(path,source)
    samples[path,source]=dict(path=path,source=source,analysis=dataclasses.asdict(result) if result is not None else None,calls=calls(path,source))
    return result
structure.analyze_file=capture
import pytest
assert pytest.main([str(CORE/'tests/test_extract_structure.py'),str(CORE/'tests/test_fingerprints.py'),'-q'])==0
extra={
'a.ts':'''import X, {foo as bar} from "./x";\nexport default class Widget { value: string; run(x: string): void { bar(x); } }\nexport const fn = (a: number, ...rest: string[]) => X(a);\nexport {fn as alias};\n''',
'a.tsx':'''export function App() { return <button onClick={() => clicked()}>Hello</button>; }\n''',
'a.js':'''import * as utils from './utils';\nexport default function render(a) { return utils.f(a); }\nconst run = function(x) { return render(x); };\n''',
'a.rs':'''use crate::util::{self, help};\npub struct Data { pub value: i32 }\npub enum Color { Red, Blue }\npub trait Act { fn run(&self); fn other(&self) { help(); } }\nimpl Data { pub fn run(&self, x: i32) -> i32 { self.value + helper(x) } }\nfn helper(x: i32) -> i32 { x }\n''',
'a.java':'''import java.util.List;\npublic class App { public int value; public App(int x) { value = x; } public String run(String s) { return helper(s); } }\npublic interface Act { void run(); int X = 1; }\n''',
'a.kt':'''import example.util.help as helper\nclass App(val value: String) { fun run(x: Int): String { return helper(x) } val size = 1 }\nprivate fun hidden() { println("hi") }\nobject Util { fun help() { other() } }\n''',
'a.cs':'''using System.Text;\nnamespace Example { public class App { public int value; public string Name { get; set; } public App() { var x = new App(); } public void Run(int x) { Helper(x); } } public interface IAct { void Run(); int Value { get; } } }\n''',
'a.php':'''<?php\nnamespace Example { use Lib\\Thing; function top($x): string { return helper($x); } class App { public $value; function run($x) { $this->help($x); Thing::call(); } } interface Act { function run(); } }\n''',
'a.rb':'''require_relative "helper"\ndef top(x, *args, **kw, &block)\n  helper(x)\nend\nclass App\n  attr_accessor :value\n  def run(x)\n    self.help(x)\n  end\n  def self.build\n    new\n  end\nend\n''',
'a.c':'''#include "helpers.h"\nstruct Data { int value; };\nstatic int hidden(int x) { return helper(x); }\nint run(int *value) { return hidden(*value); }\n''',
'a.cpp':'''#include <vector>\nnamespace app { class App { public: int value; int run(int x) { return helper(x); } }; int App::helper(int x) { return other(x); } }\n''',
}
for path,source in extra.items():capture(path,source)
for sample in samples.values():
    file=dict(path=sample['path'],language=None,fileCategory='code')
    a=original(sample['path'],sample['source']);total,nonempty=count_lines(sample['source'])
    sample['result']=build_result(file,total,nonempty,a,sample['calls'],{sample['path']:[]})
(ROOT/'tests/fixtures/structure.json').write_text(json.dumps(list(samples.values()),indent=2)+'\n')
print(len(samples),'structural fixtures')
