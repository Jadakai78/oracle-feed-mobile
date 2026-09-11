from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trend_code(value: Any) -> float:
    text = str(value or "unknown").lower()
    return 1.0 if text == "up" else -1.0 if text == "down" else 0.0


def _zone_code(value: Any) -> float:
    text = str(value or "neutral").lower()
    return -1.0 if text == "discount" else 1.0 if text == "premium" else 0.0


def _structure(record: Dict[str, Any]) -> Dict[str, Any]:
    structured = record.get("structure")
    if isinstance(structured, dict) and structured:
        return structured
    indicators = record.get("indicators") or {}
    return {key: record.get(key, indicators.get(key)) for key in (
        "d1_trend", "h4_trend", "zone", "eq_pct", "market_condition"
    )}


def _pressure(record: Dict[str, Any]) -> List[float]:
    flow = record.get("volume_flow") or {}
    if not bool(flow.get("ready")):
        return [0.0, 0.0, 0.0, 0.0]
    bias = str(record.get("bias") or "").upper()
    side = 1.0 if bias in {"LONG", "BUY"} else -1.0 if bias in {"SHORT", "SELL"} else 0.0
    delta = _number(flow.get("delta_norm"))
    cvd_slope = _number(flow.get("cvd_slope"))
    return [1.0, _number(flow.get("volume_norm")), delta * side, cvd_slope * side]


def _features_volatile(record: Dict[str, Any]) -> Optional[List[float]]:
    ind = record.get("indicators") or {}
    if not ind:
        return None
    struct = _structure(record)
    shadow = ((record.get("diagnostics") or {}).get("shadow_sentinel") or {})
    vol_state = 1.0 if str(shadow.get("volatility_state", "normal")).lower() == "explosive" else 0.0
    vol15 = str(shadow.get("volume_state_15m", "normal")).lower()
    vol15_value = 0.0 if vol15 == "thin" else 1.0 if vol15 == "high" else 0.5
    return [
        _number(ind.get("rsi"), 50.0) / 100.0,
        _number(ind.get("rvol"), 1.0) / 3.0,
        _number(ind.get("atr")),
        _number(ind.get("speed_pct")) / 5.0,
        _number(ind.get("maturity"), 0.5),
        _number(ind.get("st_direction")),
        1.0 if ind.get("st_flipped") else 0.0,
        _trend_code(struct.get("d1_trend")),
        _trend_code(struct.get("h4_trend")),
        _zone_code(struct.get("zone")),
        _number(struct.get("eq_pct"), 0.5),
        vol_state,
        vol15_value,
        *_pressure(record),
    ]


def _features_range(record: Dict[str, Any]) -> Optional[List[float]]:
    ind = record.get("indicators") or {}
    if not ind:
        return None
    struct = _structure(record)
    return [
        _number(ind.get("rsi"), 50.0) / 100.0,
        _number(ind.get("bb_pct"), 0.5),
        _number(ind.get("atr")),
        1.0 if ind.get("expansion_active") else 0.0,
        _trend_code(struct.get("d1_trend")),
        _trend_code(struct.get("h4_trend")),
        _zone_code(struct.get("zone")),
        _number(struct.get("eq_pct"), 0.5),
        *_pressure(record),
    ]


def _features_rts(record: Dict[str, Any]) -> Optional[List[float]]:
    ind = record.get("indicators") or {}
    if not ind:
        return None
    struct = _structure(record)
    shadow = ((record.get("diagnostics") or {}).get("shadow_sentinel") or {})
    vol_state = 1.0 if str(shadow.get("volatility_state", "normal")).lower() == "explosive" else 0.0
    vol15 = str(shadow.get("volume_state_15m", "normal")).lower()
    vol15_value = 0.0 if vol15 == "thin" else 1.0 if vol15 == "high" else 0.5
    condition = str(struct.get("market_condition", "unknown")).upper()
    regime = 1.0 if condition.startswith("TRENDING") else 0.0 if condition.startswith("RANGING") else -1.0
    return [
        _number(record.get("trap_score"), 0.5),
        _number(ind.get("rvol"), 1.0) / 3.0,
        _number(ind.get("atr")),
        _number(ind.get("sweep_size")),
        1.0 if ind.get("swept_high") else 0.0,
        1.0 if ind.get("swept_low") else 0.0,
        1.0 if ind.get("reclaim_high") else 0.0,
        1.0 if ind.get("reclaim_low") else 0.0,
        1.0 if ind.get("strong_wick") else 0.0,
        _zone_code(struct.get("zone")),
        _number(struct.get("eq_pct"), 0.5),
        regime,
        vol_state,
        vol15_value,
        *_pressure(record),
    ]


def _features_trend(record: Dict[str, Any]) -> Optional[List[float]]:
    ind = record.get("indicators") or {}
    struct = _structure(record)
    if not ind and not struct:
        return None
    return [
        _trend_code(struct.get("d1_trend")),
        _trend_code(struct.get("h4_trend")),
        _zone_code(struct.get("zone")),
        _number(struct.get("eq_pct"), 0.5),
        _number(ind.get("pullback_depth"), 0.5),
        _number(ind.get("rsi_h1"), 50.0) / 100.0,
        _number(ind.get("rvol_m15"), 1.0) / 3.0,
        _number(ind.get("speed_score_h1")),
        _number(ind.get("speed_score_m15")),
        *_pressure(record),
    ]


def _features_drive(record: Dict[str, Any]) -> Optional[List[float]]:
    """Feature vector for the Gimba Drive training-only specialist."""
    ind = record.get("indicators") or {}
    struct = _structure(record)
    if not ind and not struct:
        return None
    conditions = record.get("drive_conditions") or {}
    return [
        _trend_code(ind.get("d1_trend") or struct.get("d1_trend")),
        _trend_code(ind.get("h4_trend") or struct.get("h4_trend")),
        _number(ind.get("eq_pct"), 0.5),
        _number(ind.get("compression_ratio"), 1.0),
        _number(ind.get("rvol_m15"), 1.0) / 3.0,
        _number(ind.get("rsi_m15"), 50.0) / 100.0,
        _number(ind.get("speed_score")),
        _number(ind.get("atr_m15")),
        1.0 if conditions.get("htf_alignment") else 0.0,
        1.0 if conditions.get("pullback_location") else 0.0,
        1.0 if conditions.get("compression") else 0.0,
        1.0 if conditions.get("structure_break") else 0.0,
        1.0 if conditions.get("expansion") else 0.0,
        *_pressure(record),
    ]


FEATURE_FN = {
    "gimba_volatile": _features_volatile,
    "gimba_range": _features_range,
    "rts_liquidation": _features_rts,
    "gimba_trend": _features_trend,
    "gimba_drive": _features_drive,
}


def _label(record: Dict[str, Any]) -> Optional[int]:
    """Use only an explicit, evaluated market outcome; never prior conviction."""
    outcome = record.get("outcome") or {}
    label = outcome.get("label")
    if label in {1, "1", "positive", "win", "paid"}:
        return 1
    if label in {-1, "-1", "negative", "loss", "failed", "invalidated"}:
        return -1
    return None


def _normalize_columns(X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0] = 1.0
    return (X - mean) / std, mean, std


def _knn_adjust(query: np.ndarray, X_train: np.ndarray, y_train: np.ndarray, k: int = 7) -> float:
    k = min(k, len(X_train))
    if k == 0:
        return 0.0
    distances = np.linalg.norm(X_train - query, axis=1)
    idx = np.argsort(distances)[:k]
    weights = 1.0 / (distances[idx] + 1e-6)
    score = float(np.dot(weights, y_train[idx].astype(float)) / weights.sum())
    return round(score * 0.15, 4)


class KNNEngine:
    """One outcome-trained, specialist-specific KNN instance per bot."""

    def __init__(self, bot_name: str, log_dir: Path, min_samples: int = 30):
        if bot_name not in FEATURE_FN:
            raise ValueError(f"Unknown bot: {bot_name}")
        self.bot_name = bot_name
        self.log_file = log_dir / f"{bot_name}.jsonl"
        self.min_samples = min_samples
        self._feat_fn = FEATURE_FN[bot_name]
        self._X: Optional[np.ndarray] = None
        self._y: Optional[np.ndarray] = None
        self._mean: Optional[np.ndarray] = None
        self._std: Optional[np.ndarray] = None
        self._n_loaded = 0

    def _load(self) -> bool:
        if not self.log_file.exists():
            self._n_loaded = 0
            return False
        feature_rows: List[List[float]] = []
        labels: List[int] = []
        seen = set()
        with self.log_file.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = record.get("event_key") or "|".join(str(record.get(x, "")) for x in ("pair", "bot", "ts", "setup_type"))
                if key in seen:
                    continue
                seen.add(key)
                label = _label(record)
                features = self._feat_fn(record)
                if label is None or features is None:
                    continue
                feature_rows.append(features)
                labels.append(label)
        self._n_loaded = len(feature_rows)
        if self._n_loaded < self.min_samples:
            return False
        X_norm, self._mean, self._std = _normalize_columns(np.array(feature_rows, dtype=float))
        self._X = X_norm
        self._y = np.array(labels, dtype=float)
        return True

    def adjust(self, signal: Dict[str, Any]) -> Tuple[float, int]:
        if not self._load():
            return 0.0, self._n_loaded
        record = {
            "pair": signal.get("pair"),
            "bias": signal.get("bias"),
            "trap_score": signal.get("trap_score"),
            "indicators": signal.get("indicators") or {},
            "structure": signal.get("structure") or {},
            "diagnostics": signal.get("diagnostics") or {},
            "volume_flow": signal.get("volume_flow") or {},
        }
        features = self._feat_fn(record)
        if features is None or self._mean is None or self._std is None or self._X is None or self._y is None:
            return 0.0, self._n_loaded
        query = (np.array(features, dtype=float) - self._mean) / self._std
        return _knn_adjust(query, self._X, self._y), self._n_loaded
