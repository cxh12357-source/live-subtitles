"""Summarize timestamp measurements; never infer accuracy from GUI test strings."""
import argparse
import json
from pathlib import Path
import re
import numpy as np
from scripts.compare_recognition import character_error, REFERENCES


def stats(values):
    values=[v for v in values if v is not None and np.isfinite(v)]
    if not values:return {'n':0,'median':None,'p95':None}
    return dict(n=len(values),median=round(float(np.median(values)),3),
                p95=round(float(np.percentile(values,95)),3))


def summarize(report):
    es=report['events'];schedule=report['schedule']
    # Correlation calibrates actual loopback waveform origin, not wall-clock playback intent.
    calibration=report.get('calibration') or {}
    offset=calibration.get('engine_offset_seconds')
    if offset is None and calibration.get('correlation',0)>.65:
        first=next(e for e in es if e['stage']=='capture')
        offset=calibration['captured_offset_seconds']+first['audio_end']-first['block_ms']/1000
    if offset is not None and schedule:
        correction=offset-(schedule[0]['start']-1)
        schedule=[{k:(v+correction if k in ('start','end','speech_start','speech_end') else v)
                   for k,v in s.items()} for s in schedule]
    rows=[]
    for s in schedule:
        def belongs(e):return s['start']<=e.get('audio_end',-1)<s['end']+2.8
        displays=[e for e in es if e['stage']=='display' and belongs(e) and not e['translated'] and e['text']]
        readable=[e for e in displays if len(re.findall(r'[\u3400-\u9fff]',e['text']))>=2 or re.search(r'[A-Za-z]{3}',e['text'])]
        finals=[e for e in es if e['stage']=='asr' and e['final'] and belongs(e)]
        confirmations=[e for e in displays if e['final'] and e['audio_end']>=s['speech_end']]
        translated=[e for e in es if e['stage']=='display' and e['translated'] and belongs(e)
                    and re.search(r'[\u3400-\u9fff]',e['text'])]
        raw=''.join(e['text'] for e in finals)
        rows.append(dict(fixture=s['fixture'],language=s['language'],start=s['speech_start'],
                         first_ms=(displays[0]['t']-s['speech_start'])*1000 if displays else None,
                         readable_ms=(readable[0]['t']-s['speech_start'])*1000 if readable else None,
                         final_after_speech_ms=(confirmations[-1]['t']-s['speech_end'])*1000 if confirmations else None,
                         translation_first_ms=(translated[0]['t']-s['speech_start'])*1000 if translated else None,
                         cer=character_error(REFERENCES[s['fixture']],raw),raw=raw))
    stages={}
    for name,stage,key in [('capture_block_ms','capture','block_ms'),('portaudio_age_ms','capture','portaudio_age_ms'),
                            ('preprocess_queue_ms','audio','queue_ms'),('preprocess_ms','audio','preprocess_ms'),
                            ('resampler_delay_ms','audio','resampler_delay_ms'),('asr_queue_ms','asr','queue_ms'),
                            ('asr_inference_ms','asr','inference_ms'),('mt_queue_ms','translation','queue_ms'),
                            ('mt_inference_ms','translation','inference_ms')]:
        stages[name]=stats(e.get(key) for e in es if e['stage']==stage)
    stages['asr_result_to_ui_ms']=stats(e.get('ui_ms') for e in es if e['stage']=='display' and not e['translated'])
    stages['mt_result_to_ui_ms']=stats(e.get('ui_ms') for e in es if e['stage']=='display' and e['translated']) if report['variant']=='stream' else {'n':0,'median':None,'p95':None}
    stages['endpoint_wait_ms']=stats(e.get('endpoint_wait_ms') for e in es if e['stage']=='asr' and e.get('final'))
    intervals=[];visible_intervals=[]
    last={};last_visible={}
    for e in es:
        if e['stage']=='display' and not e['translated'] and not e['final'] and e['text']:
            key=(e.get('epoch'),e['id'])
            if key in last:intervals.append((e['t']-last[key])*1000)
            last[key]=e['t']
            prior=last_visible.get(key)
            if prior is None or e['text']!=prior['text']:
                if prior is not None:visible_intervals.append((e['t']-prior['t'])*1000)
                last_visible[key]=e
    stages['nonempty_partial_update_interval_ms']=stats(intervals)
    # A new ASR suffix may be on a later page. Count actual QLabel changes too.
    stages['visible_partial_change_interval_ms']=stats(visible_intervals)
    summary=dict(variant=report['variant'],transport=report['transport'],model=report['model'],
                 requested_seconds=report['requested_seconds'],device=report.get('device'),
                 calibration=calibration,released=report['released'],audio_drops=report['dropped'],stages=stages,
                 errors=[e for e in es if e['stage'] in ('error','playback_error','validation_error')],clips=rows)
    summary['languages']={lang:{field:stats(row[field] for row in rows if row['language']==lang)
                               for field in ('first_ms','readable_ms','final_after_speech_ms','translation_first_ms','cer')}
                          for lang in ('zh','en')}
    # Compare first/last thirds of the run; excludes long inter-sentence silences.
    thirds=[]
    for a,b in [(0,report['requested_seconds']/3),(report['requested_seconds']*2/3,report['requested_seconds']+4)]:
        thirds.append(dict(start=a,end=b,readable_ms=stats(r['readable_ms'] for r in rows if a<=r['start']<b),
                           languages={lang:stats(r['readable_ms'] for r in rows if a<=r['start']<b and r['language']==lang)
                                      for lang in ('zh','en')},
                           asr_queue_ms=stats(e.get('queue_ms') for e in es if e['stage']=='asr' and a<=e['t']<b)))
    summary['drift']=thirds
    memory=report['memory']
    summary['memory_mib']={'peak':max(m['rss'] for m in memory)/1048576,
                           'after60':next((m['rss']/1048576 for m in memory if m['t']>=60),None),
                           'last':memory[-1]['rss']/1048576,
                           'max_raw_queue':max(m['raw'] for m in memory),'max_asr_queue':max(m['jobs'] for m in memory)}
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('reports',nargs='+',type=Path);args=p.parse_args()
    for path in args.reports:
        result=summarize(json.loads(path.read_text(encoding='utf-8')))
        out=path.with_name(path.stem+'-summary.json');out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(str(out));print(json.dumps({k:result[k] for k in ('languages','stages','drift','memory_mib','audio_drops','errors')},ensure_ascii=False,indent=2))
