#!/usr/bin/env python3
import json, statistics
from collections import defaultdict

results_path = '/tmp/stt-eval/results/results.json'
output_path = '/tmp/stt-eval/results'
with open(results_path) as f:
    results = json.load(f)

total = len(results)
correct = sum(1 for r in results if r['correct'])
wer_values = [r['wer'] for r in results]
cer_values = [r['cer'] for r in results]
avg_wer = statistics.mean(wer_values)
avg_cer = statistics.mean(cer_values)
median_wer = statistics.median(wer_values)

by_domain = defaultdict(list)
for r in results:
    by_domain[r['domain']].append(r)

by_noise = defaultdict(list)
for r in results:
    by_noise[r.get('noise_level', 'clean')].append(r)

error_types = defaultdict(int)
for r in results:
    error_types[r['error_type']] += 1

bad_samples = sorted([r for r in results if r['wer'] > 0.3], key=lambda x: x['wer'], reverse=True)

proc_times = [r['processing_seconds'] for r in results if r['processing_seconds'] > 0]
corr_times = [r['correction_seconds'] for r in results if r['correction_seconds'] > 0]

report = []
report.append('='*70)
report.append('STT 准确率评测报告 -- Round 1 (Baseline)')
report.append('='*70)
report.append('')
report.append('## 总体指标')
report.append('  样本总数: %d' % total)
report.append('  完全正确: %d (%.1f%%)' % (correct, correct/total*100))
report.append('  平均 WER: %.4f (%.2f%%)' % (avg_wer, avg_wer*100))
report.append('  平均 CER: %.4f (%.2f%%)' % (avg_cer, avg_cer*100))
report.append('  中位 WER: %.4f' % median_wer)
if len(wer_values) > 1:
    report.append('  WER 标准差: %.4f' % statistics.stdev(wer_values))
report.append('  平均处理时长: %.2fs' % statistics.mean(proc_times) if proc_times else '')
report.append('  平均纠错时长: %.2fs' % statistics.mean(corr_times) if corr_times else '')
report.append('')
report.append('## WER 分布')
for r in results:
    wer = r['wer']
    if wer == 0: bucket = 'WER = 0'
    elif wer <= 0.05: bucket = 'WER <= 0.05'
    elif wer <= 0.10: bucket = 'WER <= 0.10'
    elif wer <= 0.20: bucket = 'WER <= 0.20'
    elif wer <= 0.50: bucket = 'WER <= 0.50'
    else: bucket = 'WER > 0.50'
    error_types[bucket + '_wer'] = error_types.get(bucket + '_wer', 0) + 1

buckets_ordered = ['WER = 0', 'WER <= 0.05', 'WER <= 0.10', 'WER <= 0.20', 'WER <= 0.50', 'WER > 0.50']
for b in buckets_ordered:
    count = error_types.get(b, 0)
    report.append('  %s: %3d (%.1f%%)' % (b, count, count/total*100))

report.append('')
report.append('## 按噪音级别')
for nl in ['clean', 'soft', 'medium', 'loud']:
    g = by_noise.get(nl, [])
    if not g: continue
    w = statistics.mean(r['wer'] for r in g)
    acc = sum(1 for r in g if r['correct']) / len(g) * 100
    report.append('  %-10s: n=%3d  WER=%.4f  Acc=%.1f%%' % (nl, len(g), w, acc))

report.append('')
report.append('## 按领域')
for d in sorted(by_domain.keys()):
    g = by_domain[d]
    w = statistics.mean(r['wer'] for r in g)
    acc = sum(1 for r in g if r['correct']) / len(g) * 100
    report.append('  %-10s: n=%3d  WER=%.4f  Acc=%.1f%%' % (d, len(g), w, acc))

report.append('')
report.append('## 错误类型分布')
for et, count in sorted(error_types.items(), key=lambda x: -x[1]):
    if et.startswith('WER'): continue
    report.append('  %-25s: %3d (%.1f%%)' % (et, count, count/total*100))

report.append('')
report.append('## WER > 0.3 错误样本 (Top 15)')
for r in bad_samples[:15]:
    domain = r['domain']
    wer = r['wer']
    et = r['error_type']
    gt = r['ground_truth']
    raw = r['raw_text']
    out = r['corrected_text']
    report.append('  [%s] WER=%.3f (%s)' % (domain, wer, et))
    report.append('    GT:  ' + gt)
    report.append('    RAW: ' + raw)
    report.append('    OUT: ' + out)
    report.append('')

report_text = '\n'.join(report)
print(report_text)

with open(output_path + '/report.md', 'w') as f:
    f.write(report_text)

with open(output_path + '/summary.csv', 'w') as f:
    f.write('sample_id,domain,noise_level,wer,cer,correct,error_type,ground_truth,corrected_text,raw_text\n')
    for r in sorted(results, key=lambda x: x['sample_id']):
        def esc(s):
            return s.replace('"', '""')
        f.write('%d,%s,%s,%.4f,%.4f,%s,%s,"%s","%s","%s"\n' % (
            r['sample_id'], r['domain'], r['noise_level'],
            r['wer'], r['cer'], r['correct'], r['error_type'],
            esc(r['ground_truth']), esc(r['corrected_text']), esc(r['raw_text'])
        ))

print('\n报告: %s/report.md' % output_path)
print('CSV:  %s/summary.csv' % output_path)
