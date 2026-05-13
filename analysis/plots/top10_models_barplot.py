#!/usr/bin/env python3
"""Generate a horizontal bar plot of the top 10 models by speedup ratio."""

import io
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from PIL import Image

# Try to import cairosvg for SVG support
try:
    import cairosvg

    HAS_CAIROSVG = True
except (ImportError, OSError):
    HAS_CAIROSVG = False


# Color mapping for each organization/model
ORG_COLORS = {
    "OpenAI": "#10A37F",
    "Anthropic": "#D97757",
    "Google": "#4285F4",
    "Alibaba Qwen": "#6366F1",  # Purple like their logo
    "DeepSeek": "#4D6BFE",
    "Moonshot AI": "#6366F1",
    "Cursor": "#000000",
    "Z.ai": "#00D4AA",
    "SWE-fficiency": "#7C3AED",
    "Human Expert": "#555555",  # Grey
}


def load_image(logo_path: Path, size: int = 30):
    """Load an image (PNG, JPEG, or SVG) and return an OffsetImage."""
    if not logo_path.exists():
        return None

    try:
        if logo_path.suffix.lower() == ".svg":
            if not HAS_CAIROSVG:
                return None
            png_data = cairosvg.svg2png(
                url=str(logo_path), output_width=size * 4, output_height=size * 4
            )
            img = Image.open(io.BytesIO(png_data))
            img_array = np.array(img)
        else:
            img = Image.open(logo_path)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            img_array = np.array(img)

        max_dim = max(img_array.shape[:2])
        zoom = size / max_dim
        return OffsetImage(img_array, zoom=zoom)
    except Exception:
        return None


def main():
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent
    leaderboard_path = repo_root / "docs" / "assets" / "leaderboard.json"
    docs_assets = repo_root / "docs"
    output_path = repo_root / "docs" / "assets" / "figures" / "top10_models_barplot.png"

    with open(leaderboard_path, encoding="utf-8") as f:
        data = json.load(f)

    # Sort by speedup_ratio (descending) and take top 10
    sorted_data = sorted(data, key=lambda x: x["speedup_ratio"], reverse=True)[:10]
    sorted_data = sorted_data[::-1]  # Reverse for plot (highest at top)

    systems = [d["system"] for d in sorted_data]
    speedups = [d["speedup_ratio"] for d in sorted_data]
    colors = [ORG_COLORS.get(d["model"]["name"], "#888888") for d in sorted_data]
    logo_paths = [docs_assets / d["model"]["logo"] for d in sorted_data]

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 6))

    y_pos = np.arange(len(systems))
    bars = ax.barh(y_pos, speedups, color=colors, height=0.6)

    # Configure axes
    ax.set_yticks(y_pos)
    ax.set_yticklabels(systems, fontsize=9)
    ax.set_xlabel("Speedup Ratio", fontsize=11)
    ax.tick_params(axis="y", pad=26)  # Add padding for logos

    # Center title over entire figure
    fig.suptitle("Top Models by Speedup Ratio", fontsize=15, fontweight="bold", x=0.5)

    # Value labels
    for idx, (bar_obj, speedup) in enumerate(zip(bars, speedups)):
        # Human Expert (last bar, idx 9) gets white text inside the bar
        if idx == len(bars) - 1:
            ax.text(
                bar_obj.get_width() - 0.02,
                bar_obj.get_y() + bar_obj.get_height() / 2,
                f"{speedup:.3f}x",
                va="center",
                ha="right",
                fontsize=9,
                color="white",
                fontweight="bold",
            )
        else:
            ax.text(
                bar_obj.get_width() + 0.01,
                bar_obj.get_y() + bar_obj.get_height() / 2,
                f"{speedup:.3f}x",
                va="center",
                ha="left",
                fontsize=9,
            )

    ax.xaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(speedups) * 1.02)

    # Add logos between labels and bars
    plt.subplots_adjust(left=0.38, top=0.92)

    for i, logo_path in enumerate(logo_paths):
        img = load_image(logo_path, size=15)
        if img is not None:
            # Position logo between label and bar
            ab = AnnotationBbox(
                img,
                (-0.035, i),
                xycoords=("axes fraction", "data"),
                frameon=False,
                box_alignment=(0.5, 0.5),
            )
            ax.add_artist(ab)

    plt.savefig(
        output_path, dpi=300, bbox_inches="tight", pad_inches=0.5, facecolor="white"
    )
    print(f"Plot saved to: {output_path}")


if __name__ == "__main__":
    main()
