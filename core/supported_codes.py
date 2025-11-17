from __future__ import annotations

from dataclasses import dataclass
from typing import Set


@dataclass(frozen=True)
class SupportedCodeConfig:
    """Simple configuration for which G and M codes are considered supported
    by the target CNC controller.

    This is based on the Cirqoid / supported G-code documentation, but
    intentionally small for Feature 1. We can extend this table later as
    needed without changing parser behaviour.
    """

    g_codes: Set[str]
    m_codes: Set[str]

    def is_supported_g(self, code: str) -> bool:
        return code.upper() in self.g_codes

    def is_supported_m(self, code: str) -> bool:
        return code.upper() in self.m_codes


def default_supported_config() -> SupportedCodeConfig:
    # Core motion and basic modal codes
    g_codes = {
        "G0", "G00",
        "G1", "G01",
        "G2", "G02",
        "G3", "G03",
        "G4", "G04",
        "G20", "G21",
        "G28",
        "G53",
        "G54",
        "G90", "G91",
        "G92",
    }

    m_codes = {
        "M0", "M00",
        "M1", "M01",
        "M2", "M02",
        "M3", "M03",
        "M4", "M04",
        "M5", "M05",
        "M7", "M8", "M9",
    }

    return SupportedCodeConfig(g_codes=g_codes, m_codes=m_codes)
