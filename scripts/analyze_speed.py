"""Separate unreviewed acoustic text, interim displayed text and final review."""
import argparse,json,re
from pathlib import Path
import numpy as np
from scripts.speed_probe import edits
from scripts.analyze_latency import stats
from captioner.presentation import display_text

def excess_repeats(reference,hypothesis,language):
    def runs(text):
        text=display_text(text).lower()
        tokens=re.sub(r'[^\w\s]',' ',text).split() if language=='en' else list(re.sub(r'[^\w]','',text))
        return sum(tokens[i:i+n]==tokens[i+n:i+2*n] for n in range(1,4) for i in range(len(tokens)-2*n+1))
    return max(0,runs(hypothesis)-runs(reference))

def analyze(d):
    es=d['events'];schedule=d['schedule'];cal=d.get('calibration') or {}
    correction=cal.get('engine_offset_seconds',schedule[0]['start']-1)-(schedule[0]['start']-1)
    rows=[]
    for s in schedule:
        start=s['start']+correction;end=s['end']+correction
        speech_start=s['speech_start']+correction;speech_end=s['speech_end']+correction
        owns=lambda e:start<=e.get('audio_end',-10)<end+1.8
        raw=[e for e in es if e['stage']=='asr' and e.get('final') and owns(e)]
        final_stage='resolved' if d['variant']=='reviewed' else 'asr'
        finals={e['id']:e for e in es if e['stage']==final_stage and e.get('final') and owns(e)}
        displays=[e for e in es if e['stage']=='display' and owns(e) and e['text'] and not e['translated']]
        readable=[e for e in displays if (len(re.findall(r'[\u3400-\u9fff]',e['text']))>=2 if s['language']=='zh' else re.search(r'[A-Za-z]{3}',e['text']))]
        confirmed=[e for e in displays if e['final'] and e['audio_end']>=speech_end]
        visible_finals={e['id']:e for e in displays if e['final']}
        last_shown={e['id']:e for e in displays}
        # Last genuinely published provisional full text per utterance, not pages concatenated.
        provisional={e['id']:e for e in displays if not e['final']}
        combine=lambda values,key:' '.join(e[key] for e in sorted(values,key=lambda e:(e['audio_end'],e['id'])))
        raw_text=combine(raw,'text');generated_text=combine(finals.values(),'text')
        final_text=combine(visible_finals.values(),'full_text');temp_text=combine(provisional.values(),'full_text')
        row=dict(fixture=s['fixture'],speed=s['speed'],language=s['language'],start=speech_start,
                 source=s.get('source'),reference=s['reference'],raw=raw_text,final=final_text,last_provisional=temp_text,
                 generated_final=generated_text,generated_final_error=edits(s['reference'],generated_text,s['language']),
                 last_shown=combine(last_shown.values(),'full_text'),
                 last_shown_error=edits(s['reference'],combine(last_shown.values(),'full_text'),s['language']),
                 unconfirmed_blocks=len(set(last_shown)-set(visible_finals)),
                 raw_error=edits(s['reference'],raw_text,s['language']),final_error=edits(s['reference'],final_text,s['language']),
                 last_provisional_error=edits(s['reference'],temp_text,s['language']),
                 excess_adjacent_repeats=dict(raw=excess_repeats(s['reference'],raw_text,s['language']),
                                              final=excess_repeats(s['reference'],final_text,s['language'])),
                 first_readable_ms=(readable[0]['t']-speech_start)*1000 if readable else None,
                 final_ms=(confirmed[-1]['t']-speech_end)*1000 if confirmed else None)
        terms=('平壁','导热','边界条件','热阻') if s['language']=='zh' else ()
        row['terms']={t:dict(reference=s['reference'].count(t),raw=display_text(raw_text).count(t),final=display_text(final_text).count(t)) for t in terms}
        rows.append(row)
    groups={}
    for row in rows:
        key=row['fixture']+'@'+str(row['speed']);groups.setdefault(key,[]).append(row)
    summary={key:dict(n=len(rs),raw_error=stats(r['raw_error']['rate'] for r in rs),
                      final_error=stats(r['final_error']['rate'] for r in rs),
                      last_shown_error=stats(r['last_shown_error']['rate'] for r in rs),
                      last_provisional_error=stats(r['last_provisional_error']['rate'] for r in rs),
                      first_readable_ms=stats(r['first_readable_ms'] for r in rs),
                      final_ms=stats(r['final_ms'] for r in rs)) for key,rs in groups.items()}
    memory=d['memory'];reviews=[e for e in es if e['stage']=='review']
    return dict(variant=d['variant'],seconds=d['requested_seconds'],groups=summary,clips=rows,
                missing_displays=dict(first=sum(r['first_readable_ms'] is None for r in rows),final=sum(r['final_ms'] is None for r in rows),unconfirmed_blocks=sum(r['unconfirmed_blocks'] for r in rows)),
                reviews=dict(count=len(reviews),accepted=sum(e['accepted'] for e in reviews),
                             guarded=any('agreement' in e for e in reviews),
                             bounded_prefix=any(e.get('prefix_policy')=='equal_units_or_endpoint' for e in reviews),
                             disagreement_rejected=sum(not e.get('agreement',True) for e in reviews),
                             inference_ms=stats(e['inference_ms'] for e in reviews),queue_ms=stats(e['queue_ms'] for e in reviews)),
                dropped=d['dropped'],released=d['released'],calibration=cal,
                errors=[e for e in es if e['stage'] in ('error','playback_error','validation_error')],
                memory=dict(peak_mib=max(e['rss'] for e in memory)/1048576,last_mib=memory[-1]['rss']/1048576,
                            max_raw=max(e['raw'] for e in memory),max_asr=max(e['jobs'] for e in memory)),
                asr_queue_first=stats(e['queue_ms'] for e in es if e['stage']=='asr' and e['t']<d['requested_seconds']/3),
                asr_queue_last=stats(e['queue_ms'] for e in es if e['stage']=='asr' and e['t']>d['requested_seconds']*2/3))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('paths',nargs='+',type=Path);args=p.parse_args()
    for path in args.paths:
        report=analyze(json.loads(path.read_text(encoding='utf-8')))
        path.with_name(path.stem+'-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='clips'},ensure_ascii=False,indent=2))
