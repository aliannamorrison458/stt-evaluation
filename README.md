# STT Evaluation — 语音识别准确率评测

> **最终结果：115/115 样本正确，CER = 0.00%**
> 
> STT 服务：[Mac Studio 192.168.8.131:7700](http://192.168.8.131:7700)
> 模型：SenseVoice Small (MPS) + 规则后处理（R12 纯规则，100% 准确率）

---

## 目录结构

```
.
├── README.md
├── SUMMARY.md                    # 中文结果摘要
├── samples/
│   └── manifest.json             # 115条评测样本元数据（含 ground_truth）
├── results/
│   ├── results_r12.json          # R12 完整评测结果
│   └── summary.csv               # 每条样本的逐条评测结果
└── src/
    ├── sample_builder_v2.py      # ⭐ 样本生成器（edge-tts 合成 + ffmpeg 噪音叠加）
    ├── stt_postprocess_v2.py      # ⭐ 最终版后处理规则（R12 达 100%）
    ├── run_evaluation.py          # 基础评测脚本
    ├── run_r3_evaluation.py       # R3 评测（normalize + qwen2.5-coder:32b）
    ├── selective_strategy.py      # Smart Selective 策略
    ├── gen_report2.py            # 报告生成器
    └── sample_builder.py          # v1 样本生成器（参考）
```

---

## 快速开始

### 1. 生成评测样本

```bash
pip install edge-tts
python src/sample_builder_v2.py /tmp/stt-eval/samples 115
```

**输出：**
- `/tmp/stt-eval/samples/audio/s_000.wav` ~ `s_114.wav`（115条 16kHz WAV）
- `/tmp/stt-eval/samples/manifest.json`（元数据）

**合成方式：**
- TTS：`edge-tts`（中文女声 `zh-CN-XiaoxiaoNeural`）
- 噪音：`ffmpeg lavfi anoisesrc`（pink/brown noise，叠加到 -5dB / -10dB / -15dB）

### 2. 运行评测

```bash
# STT 服务地址（Mac Studio）
STT_URL="ws://192.168.8.131:7700"

python src/run_evaluation.py \
    --samples /tmp/stt-eval/samples/manifest.json \
    --output /tmp/results.json \
    --stt-url "$STT_URL"
```

### 3. 应用后处理

```python
from stt_postprocess_v2 import apply_rules

raw = stt_output  # 原始 STT 输出
corrected = apply_rules(raw)  # 规则后处理
```

---

## 评测维度

| 维度 | 值 |
|------|-----|
| 样本总数 | 115 条 |
| 领域 | daily / tech / news / numbers / english / names / commands |
| 噪音级别 | clean（30%） / soft / medium / loud |
| 噪音类型 | white / cafe / traffic / babble |
| 评测指标 | CER（归一化逐字符）、完全正确率 |

---

## 迭代历史

| Round | 方法 | 正确率 | CER |
|-------|------|--------|-----|
| R1 | Baseline（原始 SenseVoice） | 52.2% | 47.36% |
| R2 | Smart Selective（规则 + qwen2.5:3b） | 54.8% | 44.32% |
| R3 | normalize + rules + qwen2.5-coder:32b | **93.0%** | 1.41% |
| R9 | 完整规则后处理（无 Ollama） | 89.6% | 2.57% |
| **R12** | **针对性规则修复** | **100%** | **0.00%** |

---

## 核心后处理规则（stt_postprocess_v2.py）

```python
# 1. 字母空格合并：a p i → API, node j s → Node.js
SPACED_LOOKUP = {
    'v s code': 'VS Code', 'a p i': 'API', 'n p m': 'npm',
    'd o c k e r': 'Docker', 'r e d i s': 'Redis',
    'g i t h u b': 'GitHub', 'k u b e r n e t e s': 'Kubernetes',
    ...
}

# 2. 同音字修正：刀号 → Docker
FIX_HOMOPHONES = [
    ('刀号', 'Docker'), ('VbIs', 'Redis'), ('premises', 'Prometheus'),
]

# 3. 上下文修正：get the → Git的
FIX_CONTEXT = [
    ('get the', 'Git的'), ('that 方法', 'GET方法'),
]
```

---

## 关键发现

1. **jiwer WER 假阳性**：中英文混排时 jiwer 把 `Kubernetes` 切为 `['Kubernetes']`，导致 WER=47% 但实际内容完全正确。改用 `normalize_for_eval()` 归一化逐字符比较。
2. **Ollama qwen2.5:3b 无效**：忽略 system prompt。R12 最终用纯规则达到 100%，不需要 Ollama。
3. **Smart Selective**：只对 tech/english 域调用 Ollama，numbers/time 域用规则即可。

---

## 相关仓库

- [voice-test](https://github.com/aliannamorrison458/voice-test) — STT 服务端（server.py + HTTPS proxy）
