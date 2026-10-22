"""Approximate distinct counting helpers for Buckaroo profiling.

This module implements a small HyperLogLog-style counter inspired by the
Metanome DVHyperLogLogPlus family of algorithms.  It gives Buckaroo a cheap
way to estimate how many distinct values a column has without storing every
distinct value in memory.

The helper intentionally keeps an exact set for small inputs.  That gives exact
answers for normal sampled profiling, and automatically switches to
HyperLogLog when a column becomes too large for exact counting to be cheap.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Iterable


DEFAULT_HLL_PRECISION = 12
DEFAULT_EXACT_LIMIT = 10_000


@dataclass(frozen=True)
class DistinctCountProfile:
    """Cardinality evidence for one collection of values."""

    non_missing_count: int
    unique_count: int
    cardinality_ratio: float
    method: str
    is_estimated: bool
    precision: int


class HyperLogLogCounter:
    """Small deterministic HyperLogLog counter.

    Precision ``p`` controls the number of registers: ``2**p``.  A precision of
    12 uses 4096 registers and has an expected relative error around 1.6%.
    """

    def __init__(self, precision: int = DEFAULT_HLL_PRECISION) -> None:
        if precision < 4 or precision > 18:
            raise ValueError("precision must be between 4 and 18")
        self.precision = precision
        self.register_count = 1 << precision
        self.registers = [0] * self.register_count

    def add(self, value: Any) -> None:
        hashed = _hash64(value)
        index = hashed >> (64 - self.precision)
        remaining_bits = 64 - self.precision
        remaining = hashed & ((1 << remaining_bits) - 1)
        rank = _leading_zero_rank(remaining, remaining_bits)
        if rank > self.registers[index]:
            self.registers[index] = rank

    def estimate(self) -> float:
        m = self.register_count
        indicator = sum(2.0 ** -register for register in self.registers)
        raw_estimate = _alpha(m) * m * m / indicator

        empty_registers = self.registers.count(0)
        if raw_estimate <= 2.5 * m and empty_registers:
            return m * math.log(m / empty_registers)

        two_64 = float(1 << 64)
        if raw_estimate > two_64 / 30.0:
            return -two_64 * math.log(1.0 - raw_estimate / two_64)

        return raw_estimate


class DistinctCountAccumulator:
    """Streaming exact-then-HLL distinct counter."""

    def __init__(
        self,
        *,
        exact_limit: int = DEFAULT_EXACT_LIMIT,
        precision: int = DEFAULT_HLL_PRECISION,
        normalize_text: bool = True,
    ) -> None:
        self.exact_limit = exact_limit
        self.precision = precision
        self.normalize_text = normalize_text
        self.hll = HyperLogLogCounter(precision=precision)
        self.exact_values: set[str] | None = set()
        self.non_missing_count = 0

    def add(self, value: Any) -> None:
        normalized = _normalize_value(value, normalize_text=self.normalize_text)
        if normalized is None:
            return

        self.non_missing_count += 1
        self.hll.add(normalized)

        if self.exact_values is not None:
            self.exact_values.add(normalized)
            if len(self.exact_values) > self.exact_limit:
                self.exact_values = None

    def add_many(self, values: Iterable[Any]) -> None:
        for value in values:
            self.add(value)

    def profile(self) -> DistinctCountProfile:
        if self.exact_values is not None:
            unique_count = len(self.exact_values)
            method = "exact"
            is_estimated = False
        else:
            unique_count = max(0, int(round(self.hll.estimate())))
            method = "hyperloglog"
            is_estimated = True

        unique_count = min(unique_count, self.non_missing_count)
        ratio = float(unique_count / self.non_missing_count) if self.non_missing_count else 0.0
        return DistinctCountProfile(
            non_missing_count=self.non_missing_count,
            unique_count=unique_count,
            cardinality_ratio=ratio,
            method=method,
            is_estimated=is_estimated,
            precision=self.precision,
        )


def distinct_count_profile(
    values: Iterable[Any],
    *,
    exact_limit: int = DEFAULT_EXACT_LIMIT,
    precision: int = DEFAULT_HLL_PRECISION,
    normalize_text: bool = True,
) -> DistinctCountProfile:
    """Return exact or approximate distinct-count evidence."""

    accumulator = DistinctCountAccumulator(
        exact_limit=exact_limit,
        precision=precision,
        normalize_text=normalize_text,
    )
    accumulator.add_many(values)
    return accumulator.profile()


def _normalize_value(value: Any, *, normalize_text: bool) -> str | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass

    text = str(value).strip()
    if not text:
        return None
    return text.lower() if normalize_text else text


def _hash64(value: Any) -> int:
    data = str(value).encode("utf-8", errors="replace")
    digest = hashlib.blake2b(data, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


def _leading_zero_rank(value: int, bit_width: int) -> int:
    if value == 0:
        return bit_width + 1
    return bit_width - value.bit_length() + 1


def _alpha(register_count: int) -> float:
    if register_count == 16:
        return 0.673
    if register_count == 32:
        return 0.697
    if register_count == 64:
        return 0.709
    return 0.7213 / (1.0 + 1.079 / register_count)
