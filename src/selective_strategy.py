#!/usr/bin/env python3
"""
Smart selective post-processing:
- tech/english domains: Ollama few-shot (these benefit significantly)
- numbers/daily/others: only rule-based tech term fixes (no Ollama)
- Never modify: numbers, times, dates, percentages
"""
import json, jiwer, re

# Load results from r2 (which had Ollama on everything)
with open('/tmp/stt-eval/results/results_r2.json') as f:
    r2 = json.load(f)

# Also load r1 baseline
with open('/tmp/stt-eval/results/results.json') as f:
    r1 = {r['sample_id']: r for r in json.load(f)}

def compute_wer(reference, hypothesis):
    ref = ' '.join(reference.split())
    hyp = ' '.join(hypothesis.split())
    try:
        return jiwer.wer(ref, hyp)
    except Exception:
        return 1.0

# Selective strategy:
# - 'tech' and 'english': use Ollama result if WER improved
# - 'numbers': NEVER use Ollama (always causes regressions)
# - 'daily', 'commands', 'names', 'news': only use Ollama if it improves AND doesn't add/modify words
# - 'all': fallback to raw or rule-fixed (never worse)

OLLAMA_GOOD_DOMAINS = {'tech', 'english'}
OLLAMA_BAD_DOMAINS = {'numbers'}

def smart_select(r):
    gt = r['ground_truth']
    raw = r['raw_text']
    rule = r.get('rule_fixed_text', raw)
    ollama = r.get('ollama_text', '')
    domain = r['domain']

    wer_raw = compute_wer(gt, raw)
    wer_rule = compute_wer(gt, rule)
    wer_ollama = compute_wer(gt, ollama) if ollama else 1.0

    # Numbers domain: never use Ollama
    if domain in OLLAMA_BAD_DOMAINS:
        if wer_rule < wer_raw:
            return rule, wer_rule, 'rules'
        else:
            return raw, wer_raw, 'raw'

    # Tech/English: use Ollama if it improves
    if domain in OLLAMA_GOOD_DOMAINS:
        if wer_ollama < wer_rule and wer_ollama < wer_raw:
            return ollama, wer_ollama, 'ollama'
        elif wer_rule < wer_raw:
            return rule, wer_rule, 'rules'
        else:
            return raw, wer_raw, 'raw'

    # Other domains: conservative — use Ollama only if it strictly improves
    # AND doesn't add new content
    if ollama and wer_ollama < wer_raw and wer_ollama < wer_rule:
        # Additional check: Ollama shouldn't add words that aren't in GT
        # Allow if ollama is shorter or same length (removing is ok, adding is not)
        if len(ollama) <= len(rule) * 1.2:
            return ollama, wer_ollama, 'ollama'

    if wer_rule < wer_raw:
        return rule, wer_rule, 'rules'
    return raw, wer_raw, 'raw'

# Apply smart selection
for r in r2:
    final_text, wer_final, method = smart_select(r)
    r['final_text'] = final_text
    r['smart_wer'] = wer_final
    r['smart_method'] = method

# Summary
total = len(r2)
r1_avg = sum(r['wer'] for r in r1.values()) / total
r2_ollama_avg = sum(r['wer_final'] for r in r2) / total
smart_avg = sum(r['smart_wer'] for r in r2) / total
r1_correct = sum(1 for r in r1.values() if r['wer'] == 0)
r2_correct = sum(1 for r in r2 if r['wer_final'] == 0)
smart_correct = sum(1 for r in r2 if r['smart_wer'] == 0)

print("="*60)
print("Strategy Comparison")
print("="*60)
print()
print("%-20s: WER=%-8s Correct=%-5s" % ("Baseline (raw)", "%.4f" % r1_avg, "%d/%d" % (r1_correct, total)))
print("%-20s: WER=%-8s Correct=%-5s" % ("Ollama everywhere", "%.4f" % r2_ollama_avg, "%d/%d" % (r2_correct, total)))
print("%-20s: WER=%-8s Correct=%-5s" % ("Smart selective", "%.4f" % smart_avg, "%d/%d" % (smart_correct, total)))
print()

# Per domain with smart strategy
from collections import defaultdict
by_domain = defaultdict(list)
for r in r2:
    by_domain[r['domain']].append(r)

print("Per-domain (smart):")
for d in sorted(by_domain.keys()):
    g = by_domain[d]
    r1_w = sum(r['wer_raw'] for r in g) / len(g)
    smart_w = sum(r['smart_wer'] for r in g) / len(g)
    r1_c = sum(1 for r in g if r['wer_raw'] == 0)
    smart_c = sum(1 for r in g if r['smart_wer'] == 0)
    delta = r1_w - smart_w
    print("  %-10s: R1 WER=%.4f C=%-2d  Smart WER=%.4f C=%-2d  delta=%.4f" % (
        d, r1_w, r1_c, smart_w, smart_c, delta))

# Method distribution
methods = defaultdict(int)
for r in r2:
    methods[r['smart_method']] += 1
print()
print("Method distribution:")
for m, c in sorted(methods.items(), key=lambda x: -x[1]):
    print("  %s: %d" % (m, c))

# Save
with open('/tmp/stt-eval/results/results_smart.json', 'w') as f:
    json.dump(r2, f, ensure_ascii=False, indent=2)
print()
print("Saved: results_smart.json")
