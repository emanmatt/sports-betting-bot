"""Evidence extraction with explainable rules and optional LLM enrichment."""
from dataclasses import dataclass, asdict
import re

RULES = {"injury": ("out", "doubtful", "questionable", "injury", "inactive", "scratch"),
         "lineup": ("lineup", "starter", "starting", "rest", "minutes", "benched"),
         "weather": ("weather", "wind", "rain", "temperature"),
         "market": ("odds", "line moved", "spread", "total")}

@dataclass
class Evidence:
    text: str; classification: str; impact: float; reliability: float; entities: list[str]
    contradiction_key: str = ""
    def to_dict(self): return asdict(self)

def extract_evidence(text, verified=False, source_type="news"):
    normalized = (text or "").lower()
    matches = [kind for kind, words in RULES.items() if any(word in normalized for word in words)]
    classification = matches[0] if matches else "noise"
    reliability = 0.9 if source_type == "official" else (0.7 if verified or source_type == "news" else 0.35)
    impact = min(1.0, 0.35 * len(matches) + (0.25 if classification == "injury" else 0))
    entities = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", text or "")[:10]
    key = f"{classification}:{'|'.join(sorted(entities[:2]))}" if entities else classification
    return Evidence(text=text or "", classification=classification, impact=impact,
                    reliability=reliability, entities=entities, contradiction_key=key)

def contradiction_rate(evidence):
    keys = {}
    for item in evidence:
        if item.classification == "noise": continue
        keys.setdefault(item.contradiction_key, []).append(item.impact)
    return sum(1 for values in keys.values() if len(values) > 1) / max(1, len(keys))
