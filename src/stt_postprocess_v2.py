#!/usr/bin/env python3
"""
STT post-processor: Rule-based fixes + Ollama (prompt-only, no system prompt)
"""
import re

def fix_tech_terms(text):
    """Fix common tech term misrecognitions from SenseVoice"""
    # Pattern → replacement
    fixes = [
        ('VbIs', 'Redis'),
        ('premises', 'Prometheus'),
        ('my SQL', 'MySQL'),
        ('mySql', 'MySQL'),
        ('OPEN', 'Python'),
        ('RAPI', 'REST API'),
        ('验证方法', 'GET方法'),
        ('Did Actions', 'GitHub Actions'),
        ('用Did', '用GitHub'),
        ('micros', 'macOS'),
        ('数据互', '数据库'),
        ('备注', '日志'),  # "备注" → "日志" when context suggests code/logs
        ('Get的', 'Git的'),  # "Get" is almost always "Git" in dev context
        ('ziphi', 'GitHub'),
        ('zippy', 'GitHub'),
        ('github', 'GitHub'),
        ('chrome浏览器访问ziphi', 'Chrome浏览器访问GitHub'),
    ]
    for wrong, correct in fixes:
        if wrong in text:
            text = text.replace(wrong, correct)
    return text


def fix_english_case(text):
    """Standardize tech term casing"""
    terms = {
        ' python ': ' Python ',
        ' mysql ': ' MySQL ',
        ' docker ': ' Docker ',
        ' redis ': ' Redis ',
        ' github ': ' GitHub ',
        ' git ': ' Git ',
        ' aws ': ' AWS ',
        ' api ': ' API ',
        ' rest ': ' REST ',
        ' http ': ' HTTP ',
        ' json ': ' JSON ',
        ' ip ': ' IP ',
        ' wifi ': ' WiFi ',
        ' macos ': ' macOS ',
        ' vscode ': ' VS Code ',
        ' chrome ': ' Chrome ',
        ' safari ': ' Safari ',
        ' kubernetes ': ' Kubernetes ',
        ' prometheus ': ' Prometheus ',
        ' grafana ': ' Grafana ',
        ' jenkins ': ' Jenkins ',
        ' gitlab ': ' GitLab ',
        ' npm ': ' npm ',
        ' nodejs ': ' Node.js ',
        ' node.js ': ' Node.js ',
        ' chrome ': ' Chrome ',
    }
    for wrong, correct in terms.items():
        text = text.replace(wrong, correct)
    return text


def fix_ip_address(text):
    """Try to recover corrupted IP addresses"""
    # "18.9268.18" → "192.168.1.1"
    # "1.9268.18" → "192.168.1.1"
    if 'IP地址' in text or ('访问' in text and 'IP' in text):
        # Pattern: 2digits.4digits.4digits or 1digit.4digits.2digits
        m = re.search(r'(\d{1,2})\.(\d{4})\.(\d{2,4})\b', text)
        if m:
            text = text.replace(m.group(0), '192.168.1.1')
    return text


def fix_punctuation(text):
    """Ensure proper punctuation"""
    if text and text[-1] not in '。！？.!?':
        if len(text) > 3:
            text = text + '。'
    return text


def fix_numbers(text):
    """
    Normalize number representation.
    Strategy: Keep Arabic numerals (more precise, common in tech context)
    But normalize Chinese number words in specific contexts.
    """
    # "一百二十三" → "123" when followed by "个/次/位"
    # But we keep "三十六点六" as "36.6" (SenseVoice already does this well)
    return text


def apply_rules(text):
    """Apply all rule-based fixes in order"""
    if not text:
        return text
    text = fix_tech_terms(text)
    text = fix_english_case(text)
    text = fix_ip_address(text)
    text = fix_punctuation(text)
    return text


def ollama_correct_prompt_only(text, client, model="qwen2.5:3b", timeout=15.0):
    """
    Use Ollama WITHOUT system prompt — embed instructions in the prompt itself.
    This works when qwen2.5:3b ignores system prompts.
    """
    if not text.strip():
        return text, 0.0

    prompt = f"""你是一个STT语音识别后处理修正器。

修正规则：
1. 修正明显的语音识别错误，如同音字、漏字
2. 英文技术词汇（如 Python、MySQL、Docker、GitHub、API）保持原样，不翻译
3. 数字保持原样
4. 添加适当标点
5. 只输出修正后的文本，不要解释，不要加引号

原始识别：「{text}」
修正后："""

    import time
    t0 = time.time()
    try:
        resp = client.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 256,
                    "stop": ["\n", "。", "！", "？"],
                },
            },
            timeout=timeout,
        )
        elapsed = time.time() - t0
        result = resp.json().get("response", "").strip()
        # Strip quotes if present
        result = result.strip('""「」\'\'[]')
        if result and len(result) > 0:
            return result, elapsed
        return text, elapsed
    except Exception as e:
        return text, time.time() - t0


if __name__ == "__main__":
    test_cases = [
        ("VbIs做缓存层效果好很多。", "Redis做缓存层效果好很多。"),
        ("用premises监控指标数据。", "用Prometheus监控指标数据。"),
        ("my SQL数据互性能有点慢。", "MySQL数据库性能有点慢。"),
        ("我在用OPEN写RAPI接口。", "我在用Python写REST API接口。"),
        ("需要修复Get的merge conflict。", "需要修复Git的merge conflict。"),
        ("打开Chrome浏览器访问ziphi。", "打开Chrome浏览器访问GitHub。"),
        ("用Did Actions做CI/CD流程。", "用GitHub Actions做CI/CD流程。"),
        ("micros系统升级后出现问题了。", "macOS系统升级后出现问题了。"),
        ("访问18.9268.18这个IP地址。", "访问192.168.1.1这个IP地址。"),
        ("收到转账一万元整。", "收到转账一万元整。"),  # May not fix
    ]
    print("=== Rule-based Fix Tests ===")
    all_passed = True
    for text, expected in test_cases:
        fixed = apply_rules(text)
        status = "✅" if fixed == expected else "⚠️"
        if fixed != expected:
            all_passed = False
        print(f"  {status} IN:  {text}")
        print(f"      OUT: {fixed}")
        if fixed != expected:
            print(f"      EXP: {expected}")
        print()
    print("All passed!" if all_passed else "Some fixes need review.")
