"""Matplotlib bar chart generator for expense summary PDFs.

Uses the non-interactive 'Agg' backend — safe in headless / server environments.
"""
from __future__ import annotations

import logging
import os
import tempfile

logger = logging.getLogger(__name__)

# Force non-interactive backend before any pyplot import
os.environ.setdefault("MPLBACKEND", "Agg")


def generate_expense_chart(category_totals: dict[str, float], month_label: str) -> str:
    """Draw a horizontal bar chart; return path to a temp PNG (caller must delete).

    Args:
        category_totals: {"food": 1200.0, "fuel": 800.0, ...}
        month_label:     e.g. "January 2024"
    """
    import matplotlib  # type: ignore[import]
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # type: ignore[import]

    if not category_totals:
        category_totals = {"(no data)": 0.0}

    # Sort by value descending for cleaner look
    sorted_items = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    labels = [item[0].capitalize() for item in sorted_items]
    values = [item[1] for item in sorted_items]

    # Colour palette
    palette = [
        "#1a237e", "#283593", "#3949ab", "#5c6bc0",
        "#7986cb", "#9fa8da", "#c5cae9", "#e8eaf6",
    ]
    bar_colors = [palette[i % len(palette)] for i in range(len(labels))]

    fig_height = max(3, len(labels) * 0.55 + 1.5)
    fig, ax = plt.subplots(figsize=(8, fig_height))

    bars = ax.barh(labels, values, color=bar_colors, edgecolor="white", linewidth=0.5)

    # Value labels on bars
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_width() + max(values) * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"₹{val:,.0f}",
            va="center",
            ha="left",
            fontsize=9,
            color="#1a237e",
        )

    ax.set_xlabel("Amount (₹)", fontsize=10)
    ax.set_title(f"Expenses by Category — {month_label}", fontsize=12, fontweight="bold", pad=12)
    ax.invert_yaxis()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlim(0, max(values) * 1.2 if max(values) > 0 else 1)

    plt.tight_layout()

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    plt.savefig(tmp.name, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    logger.info("Chart saved: %s", tmp.name)
    return tmp.name
