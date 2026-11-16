"""matplotlib 图表渲染（PNG）。图表标签用英文以避免中文字体缺失问题。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def chart_by_category(by_type: list[dict[str, Any]], path: Path, title: str = "Losses by category") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    labels = [d["key"] for d in by_type]
    counts = [d["count"] for d in by_type]
    fig, ax = plt.subplots(figsize=(9, max(3, 0.4 * len(labels) + 1)))
    ax.barh(labels[::-1], counts[::-1], color="#b03a2e")
    ax.set_title(title)
    ax.set_xlabel("Count")
    for i, v in enumerate(counts[::-1]):
        ax.text(v, i, f" {v}", va="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def chart_by_status(by_status: list[dict[str, Any]], path: Path, title: str = "Losses by status") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    labels = [d["key"] for d in by_status]
    counts = [d["count"] for d in by_status]
    colors = {"Destroyed": "#b03a2e", "Damaged": "#e67e22", "Abandoned": "#7f8c8d", "Captured": "#2980b9"}
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(labels, counts, color=[colors.get(l, "#34495e") for l in labels])
    ax.set_title(title)
    ax.set_ylabel("Count")
    for i, v in enumerate(counts):
        ax.text(i, v, str(v), ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def chart_trend(daily: list[dict[str, Any]], path: Path, title: str = "Daily losses trend") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dates = [d["date"][5:] for d in daily]  # MM-DD
    counts = [d["count"] for d in daily]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(range(len(dates)), counts, marker="o", markersize=3, linewidth=1.2, color="#2c3e50")
    ax.set_title(title)
    ax.set_ylabel("Count")
    step = max(1, len(dates) // 12)
    ax.set_xticks(range(0, len(dates), step))
    ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)], rotation=45, fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
