#!/usr/bin/env python3
"""
STT Accuracy Evaluation Runner
批量测试 STT 服务，计算 WER/CER，保留测试结果
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import httpx
import jiwer


@dataclass
class EvalSample:
    id: int
    audio_file: str
    ground_truth: str
    domain: str
    noise_type: Optional[str]
    noise_level: str


@dataclass
class EvalResult:
    sample_id: int
    domain: str
    noise_type: Optional[str]
    noise_level: str
    ground_truth: str
    raw_text: str
    corrected_text: str
    wer: float
    cer: float
    correct: bool
    error_type: str
    processing_seconds: float
    correction_seconds: float
    ollama_model: str


class STTEvaluator:
    def __init__(self, stt_url: str, timeout: int = 60):
        self.stt_url = stt_url
        self.timeout = timeout

    async def transcribe(self, audio_path: str) -> dict:
        """发送音频到 STT 服务"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            with open(audio_path, "rb") as f:
                files = {"file": (Path(audio_path).name, f, "audio/wav")}
                response = await client.post(
                    f"{self.stt_url}/v1/audio/transcriptions",
                    files=files,
                    data={"model": "SenseVoice"},
                )
            response.raise_for_status()
            return response.json()

    def compute_metrics(self, reference: str, hypothesis: str):
        """计算 WER 和 CER"""
        # 预处理：统一空白符
        ref_clean = " ".join(reference.split())
        hyp_clean = " ".join(hypothesis.split())

        try:
            wer = jiwer.wer(ref_clean, hyp_clean)
        except Exception:
            wer = 1.0

        try:
            cer = jiwer.cer(ref_clean, hyp_clean)
        except Exception:
            cer = 1.0

        return wer, cer

    def classify_error(self, reference: str, hypothesis: str) -> str:
        """归类错误类型"""
        ref_clean = " ".join(reference.split())
        hyp_clean = " ".join(hypothesis.split())

        if ref_clean == hyp_clean:
            return "correct"
        if not hyp_clean:
            return "empty"
        if len(hyp_clean) < len(ref_clean) * 0.3:
            return "severely_truncated"
        if all("\u4e00" <= c <= "\u9fff" for c in hyp_clean if c not in " \n"):
            return "punc_only"
        if all(c.isascii() or c == " " for c in hyp_clean):
            return "english_only"
        return "general_error"


async def run_batch(
    evaluator: STTEvaluator,
    samples: list[EvalSample],
    output_path: str,
    resume: bool = False,
) -> list[EvalResult]:
    """批量执行评测"""
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    results_file = output_path / "results.json"

    # 加载已有结果（断点续传）
    existing: dict[int, EvalResult] = {}
    if resume and results_file.exists():
        with open(results_file) as f:
            for r in json.load(f):
                existing[r["sample_id"]] = EvalResult(**r)
        print(f"📍 断点续传：已加载 {len(existing)} 个结果")

    results: list[EvalResult] = list(existing.values())

    for i, sample in enumerate(samples):
        if sample.id in existing:
            continue

        print(f"[{i+1}/{len(samples)}] Sample {sample.id:03d} ({sample.domain}, {sample.noise_level})...", end=" ")

        try:
            t0 = time.time()
            resp = await evaluator.transcribe(sample.audio_file)
            elapsed = time.time() - t0

            raw_text = resp.get("text", "")
            corrected_text = resp.get("text", "")  # API 已返回处理后文本
            wer, cer = evaluator.compute_metrics(sample.ground_truth, corrected_text)
            error_type = evaluator.classify_error(sample.ground_truth, corrected_text)

            result = EvalResult(
                sample_id=sample.id,
                domain=sample.domain,
                noise_type=sample.noise_type,
                noise_level=sample.noise_level,
                ground_truth=sample.ground_truth,
                raw_text=raw_text,
                corrected_text=corrected_text,
                wer=wer,
                cer=cer,
                correct=(wer == 0.0),
                error_type=error_type,
                processing_seconds=resp.get("processing_seconds", elapsed),
                correction_seconds=resp.get("correction_seconds", 0.0),
                ollama_model=resp.get("ollama_model", ""),
            )
            print(f"WER={wer:.3f} | {'✅' if wer == 0 else '❌'} | {corrected_text[:40]}")
        except Exception as e:
            print(f"❌ ERROR: {e}")
            result = EvalResult(
                sample_id=sample.id,
                domain=sample.domain,
                noise_type=sample.noise_type,
                noise_level=sample.noise_level,
                ground_truth=sample.ground_truth,
                raw_text="",
                corrected_text="",
                wer=1.0,
                cer=1.0,
                correct=False,
                error_type="api_error",
                processing_seconds=0,
                correction_seconds=0,
                ollama_model="",
            )

        results.append(result)

        # 每10个保存一次
        if (i + 1) % 10 == 0:
            with open(results_file, "w") as f:
                json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)
            print(f"💾 已保存 {len(results)} 个结果")

    # 最终保存
    with open(results_file, "w") as f:
        json.dump([asdict(r) for r in sorted(results, key=lambda x: x.sample_id)], f, ensure_ascii=False, indent=2)

    return results


def generate_report(results: list[EvalResult], output_path: str):
    """生成详细评测报告"""
    import statistics

    output_path = Path(output_path)
    total = len(results)
    correct = sum(1 for r in results if r.correct)
    wer_values = [r.wer for r in results]
    cer_values = [r.cer for r in results]
    avg_wer = statistics.mean(wer_values)
    avg_cer = statistics.mean(cer_values)
    median_wer = statistics.median(wer_values)

    # 按 domain 分组
    by_domain: dict[str, list[EvalResult]] = {}
    for r in results:
        by_domain.setdefault(r.domain, []).append(r)

    # 按噪音级别分组
    by_noise: dict[str, list[EvalResult]] = {}
    for r in results:
        key = r.noise_level if r.noise_type else "clean"
        by_noise.setdefault(key, []).append(r)

    # 按错误类型分组
    error_types: dict[str, int] = {}
    for r in results:
        error_types[r.error_type] = error_types.get(r.error_type, 0) + 1

    # 错误样本（WER > 0.5）
    bad_samples = sorted(
        [r for r in results if r.wer > 0.5],
        key=lambda x: x.wer,
        reverse=True,
    )

    report = []
    report.append("=" * 70)
    report.append("STT 准确率评测报告")
    report.append("=" * 70)
    report.append("")
    report.append("## 总体指标")
    report.append(f"  样本总数：{total}")
    report.append(f"  完全正确：{correct} ({correct/total*100:.1f}%)")
    report.append(f"  平均 WER：{avg_wer:.4f} ({avg_wer*100:.2f}%)")
    report.append(f"  平均 CER：{avg_cer:.4f} ({avg_cer*100:.2f}%)")
    report.append(f"  中位 WER：{median_wer:.4f}")
    report.append(f"  WER 标准差：{statistics.stdev(wer_values):.4f}")
    report.append("")
    report.append("## 按噪音级别")
    for noise_level in ["clean", "soft", "medium", "loud"]:
        group = by_noise.get(noise_level, [])
        if not group:
            continue
        avg_w = statistics.mean(r.wer for r in group)
        acc = sum(1 for r in group if r.correct) / len(group) * 100
        report.append(f"  {noise_level:10s}: n={len(group):3d}  WER={avg_w:.4f}  Acc={acc:.1f}%")
    report.append("")
    report.append("## 按领域")
    for domain in sorted(by_domain.keys()):
        group = by_domain[domain]
        avg_w = statistics.mean(r.wer for r in group)
        acc = sum(1 for r in group if r.correct) / len(group) * 100
        report.append(f"  {domain:10s}: n={len(group):3d}  WER={avg_w:.4f}  Acc={acc:.1f}%")
    report.append("")
    report.append("## 错误类型分布")
    for et, count in sorted(error_types.items(), key=lambda x: -x[1]):
        report.append(f"  {et:20s}: {count:3d} ({count/total*100:.1f}%)")
    report.append("")
    report.append("## WER > 0.5 的错误样本")
    for r in bad_samples[:10]:
        report.append(f"  [{r.domain}] WER={r.wer:.3f}")
        report.append(f"    GT:  {r.ground_truth}")
        report.append(f"    OUT: {r.corrected_text}")
        report.append("")

    report_text = "\n".join(report)
    print(report_text)

    # 保存 markdown 报告
    report_path = output_path / "report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n📄 报告已保存: {report_path}")

    # 保存 CSV 摘要
    csv_path = output_path / "summary.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("sample_id,domain,noise_level,wer,cer,correct,error_type,ground_truth,corrected_text\n")
        for r in sorted(results, key=lambda x: x.sample_id):
            f.write(f'{r.sample_id},{r.domain},{r.noise_level},{r.wer:.4f},{r.cer:.4f},{r.correct},{r.error_type},"{r.ground_truth}","{r.corrected_text}"\n')
    print(f"📊 CSV摘要已保存: {csv_path}")


async def main():
    parser = argparse.ArgumentParser(description="STT 准确率评测")
    parser.add_argument("--samples", required=True, help="manifest.json 路径")
    parser.add_argument("--stt-url", default="http://localhost:7700", help="STT 服务地址")
    parser.add_argument("--output", default="/tmp/stt-eval/results", help="结果输出目录")
    parser.add_argument("--resume", action="store_true", help="断点续传")
    args = parser.parse_args()

    # 加载 manifest
    with open(args.samples, encoding="utf-8") as f:
        manifest = json.load(f)

    samples = [
        EvalSample(
            id=m["id"],
            audio_file=m["audio_file"],
            ground_truth=m["text"],
            domain=m["domain"],
            noise_type=m.get("noise_type"),
            noise_level=m.get("noise_level", "clean"),
        )
        for m in manifest
    ]

    print(f"🎯 开始评测：{len(samples)} 个样本")
    print(f"   STT服务: {args.stt_url}")
    print(f"   输出目录: {args.output}")
    print("-" * 60)

    evaluator = STTEvaluator(args.stt_url)
    results = await run_batch(evaluator, samples, args.output, args.resume)

    print("-" * 60)
    generate_report(results, args.output)


if __name__ == "__main__":
    asyncio.run(main())
