import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional

_BASE = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
LAYOUT_PATH = os.path.join(_BASE, "layout.json")


@dataclass
class Source:
    title: str
    crop: list = field(default_factory=lambda: [0, 0, 0, 0])  # w==0 → 全体
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    interval: int = 1000
    parked_rect: Optional[list] = None  # 退避中なら元の [x,y,w,h]

    @staticmethod
    def from_dict(d):
        keys = Source.__dataclass_fields__.keys()
        return Source(**{k: v for k, v in d.items() if k in keys})


def save_layout(sources, always_on_top, geometry, path=LAYOUT_PATH):
    data = {
        "always_on_top": always_on_top,
        "geometry": geometry,
        "sources": [asdict(s) for s in sources],
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_layout(path=LAYOUT_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return ([Source.from_dict(s) for s in d.get("sources", [])],
                d.get("always_on_top", False), d.get("geometry"))
    except Exception:
        return [], False, None
