#!/usr/bin/env python3
"""
STT Evaluation Sample Builder
生成 100+ 多样化测试样本，支持背景噪音叠加
"""
import os
import random
import subprocess
import json
from pathlib import Path

# ── 评测维度 ──────────────────────────────────────────
SPEED_VARIANTS = ["slow", "normal", "fast"]
NOISE_LEVELS = ["clean", "soft", "medium", "loud"]
DOMAINS = [
    "daily",        # 日常对话
    "tech",         # 技术术语
    "news",         # 新闻播报
    "numbers",      # 数字/金额
    "english",      # 中英混杂
    "names",        # 人名/地名
    "commands",     # 语音指令
]

# ── 合成音频用的文本样本 ───────────────────────────────
# 每个 domain 多个变体，确保多样性
SYNTHESIS_SAMPLES = {
    "daily": [
        "今天天气真好，我们出去散步吧。",
        "我想喝一杯咖啡，要不要一起？",
        "这个电影非常精彩，推荐大家去看。",
        "明天要早起，记得定好闹钟。",
        "晚上吃什么好呢，火锅还是烧烤？",
        "这本书很有意思，我已经看了三遍了。",
        "周末有什么计划吗？",
        "路上堵车可能要晚一点到。",
        "记得带伞，今天下午有雨。",
        "你好，请问这个怎么走？",
    ],
    "tech": [
        "我在用 Python 写 REST API 接口。",
        "这个项目用 Docker 部署到 AWS 上面。",
        "需要修复 Git 的 merge conflict。",
        "MySQL 数据库性能有点慢。",
        "用 GitHub Actions 做 CI/CD 流程。",
        "这个 bug 很难复现，需要加日志。",
        "macOS 系统升级后 Docker 出问题了。",
        "用 Redis 做缓存层效果好很多。",
        "API 文档用 Swagger 自动生成。",
        "测试覆盖率需要提升到百分之八十以上。",
    ],
    "news": [
        "今天上午国务院召开新闻发布会。",
        "经济增长保持稳中向好态势。",
        "科技创新取得重大突破性进展。",
        "房地产市场调控政策效果显现。",
        "教育公平进一步得到保障。",
        "环境保护工作取得积极成效。",
        "文化产业发展势头强劲。",
        "医疗卫生体制改革持续深化。",
        "社会保障体系不断完善。",
        "乡村振兴战略深入实施。",
    ],
    "numbers": [
        "我的电话号码是一三八幺二三四五六七八。",
        "总价是九千九百九十九块九毛九。",
        "一共买了一百二十三个苹果。",
        "时间是下午三点四十五分。",
        "体温是三十六点六度，正常。",
        "距离目的地还有二十公里。",
        "参加人数大约是三百人左右。",
        "增长率为百分之二十三点五。",
        "收到转账一万两千元整。",
        "快递单号以九四三二开头。",
    ],
    "english": [
        "打开 Chrome 浏览器访问 GitHub。",
        "这个 API 用 GET 方法请求。",
        "下载 VS Code 编辑器。",
        "登录 iCloud 账号同步数据。",
        "用 Docker 跑一个 MySQL 容器。",
        "收到一封 Email 来自 HR。",
        "把文件上传到 Google Drive。",
        "用 Python 读取 JSON 文件。",
        "访问 192.168.1.1 这个 IP 地址。",
        "安装 Node.js 和 npm 包管理器。",
    ],
    "names": [
        "李明和王小红去看了张艺谋的新电影。",
        "上海浦东机场今天航班延误了。",
        "北京大学的王教授做了报告。",
        "深圳华为总部参观需要预约。",
        "阿里巴巴和腾讯都是大公司。",
        "特朗普和拜登进行了辩论。",
        "去成都要吃火锅和兔头。",
        "杭州西湖的风景真美。",
        "特斯拉汽车销量创新高。",
        "微信和支付宝都可以付款。",
    ],
    "commands": [
        "帮我打开音乐播放器。",
        "把空调温度调到二十六度。",
        "导航去最近的加油站。",
        "设置一个明天早上七点的闹钟。",
        "播放下一首歌曲。",
        "关掉客厅的灯。",
        "给我妈妈打个电话。",
        "查看一下明天的天气。",
        "把这个链接分享给张三。",
        "帮我叫一辆出租车。",
    ],
}

def get_all_samples():
    """展平所有样本，随机打乱"""
    all_samples = []
    for domain, texts in SYNTHESIS_SAMPLES.items():
        for text in texts:
            all_samples.append({"text": text, "domain": domain})
    random.shuffle(all_samples)
    return all_samples

def ensure_tool(cmd):
    """检查工具是否存在"""
    result = subprocess.run(f"which {cmd}", shell=True, capture_output=True)
    return result.returncode == 0

def synthesize_audio(text, output_path, voice="zh-CN-XiaoxiaoNeural"):
    """用 edge-tts 合成音频"""
    if not ensure_tool("edge-tts"):
        raise RuntimeError("edge-tts not installed. Run: pip install edge-tts")

    import asyncio
    import edge_tts

    async def _synth():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)

    asyncio.run(_synth())

def add_noise(clean_audio, noisy_audio, noise_type, level):
    """叠加背景噪音"""
    # 使用 ffmpeg 叠加噪音
    # noise_type: cafe | babble | traffic | white
    # level: soft(10dB) | medium(5dB) | loud(0dB)
    import subprocess

    noise_db_map = {"soft": "-15", "medium": "-10", "loud": "-5"}
    noise_db = noise_db_map.get(level, "-10")

    # 先生成噪音文件
    noise_file = noisy_audio.replace(".wav", f"_{noise_type}_noise.wav")

    if noise_type == "white":
        # 生成白噪音
        subprocess.run([
            "ffmpeg", "-f", "lavfi", "-i", f"anoisesrc=d={get_duration(clean_audio)}:c=pink",
            "-ar", "16000", "-ac", "1", "-y", noise_file
        ], capture_output=True)
    elif noise_type == "cafe":
        # 用高斯噪音模拟咖啡馆
        subprocess.run([
            "ffmpeg", "-f", "lavfi", "-i", f"anoisesrc=d={get_duration(clean_audio)}:c=brown",
            "-ar", "16000", "-ac", "1", "-y", noise_file
        ], capture_output=True)
    elif noise_type == "traffic":
        subprocess.run([
            "ffmpeg", "-f", "lavfi", "-i", f"anoisesrc=d={get_duration(clean_audio)}:c=pink",
            "-ar", "16000", "-ac", "1", "-af", "lowpass=f=300", "-y", noise_file
        ], capture_output=True)
    elif noise_type == "babble":
        subprocess.run([
            "ffmpeg", "-f", "lavfi", "-i", f"anoisesrc=d={get_duration(clean_audio)}:c=white",
            "-ar", "16000", "-ac", "1", "-af", "highpass=f=200,lowpass=f=3000",
            "-y", noise_file
        ], capture_output=True)

    # 混合
    subprocess.run([
        "ffmpeg", "-y",
        "-i", clean_audio,
        "-i", noise_file,
        "-filter_complex", f"[1:a]volume={noise_db}dB[noise];[0:a][noise]amix=inputs=2:duration=longest",
        "-ar", "16000", "-ac", "1", noisy_audio
    ], capture_output=True)

    os.unlink(noise_file)

def get_duration(audio_path):
    """获取音频时长（秒）"""
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path
    ], capture_output=True, text=True)
    return float(result.stdout.strip())

def resample_to_16k(audio_path, output_path):
    """重采样到 16kHz 单声道"""
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_path,
        "-ar", "16000", "-ac", "1", output_path
    ], capture_output=True)

def build_samples(output_dir, target_count=120):
    """构建完整测试集"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = get_all_samples()
    # 补足到 target_count
    while len(samples) < target_count:
        domain = random.choice(DOMAINS)
        samples.append({
            "text": random.choice(SYNTHESIS_SAMPLES[domain]),
            "domain": domain
        })
    samples = samples[:target_count]

    manifest = []
    noise_types = ["white", "cafe", "traffic", "babble"]
    noise_levels = ["soft", "medium", "loud"]

    for i, sample in enumerate(samples):
        text = sample["text"]
        domain = sample["domain"]

        # 随机决定噪音级别
        if random.random() < 0.3:
            noise_level = "clean"
            noise_type = None
        else:
            noise_level = random.choice(noise_levels)
            noise_type = random.choice(noise_types)

        # 合成干净音频
        clean_wav = output_dir / f"sample_{i:03d}_clean.wav"
        synthesize_audio(text, str(clean_wav))

        if noise_level == "clean":
            final_wav = clean_wav
        else:
            final_wav = output_dir / f"sample_{i:03d}_{noise_type}_{noise_level}.wav"
            add_noise(str(clean_wav), str(final_wav), noise_type, noise_level)

        # 统一重采样到 16kHz
        final_16k = output_dir / f"sample_{i:03d}.wav"
        resample_to_16k(str(final_wav), str(final_16k))
        if final_wav != clean_wav:
            os.unlink(str(final_wav))
        os.unlink(str(clean_wav))

        manifest.append({
            "id": i,
            "text": text,
            "domain": domain,
            "noise_type": noise_type,
            "noise_level": noise_level,
            "audio_file": str(final_16k),
        })

    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"✅ 生成了 {len(manifest)} 个样本 -> {output_dir}")
    print(f"📋 Manifest: {manifest_path}")
    return manifest

if __name__ == "__main__":
    import sys
    output = sys.argv[1] if len(sys.argv) > 1 else "/tmp/stt-eval/samples"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    build_samples(output, count)
