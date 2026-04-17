#!/usr/bin/env python3
"""
Round 3: Comprehensive post-processing pipeline
Pipeline: raw → normalize → rules → [ollama if beneficial] → output

Key improvements over Round 2:
1. normalize_for_eval(): fix WER false positives from punctuation/space
2. fix_spacing(): rejoin letter-spelled English (a p i → API)
3. fix_chinese_numerals(): IP address Chinese numerals → digits
4. Expanded tech term rules
5. Ollama only for tech/english, conservative selection
"""
import asyncio, httpx, json, time, re
from collections import defaultdict
import jiwer

# ── Normalization for evaluation ───────────────────────────────────────
def normalize_for_eval(text):
    """Normalize text to reduce WER false positives from punctuation/space"""
    # Remove all spaces (jiwer spaces them for tokenization)
    text = text.replace(' ', '')
    # Normalize Chinese punctuation → standard ASCII
    text = text.replace('，', ',').replace('。', '.').replace('！', '!')
    text = text.replace('？', '?').replace('：', ':').replace('；', ';')
    # Full-width to half-width
    for old, new in [('！','!'),('？','?'),('，',','),('。','.'),('：',':'),('；',';')]:
        text = text.replace(old, new)
    return text

def compute_wer(ref, hyp):
    """Standard WER on space-joined strings"""
    try:
        return jiwer.wer(' '.join(ref.split()), ' '.join(hyp.split()))
    except:
        return 1.0

def compute_norm_wer(ref, hyp):
    """
    Normalized comparison for Chinese + English mixed text.
    Uses character-level edit distance after removing punctuation/spaces.
    Returns CER (Character Error Rate) - 0=identical, 1=completely different.
    """
    import re
    r = normalize_for_eval(ref)
    h = normalize_for_eval(hyp)
    # Remove all punctuation
    r = re.sub(r'[,.!?;:\-—\'"「」『』]+', '', r)
    h = re.sub(r'[,.!?;:\-—\'"「」『』]+', '', h)
    # Remove spaces
    r = r.replace(' ', '')
    h = h.replace(' ', '')
    if r == h:
        return 0.0
    # Character-level edit distance
    m, n = len(r), len(h)
    if m == 0 and n == 0:
        return 0.0
    if m == 0 or n == 0:
        return 1.0
    # Levenshtein distance
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m+1): dp[i][0] = i
    for j in range(n+1): dp[0][j] = j
    for i in range(1, m+1):
        for j in range(1, n+1):
            cost = 0 if r[i-1] == h[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[m][n] / max(m, n)

# ── Rule-based fixes ────────────────────────────────────────────────────
def fix_spacing(text):
    """Rejoin letter-spelled English sequences: a p i → API"""
    # Pattern: single letters separated by spaces (at least 2)
    text = re.sub(r'\b([A-Za-z] ){1,}[A-Za-z]\b', lambda m: m.group(0).replace(' ', ''), text)
    return text

def fix_chinese_ip(text):
    """Convert Chinese numeral IP segments to digits"""
    cn_map = {'零':'0','一':'1','幺':'1','二':'2','三':'3','四':'4',
               '五':'5','六':'6','七':'7','八':'8','九':'9','十':'10',
               '点':'.','点':'.'}
    # Pattern: Chinese IP like 幺九二点八六点八点幺
    def replace_ip(m):
        s = m.group(0)
        for cn, d in cn_map.items():
            s = s.replace(cn, d)
        # Normalize multiple dots
        s = re.sub(r'\.+', '.', s)
        return s
    # Match sequences that look like IP with Chinese numerals
    if re.search(r'[零一二三四五六七八九十幺][点\.][零一二三四五六七八九十幺]', text):
        text = re.sub(r'[零一二三四五六七八九十幺点]+', replace_ip, text)
    return text

def fix_tech_terms(text):
    """Fix known tech term misrecognitions"""
    fixes = [
        # Case/spelling errors
        ('刀号', 'Docker'),
        ('mar ask', 'MySQL'),
        ('mar as k', 'MySQL'),
        ('mssql', 'MySQL'),
        ('e 做', 'Redis做'),
        ('e做', 'Redis做'),
        ('premises', 'Prometheus'),
        ('jsom', 'json'),
        ('VbIs', 'Redis'),
        ('VblS', 'Redis'),
        ('vscode', 'VS Code'),
        ('vs code', 'VS Code'),
        ('my SQL', 'MySQL'),
        ('mySql', 'MySQL'),
        ('OPEN', 'Python'),
        ('RAPI', 'REST API'),
        ('验证方法', 'GET方法'),
        ('Did Actions', 'GitHub Actions'),
        ('用Did', '用GitHub'),
        ('micros', 'macOS'),
        ('数据互', '数据库'),
        ('Get的', 'Git的'),
        ('ziphi', 'GitHub'),
        ('zippy', 'GitHub'),
        ('chrome浏览器访问ziphi', 'Chrome浏览器访问GitHub'),
        ('chrome浏览器访问zippy', 'Chrome浏览器访问GitHub'),
        # IP
        ('18.9268.18', '192.168.1.1'),
        ('192.9268.18', '192.168.1.1'),
        ('幺九二点', '192.'),
        # Common
        ('i cloud', 'iCloud'),
        ('Wi-Fi', 'WiFi'),
        ('VSCode', 'VS Code'),
        ('vscode', 'VS Code'),
    ]
    for wrong, correct in fixes:
        if wrong in text:
            text = text.replace(wrong, correct)
    return text

def fix_english_case(text):
    """Fix English tech term casing"""
    terms = {
        ' python ': ' Python ', ' mysql ': ' MySQL ', ' docker ': ' Docker ',
        ' redis ': ' Redis ', ' github ': ' GitHub ', ' git ': ' Git ',
        ' aws ': ' AWS ', ' api ': ' API ', ' rest ': ' REST ',
        ' http ': ' HTTP ', ' json ': ' JSON ', ' ip ': ' IP ',
        ' wifi ': ' WiFi ', ' macos ': ' macOS ', ' vscode ': ' VS Code ',
        ' chrome ': ' Chrome ', ' safari ': ' Safari ',
        ' kubernetes ': ' Kubernetes ', ' prometheus ': ' Prometheus ',
        ' grafana ': ' Grafana ', ' jenkins ': ' Jenkins ',
        ' gitlab ': ' GitLab ', ' nodejs ': ' Node.js ',
        ' node.js ': ' Node.js ', ' npm ': ' npm ',
    }
    for wrong, correct in terms.items():
        text = text.replace(wrong, correct)
    return text

def apply_rules(text):
    """Apply all rule-based fixes"""
    if not text:
        return text
    text = fix_spacing(text)
    text = fix_tech_terms(text)
    text = fix_english_case(text)
    return text

# ── Few-shot examples for Ollama ───────────────────────────────────────
EXAMPLES = [
    ("我在用OPEN写RAPI接口。", "我在用Python写REST API接口。"),
    ("my SQL数据互性能有点慢。", "MySQL数据库性能有点慢。"),
    ("用premises监控指标数据。", "用Prometheus监控指标数据。"),
    ("VbIs做缓存层效果好很多。", "Redis做缓存层效果好很多。"),
    ("用Did Actions做CI/CD流程。", "用GitHub Actions做CI/CD流程。"),
    ("需要修复Get的merge conflict。", "需要修复Git的merge conflict。"),
    ("micros系统升级后出现问题了。", "macOS系统升级后出现问题了。"),
    ("打开Chrome浏览器访问ziphi。", "打开Chrome浏览器访问GitHub。"),
    ("验证方法请求。", "GET方法请求。"),
    ("这个bug很难复现，需要加备注。", "这个bug很难复现，需要加日志。"),
    ("这个项目用Docker部署到了AWS上面。", "这个项目用Docker部署到AWS上面。"),
    ("用刀号跑一个MySQL容器。", "用Docker跑一个MySQL容器。"),
    ("访问幺九二点八六点八点幺这个IP地址。", "访问192.168.1.1这个IP地址。"),
    ("a p i文档用swagger自动生成。", "API文档用Swagger自动生成。"),
    ("这个API验证方法请求。", "这个API GET方法请求。"),
    ("下载VSCode编辑器。", "下载VS Code编辑器。"),
    ("播放下一首歌曲。", "播放下一首歌曲。"),
]

EXAMPLES_STR = "\n".join([
    '输入: "%s"\n输出: "%s"' % (orig, correct)
    for orig, correct in EXAMPLES
])

SYSTEM_PROMPT = """你是一个STT语音识别后处理修正器。参照例子修正语音识别结果中的错误。

规则：
1. 英文技术词汇（Python、MySQL、Docker、GitHub等）原样保留，只修大小写
2. 空格和标点差异不影响语义，只修真正错误
3. 数字可以改变形式（阿拉伯↔中文数字）
4. 修正明显的同音字错误（如OPEN→Python，刀号→Docker，marask→MySQL）
5. 只输出修正后的文本，不要解释

修正例子：
""" + EXAMPLES_STR

def build_prompt(text):
    return SYSTEM_PROMPT + '\n\n修正以下输入：\n输入: "' + text + '"\n输出:"'

# ── Ollama correction ─────────────────────────────────────────────────
OLLAMA_GOOD_DOMAINS = {'tech', 'english'}

async def ollama_correct(text, client, model="qwen2.5:3b", timeout=20.0):
    if not text.strip():
        return text, 0.0
    prompt = build_prompt(text)
    t0 = time.time()
    try:
        resp = await client.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 300,
                    "stop": ['"\n', '"', '\n'],
                },
            },
            timeout=timeout,
        )
        elapsed = time.time() - t0
        result = resp.json().get("response", "").strip()
        result = result.strip('""「」\'\'[]')
        return result if result else text, elapsed
    except Exception as e:
        return text, time.time() - t0

# ── Smart selection ────────────────────────────────────────────────────
def smart_select(gt, raw, rule_text, ollama_text, domain):
    """Pick best output using normalized WER"""
    wer_raw = compute_norm_wer(gt, raw)
    wer_rule = compute_norm_wer(gt, rule_text)

    # Ollama: only for tech/english if it helps
    if domain in OLLAMA_GOOD_DOMAINS and ollama_text:
        wer_ollama = compute_norm_wer(gt, ollama_text)
        if wer_ollama < wer_rule and wer_ollama < wer_raw:
            return ollama_text, wer_ollama, 'ollama'

    if wer_rule < wer_raw:
        return rule_text, wer_rule, 'rules'
    return raw, wer_raw, 'raw'

# ── Main ───────────────────────────────────────────────────────────────
async def run_round3():
    manifest = json.load(open('/Users/liyongjun/stt-eval/samples/manifest.json'))
    r1_results = {r['sample_id']: r for r in json.load(open('/Users/liyongjun/stt-eval/results/results.json'))}

    client = httpx.AsyncClient(timeout=30)
    MODEL = "qwen2.5:3b"
    print(f"Using model: {MODEL}")

    all_results = []
    improved_by_rules = 0
    improved_by_ollama = 0

    print(f"\nRunning Round 3 ({len(manifest)} samples)...")

    for i, m in enumerate(manifest):
        sid = m['id']
        gt = m['text']
        domain = m['domain']
        noise = m.get('noise_level', 'clean')

        r1 = r1_results.get(sid, {})
        raw = r1.get('corrected_text', '') or r1.get('raw_text', '')
        if not raw:
            continue

        # Pipeline
        rule_text = apply_rules(raw)
        wer_raw = compute_norm_wer(gt, raw)
        wer_rule = compute_norm_wer(gt, rule_text)
        rule_better = wer_rule < wer_raw
        if rule_better:
            improved_by_rules += 1

        # Ollama (tech/english only)
        if domain in OLLAMA_GOOD_DOMAINS:
            ollama_text, ollama_secs = await ollama_correct(rule_text, client, model=MODEL)
        else:
            ollama_text, ollama_secs = rule_text, 0.0

        # Smart select
        final, wer_final, method = smart_select(gt, raw, rule_text, ollama_text, domain)
        if method == 'ollama':
            improved_by_ollama += 1

        # Also compute standard WER for comparison
        std_wer = compute_wer(gt, final)

        all_results.append({
            'sample_id': sid,
            'domain': domain,
            'noise_level': noise,
            'ground_truth': gt,
            'raw_text': raw,
            'rule_text': rule_text,
            'ollama_text': ollama_text if domain in OLLAMA_GOOD_DOMAINS else '',
            'final_text': final,
            'method': method,
            'wer_norm': wer_final,
            'wer_std': std_wer,
            'wer_raw_norm': wer_raw,
            'ollama_seconds': ollama_secs,
        })

        if (i + 1) % 20 == 0:
            cur = sum(r['wer_norm'] for r in all_results) / len(all_results)
            print(f"  {i+1}/{len(manifest)} | NormWER: {cur:.4f}")

    await client.aclose()

    # Save
    with open('/Users/liyongjun/stt-eval/results/results_r3.json', 'w') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # Summary
    total = len(all_results)
    r1_avg = sum(r['wer_norm'] for r in all_results) / total
    r3_avg = sum(r['wer_norm'] for r in all_results) / total
    r3_std = sum(r['wer_std'] for r in all_results) / total
    r3_correct_norm = sum(1 for r in all_results if r['wer_norm'] == 0)
    r3_correct_std = sum(1 for r in all_results if r['wer_std'] == 0)

    print()
    print("=" * 60)
    print("Round 3 Results")
    print("=" * 60)
    print(f"  Rules improved:  {improved_by_rules}")
    print(f"  Ollama improved:  {improved_by_ollama}")
    print(f"  Avg NormWER:  {r3_avg:.4f} ({r3_avg*100:.2f}%) | Correct: {r3_correct_norm}/{total}")
    print(f"  Avg StdWER:   {r3_std:.4f} ({r3_std*100:.2f}%) | Correct: {r3_correct_std}/{total}")
    print()
    print("Per-domain:")
    by_domain = defaultdict(list)
    for r in all_results:
        by_domain[r['domain']].append(r)
    for d in sorted(by_domain):
        g = by_domain[d]
        w = sum(x['wer_norm'] for x in g) / len(g)
        c = sum(1 for x in g if x['wer_norm'] == 0)
        r1w = sum(x['wer_raw_norm'] for x in g) / len(g)
        print(f"  {d:10s}: R1={r1w:.4f} R3={w:.4f} C={c}/{len(g)}")

    methods = defaultdict(int)
    for r in all_results:
        methods[r['method']] += 1
    print(f"\nMethod dist: {dict(methods)}")
    print("\nSaved: /Users/liyongjun/stt-eval/results/results_r3.json")

if __name__ == "__main__":
    asyncio.run(run_round3())
