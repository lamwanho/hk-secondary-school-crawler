#!/usr/bin/env python3
"""Offline, attributed academic-reference import. Secondary claims stay unverified."""
import argparse
from collections import defaultdict, Counter
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
STATUS='secondary_compilation_unverified'
BANDS=['1A','1B','1C','2A','2B','2C','3A','3B','3C','1','2','3']

def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKC',value or '').casefold() if c.isalnum())

def number_year(value):
    value=str(value or '').strip()
    if not value:return None
    if not re.fullmatch(r'20\d{2}',value):raise ValueError('Invalid cohort year: '+value)
    return int(value)

def percentage(value):
    value=(value or '').strip()
    if not value:return None
    match=re.fullmatch(r'(大約|接近|超過|少於|至少|不低於|約|[<>≥≤])?\s*(\d+(?:\.\d+)?)\s*%',value)
    if not match or not 0<=float(match[2])<=100:raise ValueError('Invalid percentage: '+value)
    return {'reported_value':value,'rate_percent':float(match[2]),'qualifier':match[1] or 'exact_as_supplied'}

def urls(value):
    return list(dict.fromkeys(re.findall(r'https?://[^\s）)；;]+',value or '')))

def markdown_table(path,first):
    fields=None;rows=[]
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.startswith('|'):continue
        cells=[c.strip() for c in line.strip().strip('|').split('|')]
        if fields is None:
            if cells[0]==first:fields=cells
            continue
        if all(re.fullmatch(r':?-+:?',c) for c in cells):continue
        if len(cells)!=len(fields):raise ValueError('Invalid Markdown table width: '+path.name)
        rows.append(dict(zip(fields,cells)))
    if fields is None:raise ValueError('Missing Markdown data table: '+path.name)
    return rows

def compile_seed(rows,details,schools,provenance):
    index={k:defaultdict(list) for k in ('name_zh','name_en')}
    for s in schools:
        for k in index:index[k][normalized(s.get(k))].append(s)
    detail_index={}
    for detail in details:
        name=normalized(detail['學校名稱'])
        if name in detail_index:raise ValueError('Duplicate detail school')
        detail_index[name]=detail
    records=[];seen=set();matched_details=set()
    for row in rows:
        candidates={s['id']:s for s in index['name_zh'].get(normalized(row['學校名稱']),[])+index['name_en'].get(normalized(row['English Name']),[])}
        if len(candidates)!=1:raise ValueError(('unmatched' if not candidates else 'ambiguous')+' school: '+row['學校名稱'])
        school=next(iter(candidates.values()))
        if school['id'] in seen:raise ValueError('Duplicate match: multiple import rows for '+school['id'])
        seen.add(school['id'])
        source=row['資料頁'];year=number_year(row['升學數據年份'])
        def metric(label,value,kind):
            rate=percentage(value)
            return {**rate,'metric':label,'kind':kind,'stream':'DSE','cohort_year':year,'source_url':source,'verification_status':STATUS} if rate else None
        band=row['Banding'] or None;original=row['Banding 原始估算'] or None;method=row['Banding 推導方式']
        if band and band not in BANDS:raise ValueError('Invalid reference band: '+band)
        # The CSV retains Big Exam's old range even when SchoolHub is the chosen source.
        fallback=bool(re.search(r'(?:以|改用)\s*SchoolHub',method))
        reported=band if fallback else original
        choices=re.findall(r'[123][ABC]?',reported or '')
        if band and choices and band!=min(choices):raise ValueError('Band must use the highest reported range: '+school['id'])
        band_urls=urls(row['Banding 來源（含 URL）'])
        chosen=next((u for u in band_urls if ('schoolhub.hk' in u if fallback else 'schooland.hk' in u if '採用升學天地' in method else 'bigexam.hk' in u)),None)
        b={'display':band,'reported':reported,'source_original_estimate':original,'year':number_year(row['Banding 更新年份（DSE 年度）']),
           'source_url':chosen,'source_urls':band_urls,'source_accuracy_label':row['Banding 準確度'],
           'method_as_supplied':method,'verification_status':STATUS,'status':'unofficial imported estimate; not an EDB classification',
           'notes':'Highest band within the selected source range. Source year and source-reported accuracy are retained; neither establishes official school banding.'}
        label=row['入學要求指標'];headline=metric(label,row['大學最低入學要求達標率'],'entry_requirement' if label in ('332A+2','3322+2') else 'unclassified_degree_subdegree_measure')
        progression=[]
        for part in filter(None,row['其他升學指標（學校公布）'].split('；')):
            match=re.fullmatch(r'(.+?)\s+((?:大約|接近|超過|少於|至少|不低於|約|[<>≥≤])?\s*\d+(?:\.\d+)?\s*%)',part.strip())
            if not match:raise ValueError('Unparsed progression metric: '+part)
            progression.append(metric(match[1],match[2],'progression'))
        reference={'import_id':'academic-reference-2026','imported_date':provenance.get('imported_date'),
                   'verification_status':STATUS,'source_url':source,'source_claim_as_supplied':row['升學數據性質'],
                   'band':b,'entry_requirements':headline if label in ('332A+2','3322+2') else None,
                   'unclassified_measure':headline if label not in ('332A+2','3322+2') else None,'progression':progression}
        detail=detail_index.get(normalized(row['學校名稱']))
        if detail:
            matched_details.add(normalized(row['學校名稱']))
            result={'cohort_year':number_year(detail['DSE 年份']),'source_url':detail['資料頁'],'verification_status':STATUS,'school_metrics':[],'hk_day_school_benchmarks':[]}
            for key,value in detail.items():
                if key in ('學校名稱','Banding','DSE 年份','資料頁') or not value:continue
                rate=percentage(value)
                result['hk_day_school_benchmarks' if key.startswith('全港 ') else 'school_metrics'].append({'metric':key,**rate})
            reference['subject_results']=result
        records.append({'id':school['id'],'name_zh':school['name_zh'],'name_en':school['name_en'],'input_row':row['#'],'academic_reference':reference})
    if set(detail_index)-matched_details:raise ValueError('Unmatched detail schools')
    return {'schema_version':'1.0','provenance':provenance,'records':records}

def apply_enrichment(schools,seed,verifications=None):
    result=copy.deepcopy(schools);byid={s['id']:s for s in result};seen=set()
    for record in seed.get('records',[]):
        sid=record['id']
        if sid not in byid or sid in seen:raise ValueError('Unknown or duplicate enrichment identity: '+sid)
        seen.add(sid);school=byid[sid]
        if normalized(school['name_zh'])!=normalized(record['name_zh']):raise ValueError('Enrichment school name changed: '+sid)
        reference=copy.deepcopy(record['academic_reference']);b=reference['band'];current=school.get('reference_band',{})
        previous=current.get('previous_reference') if current.get('import_id')=='academic-reference-2026' else current
        previous=previous or {}
        reference['band_conflict']=bool(previous.get('display') and b.get('display') and previous['display']!=b['display'])
        if b.get('display') and (b.get('year') or 0)>=2024 and current.get('source_type')!='user_correction' and (b['year']>=(current.get('year') or 0)):
            school['reference_band']={**copy.deepcopy(b),'import_id':'academic-reference-2026','previous_reference':copy.deepcopy(previous)}
        school['academic_reference']=reference
    for proof in (verifications or {}).get('schools',[]):
        school=byid.get(proof['id'])
        if not school or normalized(school['name_zh'])!=normalized(proof['name_zh']):raise ValueError('Unknown verified academic identity')
        host=lambda u:(urlsplit(u or '').hostname or '').lower().removeprefix('www.')
        if not host(school.get('website')) or host(school.get('website'))!=host(proof.get('source_url')) or proof.get('verification_status')!='school_page_verified' or not proof.get('checked_date'):
            raise ValueError('Verified academic record requires official school-page evidence')
        entries=[]
        for entry in proof['entry_requirements']:
            entries.append({**percentage(entry['reported_value']),'metric':entry['metric'],'cohort_year':number_year(entry['cohort_year']),
                            'kind':'entry_requirement','stream':'DSE','verification_status':'school_page_verified',
                            'source_url':proof['source_url'],'checked_date':proof['checked_date']})
        school['exam_entry_requirements']=entries
    return result

def summarize(schools):
    refs=[s['academic_reference'] for s in schools if s.get('academic_reference')]
    return {'matched_schools':len(refs),'current_reference_bands':sum(bool(s.get('reference_band',{}).get('display')) for s in schools),
            'imported_entry_requirement_claims':sum(bool(r.get('entry_requirements')) for r in refs),
            'unclassified_degree_subdegree_claims':sum(bool(r.get('unclassified_measure')) for r in refs),
            'schools_with_imported_progression_claims':sum(bool(r['progression']) for r in refs),
            'schools_with_imported_subject_statistics':sum(bool(r.get('subject_results',{}).get('school_metrics')) for r in refs),
            'conflicting_band_claims':sum(r['band_conflict'] for r in refs)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv',type=Path,required=True)
    parser.add_argument('--banding-notes',type=Path,required=True)
    parser.add_argument('--detail',type=Path,required=True)
    parser.add_argument('--roster',type=Path,default=ROOT/'docs/data/pilot.json')
    parser.add_argument('--output',type=Path,default=ROOT/'seed/academic-reference-2026.json')
    args=parser.parse_args()
    rows=list(csv.DictReader(args.csv.open(encoding='utf-8-sig',newline='')))
    notes=markdown_table(args.banding_notes,'#')
    if len(rows)!=len(notes):raise ValueError('CSV and banding Markdown counts disagree')
    for a,b in zip(rows,notes):
        for key in ('#','學校名稱','Banding','大學最低入學要求達標率'):
            if a[key]!=b[key]:raise ValueError('CSV and banding Markdown disagree: '+a['#'])
    provenance={'imported_date':'2026-10-26','origin':'Owner-supplied AI-assisted secondary compilation; source claims are not independently school-verified.',
                'files':[{'filename':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (args.csv,args.banding_notes,args.detail)],
                'policies':['Owner corrections take precedence. Only estimates dated 2024 onwards enter current band filters.',
                            'Preserve exact qualifiers and cohort years. Entry thresholds are not university admissions.',
                            'Mixed degree/subdegree headline measures are quarantined for definition review.',
                            'School subject statistics and Hong Kong day-school benchmarks are separate.',
                            'Missing values stay unknown. This enrichment does not verify events or booking dates.']}
    seed=compile_seed(rows,markdown_table(args.detail,'學校名稱'),json.loads(args.roster.read_text(encoding='utf-8'))['schools'],provenance)
    args.output.write_text(json.dumps(seed,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'records':len(seed['records']),'input_files':[p['filename'] for p in provenance['files']]},ensure_ascii=False))

if __name__=='__main__':main()
