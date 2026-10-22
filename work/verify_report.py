from __future__ import annotations

import contextlib
from copy import deepcopy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
WORK = BASE/'work'/'verify_report'/f'run_{time.time_ns()}'
WORK.mkdir(parents=True,exist_ok=True)

def module(name,path):
    spec = importlib.util.spec_from_file_location(name,path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result

report = module('rps_report',BASE/'outputs'/'rps_report.py')
sim = module('sim_report_under_test',BASE/'outputs'/'rps_simulator.py')
checks = 0

def check(value,message):
    global checks
    assert value,message
    checks += 1

def same(a,b,message):
    check(a==b,f'{message}: {a!r} vs {b!r}')

SOURCES = ['summary.json','rankings.csv','stage_rankings.csv','matches.csv','rounds.csv',
           'player_summary.csv','strategy_summary.csv','stage_summary.csv']
def hashes(directory):
    return {name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in SOURCES}

name = '中文 </script><script>globalThis.__rpsInjected=1</script> & < > " \'\n\u2028\u2029 end'
group_name = '<img src=x onerror="globalThis.__rpsInjected=2">'
stage_name = '<svg onload="globalThis.__rpsInjected=3">决赛'
raw = {'name':name,'seed':877,'runs':2,
       'groups':[{'name':group_name,'count':2,'strategy':{'type':'fixed','hand':'scissors'}},
                 {'name':'纸牌组','count':2,'strategy':{'type':'cycle','sequence':['paper','rock','scissors']}}],
       'scoring':{'win':'1e100','draw':'0.1','loss':'-0.02','hand_bonus':{'scissors':'1e-100'}},
       'stages':[{'name':stage_name,'rounds':3,'advance':1}]}
settings = sim.parse_config(raw)
t,players,groups,stages = sim.simulate(settings)
data_dir = WORK/'中文 有空格 的结果'
sim.export_results(settings,data_dir,t,players,groups,stages)
before = hashes(data_dir)
check(not (data_dir/'report.html').exists(),'export API only creates data')

stub = WORK/'stub_template.html'
stub.write_text('<!doctype html><html><meta charset="utf-8"><script id="report-data" type="application/json">'
                '__RPS_REPORT_DATA__</script><div id="root"></div></html>',encoding='utf-8')
loaded = report.load_report_data(data_dir)
same(loaded['meta']['title'],name,'title exact')
same(loaded['meta']['runs'],2,'runs metadata')
same(len(loaded['matches']),6,'first-run records only')
same(sum(int(row['qualifications']) for row in loaded['players']),2,'all-run aggregate count')
for key in report.CSV_TABLES:
    check(all(isinstance(value,str) for row in loaded[key] for value in row.values()),'CSV fields remain strings')
same(loaded['groups'][0]['group'],group_name,'CSV BOM and dangerous name read exactly')
check(len(loaded['groups'][0]['total_points'])>100,'large/tiny score string retained')
encoded = report.embedded_json(loaded)
same(json.loads(encoded),loaded,'embedded JSON lossless')
check('<' not in encoded and '>' not in encoded and '&' not in encoded,'HTML delimiters escaped')
check('\u2028' not in encoded and '\u2029' not in encoded,'literal JS line separators escaped')
check('\\u003c/script' in encoded,'closing script escaped')
same(report.build_report(data_dir,template_path=stub),data_dir.resolve()/'report.html','default absolute report path')
html = (data_dir/'report.html').read_text(encoding='utf-8')
same(html.count('<script'),1,'payload creates no script element')
same(html.count('</script>'),1,'payload cannot close the data script')
extracted = re.search(r'<script[^>]*>(.*?)</script>',html,re.S).group(1)
same(json.loads(extracted),loaded,'HTML embedded data exact')
same(hashes(data_dir),before,'build preserves every source file')
custom = WORK/'nested'/'另一个 报告.html'
same(report.build_report(data_dir,custom,template_path=stub),custom.resolve(),'custom parent directory/path')
same(hashes(data_dir),before,'custom export preserves source files')
for invalid in ['no marker','__RPS_REPORT_DATA__ __RPS_REPORT_DATA__']:
    invalid_path = WORK/'invalid_template.html'
    invalid_path.write_text(invalid,encoding='utf-8')
    try: report.build_report(data_dir,template_path=invalid_path)
    except ValueError: checks += 1
    else: raise AssertionError('invalid marker count accepted')

# Clear errors for missing/malformed saved data; source fixture stays untouched.
def clone(label):
    dest = WORK/label
    dest.mkdir(parents=True,exist_ok=True)
    for filename in SOURCES: shutil.copyfile(data_dir/filename,dest/filename)
    return dest

for label,alter,error_type in [
    ('missing',lambda d:(d/'matches.csv').unlink(),OSError),
    ('bad_json',lambda d:(d/'summary.json').write_text('{bad',encoding='utf-8'),ValueError),
    ('nan_json',lambda d:(d/'summary.json').write_text('{"config":NaN}',encoding='utf-8'),ValueError),
    ('old_json',lambda d:(d/'summary.json').write_text('{}',encoding='utf-8'),ValueError),
    ('empty_csv',lambda d:(d/'matches.csv').write_text('stage,round\n',encoding='utf-8'),ValueError),
    ('wrong_header',lambda d:(d/'rankings.csv').write_text('who,value\nA,1\n',encoding='utf-8'),ValueError),
    ('extra_cell',lambda d:(d/'matches.csv').write_text((d/'matches.csv').read_text(encoding='utf-8-sig')+'a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z,extra\n',encoding='utf-8'),ValueError),
]:
    dest = clone(label); alter(dest)
    try: report.load_report_data(dest)
    except error_type: checks += 1
    else: raise AssertionError('bad saved data accepted: '+label)

config_path = WORK/'config.json'
config_path.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
def invoke(args,expected=0):
    output,error = io.StringIO(),io.StringIO()
    with patch.object(sys,'argv',['rps_simulator.py',*map(str,args)]),contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
        try: sim.main()
        except SystemExit as exc: code = exc.code
        else: code = 0
    same(code,expected,'CLI status '+repr(args))
    if expected: check('Traceback' not in error.getvalue(),'CLI clean error')
    return output.getvalue(),error.getvalue()

# Main integration with a temporary template; no user browser is opened.
with patch.object(report,'TEMPLATE_PATH',stub):
    no_report_dir,default_dir = WORK/'CLI no report',WORK/'CLI default report'
    invoke(['--config',config_path,'--no-report','--out-dir',no_report_dir])
    check(not (no_report_dir/'report.html').exists(),'--no-report omits HTML')
    invoke(['--config',config_path,'--out-dir',default_dir])
    check((default_dir/'report.html').exists(),'default creates HTML')
    same(hashes(no_report_dir),hashes(default_dir),'report mode leaves simulation results byte-identical')
    saved_hashes = hashes(default_dir)
    with patch.object(sim,'load_config',side_effect=AssertionError('report-only loaded config')),patch.object(sim,'simulate',side_effect=AssertionError('report-only simulated')):
        invoke(['--report-only',default_dir])
    same(hashes(default_dir),saved_hashes,'report-only preserves source files')
    def assert_open(uri):
        same(uri,(default_dir/'report.html').resolve().as_uri(),'browser receives encoded file URI')
        check((default_dir/'report.html').exists(),'browser invoked after HTML write')
        return True
    with patch('webbrowser.open',side_effect=assert_open) as opened:
        invoke(['--report-only',default_dir,'--open-report'])
        opened.assert_called_once(); checks += 1
    with patch('webbrowser.open') as opened:
        invoke(['--config',config_path,'--out-dir',default_dir,'--open-report'])
        same(opened.call_count,1,'simulation open once')
        same(opened.call_args.args[0],(default_dir/'report.html').resolve().as_uri(),'simulation file URI')
    validate_dir = WORK/'validate must not write'
    invoke(['--config',config_path,'--validate-only','--out-dir',validate_dir])
    check(not validate_dir.exists(),'validate-only writes nothing')
    for args in [
        ['--no-report','--open-report'],['--validate-only','--open-report'],
        ['--report-only',default_dir,'--no-report'],['--report-only',default_dir,'--config',config_path],
        ['--report-only',default_dir,'--runs','2'],['--report-only',default_dir,'--seed','42'],
        ['--report-only',default_dir,'--out-dir',WORK/'invalid'],['--report-only',default_dir,'--validate-only'],
        ['--report-only',default_dir,'--show-rounds'],['--report-only',WORK/'missing'],
    ]: invoke(args,expected=2)

# Optional final-template and external-process integration, after the UI file lands.
if '--integration' in sys.argv:
    subprocess_python = [sys.executable,'-B']+(['-X','utf8'] if '--utf8-subprocess' in sys.argv else [])
    check(report.TEMPLATE_PATH.exists(),'final UI template exists')
    final = report.build_report(data_dir,WORK/'final_report.html')
    final_html = final.read_text(encoding='utf-8')
    check(report.DATA_MARKER not in final_html,'final marker substituted')
    check('<script>globalThis.__rpsInjected' not in final_html,'final payload cannot inject scripts')
    same(hashes(data_dir),before,'final template preserves source data')
    external = WORK/'external CLI'
    result = subprocess.run([*subprocess_python,str(BASE/'outputs'/'rps_simulator.py'),'--config',str(config_path),
                             '--out-dir',str(external)],capture_output=True)
    same(result.returncode,0,'external CLI default '+repr(result.stderr))
    check((external/'report.html').exists(),'external default report created')
    same(hashes(external),before,'external CLI matches original export bytes')
    result = subprocess.run([*subprocess_python,str(BASE/'outputs'/'rps_simulator.py'),'--report-only',str(external)],capture_output=True)
    same(result.returncode,0,'external report-only')
    result = subprocess.run([*subprocess_python,str(BASE/'outputs'/'rps_report.py'),str(external),
                             '--output',str(WORK/'standalone 报告.html')],capture_output=True)
    same(result.returncode,0,'standalone report CLI')
    check((WORK/'standalone 报告.html').exists(),'standalone output exists')

print(f'PASS: {checks} report checks; lossless/safe embedding, data scopes, source integrity, errors, CLI/report-only/open and '+('final template integration.' if '--integration' in sys.argv else 'stub template integration.'))
