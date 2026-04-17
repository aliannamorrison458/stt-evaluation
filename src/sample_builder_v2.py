#!/usr/bin/env python3
"""
STT Evaluation Sample Builder v2
顺序合成 + 噪音叠加，异常隔离
"""
import asyncio
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import edge_tts

# ── 评测维度 ──────────────────────────────────────────
DOMAINS = ["daily", "tech", "news", "numbers", "english", "names", "commands"]
NOISE_TYPES = ["white", "cafe", "traffic", "babble"]
NOISE_LEVELS = ["soft", "medium", "loud"]

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
        "去超市买点水果回来。",
        "今天太累了想早点休息。",
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
        "在 Kubernetes 集群里部署服务。",
        "用 Prometheus 监控指标数据。",
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
        "对外贸易总额创历史新高。",
        "体育事业取得新成就。",
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
        "股票涨了百分之十五。",
        "体重是六十八点五公斤。",
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
        "打开 Safari 浏览网页。",
        "连接 WiFi 无线网络。",
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
        "苹果公司的市值全球第一。",
        "刘德华和周杰伦开演唱会。",
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
        "播放暂停停止音乐。",
        "调高电视机的音量。",
    ],
}


def get_all_samples(target_count=120):
    all_samples = []
    for domain, texts in SYNTHESIS_SAMPLES.items():
        for text in texts:
            all_samples.append({"text": text, "domain": domain})
    # 随机打乱
    random.shuffle(all_samples)
    # 循环补足
    while len(all_samples) < target_count:
        domain = random.choice(DOMAINS)
        all_samples.append({
            "text": random.choice(SYNTHESIS_SAMPLES[domain]),
            "domain": domain,
        })
    return all_samples[:target_count]


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


async def synthesize_one(text, output_mp3):
    """合成单个音频，隔离异常"""
    try:
        comm = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
        await comm.save(output_mp3)
        return True
    except Exception as e:
        print(f"  ⚠️ edge-tts 失败: {e} | text={text[:20]}", flush=True)
        return False


def get_duration(audio_path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except Exception:
        return 5.0


def convert_to_16k_wav(mp3_path, wav_path):
    subprocess.run(
        ["ffmpeg", "-y", "-i", mp3_path,
         "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", wav_path],
        capture_output=True,
    )
    return Path(wav_path).stat().st_size > 0


def add_noise(clean_wav, noisy_wav, noise_type, level):
    """叠加背景噪音"""
    db_map = {"soft": "-15", "medium": "-10", "loud": "-5"}
    db = db_map.get(level, "-10")
    duration = get_duration(clean_wav)

    # 生成噪音
    noise_wav = noisy_wav + ".noise.wav"
    try:
        if noise_type == "white":
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anoisesrc=d={duration}:c=pink",
                 "-ar", "16000", "-ac", "1", noise_wav],
                capture_output=True, timeout=60,
            )
        elif noise_type == "cafe":
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anoisesrc=d={duration}:c=brown",
                 "-ar", "16000", "-ac", "1", noise_wav],
                capture_output=True, timeout=60,
            )
        elif noise_type == "traffic":
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anoisesrc=d={duration}:c=pink",
                 "-ar", "16000", "-ac", "1", "-af", "lowpass=f=300", noise_wav],
                capture_output=True, timeout=60,
            )
        elif noise_type == "babble":
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anoisesrc=d={duration}:c=white",
                 "-ar", "16000", "-ac", "1", "-af", "highpass=f=200,lowpass=f=3000",
                 noise_wav],
                capture_output=True, timeout=60,
            )
    except Exception as e:
        print(f"  ⚠️ 噪音生成失败: {e}", flush=True)
        # fallback: 直接复制
        subprocess.run(["cp", clean_wav, noisy_wav])
        return

    # 混合
    try:
        subprocess.run(
            ["ffmpeg", "-y",
             "-i", clean_wav,
             "-i", noise_wav,
             "-filter_complex", f"[1:a]volume={db}dB[noise];[0:a][noise]amix=inputs=2:duration=longest",
             "-ar", "16000", "-ac", "1", noisy_wav],
            capture_output=True, timeout=60,
        )
    finally:
        if os.path.exists(noise_wav):
            os.unlink(noise_wav)


async def build_samples(output_dir, target_count=120):
    output_dir = Path(output_dir)
    ensure_dir(output_dir)
    ensure_dir(output_dir / "audio")

    print(f"🎤 开始生成 {target_count} 个样本...")
    samples = get_all_samples(target_count)
    manifest = []
    fail_count = 0

    for i, sample in enumerate(samples):
        text = sample["text"]
        domain = sample["domain"]

        # 随机决定噪音
        if random.random() < 0.25:
            noise_level = "clean"
            noise_type = None
        else:
            noise_level = random.choice(NOISE_LEVELS)
            noise_type = random.choice(NOISE_TYPES)

        mp3_file = output_dir / "audio" / f"s_{i:03d}.mp3"
        clean_wav = output_dir / "audio" / f"s_{i:03d}_clean.wav"
        final_wav = output_dir / "audio" / f"s_{i:03d}.wav"

        # Step 1: 合成
        ok = await synthesize_one(text, str(mp3_file))
        if not ok:
            fail_count += 1
            continue

        # Step 2: 转16k wav
        if not convert_to_16k_wav(str(mp3_file), str(clean_wav)):
            print(f"  ⚠️ 转换失败 sample {i}")
            os.unlink(str(mp3_file))
            fail_count += 1
            continue

        # Step 3: 叠加噪音
        if noise_level == "clean":
            subprocess.run(["mv", str(clean_wav), str(final_wav)])
        else:
            add_noise(str(clean_wav), str(final_wav), noise_type, noise_level)
            if os.path.exists(str(clean_wav)):
                os.unlink(str(clean_wav))

        # 清理 mp3
        os.unlink(str(mp3_file))

        manifest.append({
            "id": i,
            "text": text,
            "domain": domain,
            "noise_type": noise_type,
            "noise_level": noise_level,
            "audio_file": str(final_wav),
        })

        if (i + 1) % 20 == 0:
            print(f"  进度: {i+1}/{target_count} (失败: {fail_count})", flush=True)

    # 保存 manifest
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 生成完成: {len(manifest)} 个样本 (失败: {fail_count})")
    print(f"📋 Manifest: {manifest_path}")

    # 统计
    from collections import Counter
    domain_counts = Counter(m["domain"] for m in manifest)
    noise_counts = Counter(m["noise_level"] for m in manifest)
    print(f"   领域分布: {dict(domain_counts)}")
    print(f"   噪音分布: {dict(noise_counts)}")

    return manifest


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "/tmp/stt-eval/samples"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    asyncio.run(build_samples(output, count))
