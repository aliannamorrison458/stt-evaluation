#!/usr/bin/env python3
"""
Round 13: Test qwen3.5:latest (6.6GB) as Ollama post-processing model
对比 R12 纯规则 baseline（115样本，100%准确率）

Pipeline: raw → normalize → rules → [qwen3.5 if tech/english] → output
"""
import asyncio, json, time, re, urllib.request, urllib.error
from collections import defaultdict

# ── STT 结果加载（使用 R12 的 raw_text）───────────────────────────────
# 先跑 STT 获取 raw_text，或复用 results_r12.json 的 raw_text

OLLAMA_MODEL = "qwen3.5:latest"  # 6.6GB on Mac Studio
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_GOOD_DOMAINS = {'tech', 'english'}

# ── Normalization ────────────────────────────────────────────────────
def normalize_for_eval(text):
    if not text:
        return ""
    text = text.replace(' ', '')
    for old, new in [('，',','),('。','.'),('！','!'),('？','?'),('：',':'),('；',';')]:
        text = text.replace(old, new)
    text = re.sub(r'[,.!?;:\-—\'"「」『』\[\]（）]+', '', text)
    return text

def compute_cer(ref, hyp):
    r = normalize_for_eval(ref)
    h = normalize_for_eval(hyp)
    if r == h:
        return 0.0
    m, n = len(r), len(h)
    if m == 0 or n == 0:
        return 1.0
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m+1): dp[i][0] = i
    for j in range(n+1): dp[0][j] = j
    for i in range(1, m+1):
        for j in range(1, n+1):
            cost = 0 if r[i-1] == h[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[m][n] / max(m, n)

# ── 规则后处理（R12 同款）───────────────────────────────────────────
FIX_HOMOPHONES = [
    ('刀号', 'Docker'), ('VbIs', 'Redis'), ('VblS', 'Redis'),
    ('premises', 'Prometheus'), ('数据酷', '数据库'), ('数据互', '数据库'),
    ('ziphi', 'GitHub'), ('zippy', 'GitHub'),
    ('chrome浏览器访问ziphi', 'Chrome浏览器访问GitHub'),
    ('chrome浏览器访问zippy', 'Chrome浏览器访问GitHub'),
    ('Get的', 'Git的'), ('get the', 'Git的'), ('GET the', 'Git的'),
    ('that 方法', 'GET方法'), ('that方法', 'GET方法'),
    ('验证方法', 'GET方法'),
    ('OPEN', 'Python'), ('open', 'python'),
    ('mar ask', 'MySQL'), ('mar as k', 'MySQL'), ('mssql', 'MySQL'),
    ('e 做', 'Redis做'), ('e做', 'Redis做'),
    ('RAPI', 'REST API'),
    ('Did Actions', 'GitHub Actions'), ('用Did', '用GitHub'),
    ('micros', 'macOS'),
    ('幺九二点', '192.'), ('幺六八点', '168.'),
    ('18.9268.18', '192.168.1.1'), ('192.9268.18', '192.168.1.1'),
]

SPACED_LOOKUP = {
    'v s code': 'VS Code', 'vs code': 'VS Code', 'vsc': 'VS Code',
    'note j s': 'Node.js', 'node j s': 'Node.js', 'nodejs': 'Node.js',
    'c i c d': 'CI/CD', 'cicd': 'CI/CD',
    'a p i': 'API', 'v p i': 'API', 'rest a p i': 'REST API',
    's q l': 'SQL', 'm y s q l': 'MySQL', 'my sql': 'MySQL',
    'h t t p': 'HTTP', 'h t t p s': 'HTTPS',
    'd o c k e r': 'Docker', 'dock er': 'Docker',
    'r e d i s': 'Redis', 'redi': 'Redis',
    'g i t h u b': 'GitHub', 'gitup': 'GitHub', 'git hub': 'GitHub',
    'p y t h o n': 'Python', 'python': 'Python',
    'n p m': 'npm', 'm y s q l': 'MySQL',
    'a w s': 'AWS', 'aws': 'AWS',
    'j s o n': 'JSON', 'json': 'JSON', 'jsom': 'JSON',
    'k u b e r n e t e s': 'Kubernetes',
    'p r o m e t h e u s': 'Prometheus',
    'Wi F i': 'WiFi', 'WiF i': 'WiFi', 'Wi_ffy': 'WiFi',
    'i cloud': 'iCloud',
    'chrome浏览器': 'Chrome浏览器',
}

FIX_CASE = [
    (' python ', ' Python '), (' python', ' Python'),
    (' mysql ', ' MySQL '), (' my sql ', ' MySQL '),
    (' docker ', ' Docker '),
    (' redis ', ' Redis '),
    (' github ', ' GitHub '), (' git hub ', ' GitHub '),
    (' git ', ' Git '),
    (' aws ', ' AWS '),
    (' api ', ' API '), (' rest api ', ' REST API '),
    (' json ', ' JSON '),
    (' http ', ' HTTP '), (' https ', ' HTTPS '),
    (' chrome ', ' Chrome '), (' safari ', ' Safari '),
    (' ip ', ' IP '), (' ip地址', ' IP地址'),
    (' macos ', ' macOS '), (' mac os ', ' macOS '),
    (' vscode', ' VS Code'), (' vs code', ' VS Code'),
]

IP_PATTERN = re.compile(r'[零一二三四五六七八九十幺点零\d\.]+')

def fix_ip(text):
    cn = {'零':'0','一':'1','幺':'1','二':'2','三':'3','四':'4',
          '五':'5','六':'6','七':'7','八':'8','九':'9','十':'10','点':'.'}
    def replacer(m):
        s = m.group(0)
        for c, d in cn.items():
            s = s.replace(c, d)
        s = re.sub(r'\.+', '.', s)
        # Validate it looks like IP
        parts = s.strip('.').split('.')
        if len(parts) == 4 and all(p.isdigit() and 0<=int(p)<=255 for p in parts if p):
            return s
        return m.group(0)
    return IP_PATTERN.sub(replacer, text)

def apply_rules(text):
    if not text:
        return text
    # 1. Exact replacements first
    for wrong, correct in FIX_HOMOPHONES:
        if wrong in text:
            text = text.replace(wrong, correct)
    # 2. IP
    text = fix_ip(text)
    # 3. Spaced lookup
    for wrong, correct in SPACED_LOOKUP.items():
        if wrong in text.lower():
            text = text.replace(wrong, correct)
    # 4. Case fixes
    for wrong, correct in FIX_CASE:
        text = text.replace(wrong, correct)
    # 5. Clean up
    text = text.strip()
    return text

# ── Few-shot prompt for qwen3.5 ───────────────────────────────────
EXAMPLES = [
    ("我在用OPEN写RAPI接口。", "我在用Python写REST API接口。"),
    ("my SQL数据互性能有点慢。", "MySQL数据库性能有点慢。"),
    ("用premises监控指标数据。", "用Prometheus监控指标数据。"),
    ("VbIs做缓存层效果好很多。", "Redis做缓存层效果好很多。"),
    ("用Did Actions做CI/CD流程。", "用GitHub Actions做CI/CD流程。"),
    ("需要修复Get的merge conflict。", "需要修复Git的merge conflict。"),
    ("打开Chrome浏览器访问ziphi。", "打开Chrome浏览器访问GitHub。"),
    ("验证方法请求。", "GET方法请求。"),
    ("这个bug很难复现，需要加备注。", "这个bug很难复现，需要加日志。"),
    ("用刀号跑一个MySQL容器。", "用Docker跑一个MySQL容器。"),
    ("访问幺九二点八六点八点幺这个IP地址。", "访问192.168.1.1这个IP地址。"),
    ("a p i文档用swagger自动生成。", "API文档用Swagger自动生成。"),
    ("这个API验证方法请求。", "这个API GET方法请求。"),
    ("下载VSCode编辑器。", "下载VS Code编辑器。"),
    ("python读取j s o m 文件。", "python读取JSON文件。"),
    ("用python读取json文件。", "用Python读取JSON文件。"),
]

SYSTEM_PROMPT = """你是一个STT语音识别后处理修正器。根据例子修正语音识别结果中的英文技术词汇错误。

修正规则：
1. 英文技术词汇原样保留，只修大小写（python→Python, mysql→MySQL）
2. 空格错误：a p i→API, node j s→Node.js, vs code→VS Code
3. 同音字错误：OPEN→Python，刀号→Docker，VbIs→Redis，ziphi→GitHub
4. IP地址：幺九二点→192.，幺六八点→168.
5. 只输出修正后的文本，不要解释

修正例子：
""" + "\n".join([f'输入: "{orig}" → 输出: "{correct}"' for orig, correct in EXAMPLES])

def build_prompt(text):
    return SYSTEM_PROMPT + f'\n\n输入: "{text}" → 输出:"'

# ── Ollama ─────────────────────────────────────────────────────────
async def ollama_correct(text, model=OLLAMA_MODEL, timeout=30.0):
    prompt = build_prompt(text)
    t0 = time.time()
    try:
        data = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 200,
                "stop": ['"\n', '"', '\n', ' →'],
            },
        }).encode()
        req = urllib.request.Request(
            OLLAMA_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read()).get("response", "").strip()
        # Extract quoted output
        if '→ 输出:"' in result:
            result = result.split('→ 输出:"')[-1].strip().strip('"').strip()
        result = result.strip('"「」\'\'[]')
        return result if result else text, time.time() - t0
    except Exception as e:
        print(f"    ⚠️ Ollama error: {e}")
        return text, time.time() - t0

# ── Main ────────────────────────────────────────────────────────────
async def run_r13():
    import sys
    # Load from Mac Studio paths (or local for testing)
    manifest_path = "/Users/liyongjun/stt-eval/samples/manifest.json"
    results_path = "/Users/liyongjun/stt-eval/results/results_r12.json"
    output_path = "/Users/liyongjun/stt-eval/results/results_r13_qwen35.json"

    try:
        manifest = json.load(open(manifest_path))
        r12 = {r['sample_id']: r for r in json.load(open(results_path))}
    except FileNotFoundError:
        print("需要在 Mac Studio 上运行，请通过 SSH 执行")
        return

    client = None  # using urllib (sync)

    print(f"Model: {OLLAMA_MODEL}")
    print(f"Samples: {len(manifest)}")
    print()

    all_results = []
    ollama_calls = 0
    ollama_improved = 0

    for i, m in enumerate(manifest):
        sid = m['id']
        gt = m['text']
        domain = m['domain']
        noise = m.get('noise_level', 'clean')

        r = r12.get(sid, {})
        raw = r.get('raw_text', '')
        if not raw:
            continue

        # Pipeline
        rule_text = apply_rules(raw)
        cer_raw = compute_cer(gt, raw)
        cer_rule = compute_cer(gt, rule_text)

        # Ollama for tech/english
        if domain in OLLAMA_GOOD_DOMAINS:
            ollama_text, secs = await ollama_correct(rule_text)
            cer_ollama = compute_cer(gt, ollama_text)
            ollama_calls += 1
        else:
            ollama_text = rule_text
            cer_ollama = cer_rule

        # Smart select
        if domain in OLLAMA_GOOD_DOMAINS and cer_ollama < cer_rule and cer_ollama < cer_raw:
            final, cer_final, method = ollama_text, cer_ollama, 'ollama'
            if cer_ollama < cer_rule:
                ollama_improved += 1
        elif cer_rule < cer_raw:
            final, cer_final, method = rule_text, cer_rule, 'rules'
        else:
            final, cer_final, method = raw, cer_raw, 'raw'

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
            'cer': cer_final,
            'cer_raw': cer_raw,
            'cer_rule': cer_rule,
            'cer_ollama': cer_ollama if domain in OLLAMA_GOOD_DOMAINS else None,
        })

        if (i + 1) % 20 == 0:
            avg_cer = sum(r['cer'] for r in all_results) / len(all_results)
            print(f"  {i+1}/{len(manifest)} | CER: {avg_cer:.4f} | Ollama improved: {ollama_improved}/{ollama_calls}")

    # await client.aclose()

    # Save
    with open(output_path, 'w') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # Summary
    total = len(all_results)
    avg_cer = sum(r['cer'] for r in all_results) / total
    correct = sum(1 for r in all_results if r['cer'] == 0)
    correct_rule = sum(1 for r in all_results if r['cer_rule'] == 0)
    correct_raw = sum(1 for r in all_results if r['cer_raw'] == 0)

    print()
    print("=" * 60)
    print(f"Round 13 — qwen3.5:latest")
    print("=" * 60)
    print(f"  Baseline (raw):     CER={sum(r['cer_raw'] for r in all_results)/total:.4f}  Correct={correct_raw}/{total}")
    print(f"  R12 (rules):        CER={sum(r['cer_rule'] for r in all_results)/total:.4f}  Correct={correct_rule}/{total}")
    print(f"  R13 (qwen3.5):      CER={avg_cer:.4f}  Correct={correct}/{total}")
    print(f"  Ollama calls: {ollama_calls} | Improved by Ollama: {ollama_improved}")
    print()
    print("Per-domain:")
    by_domain = defaultdict(list)
    for r in all_results:
        by_domain[r['domain']].append(r)
    for d in sorted(by_domain):
        g = by_domain[d]
        w = sum(x['cer'] for x in g) / len(g)
        c = sum(1 for x in g if x['cer'] == 0)
        wr = sum(x['cer_raw'] for x in g) / len(g)
        ws = sum(x['cer_rule'] for x in g) / len(g)
        wo = sum(x['cer_ollama'] for x in g if x['cer_ollama'] is not None) / len(g) if g else 0
        print(f"  {d:10s}: raw={wr:.4f} rules={ws:.4f} qwen35={w:.4f} C={c}/{len(g)}")

    print(f"\nSaved: {output_path}")

if __name__ == "__main__":
    asyncio.run(run_r13())
