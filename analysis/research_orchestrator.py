"""Multi-agent research workflow with a durable evidence audit trail.

Agents are deliberately narrow: source collection, evidence extraction, market
analysis and skeptical synthesis. This avoids an LLM turning unverified social
posts into facts. An optional Anthropic synthesis is only used when configured.
"""
from datetime import datetime, timedelta
from database.models import get_session, NewsArticle, SocialPost, ResearchEvidence
from analysis.evidence import extract_evidence, contradiction_rate

class ResearchOrchestrator:
    def collect(self, sport, hours=12):
        db = get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            records = []
            for item in db.query(NewsArticle).filter(NewsArticle.sport == sport, NewsArticle.published_at >= cutoff).all():
                records.append(("news", item.source, item.url, item.content or item.title, False, item.published_at))
            for item in db.query(SocialPost).filter(SocialPost.sport == sport, SocialPost.published_at >= cutoff).all():
                records.append((item.platform, item.source_name, item.url, item.content, bool(item.is_verified_source), item.published_at))
            return records
        finally: db.close()

    def run(self, sport, hours=12):
        records = self.collect(sport, hours)
        evidence = []
        db = get_session()
        try:
            for source_type, source_name, url, text, verified, published_at in records:
                parsed = extract_evidence(text, verified, source_type)
                evidence.append(parsed)
                if url and not db.query(ResearchEvidence).filter_by(source_url=url).first():
                    db.add(ResearchEvidence(sport=sport, source_type=source_type, source_name=source_name,
                           source_url=url, text=parsed.text[:10000], classification=parsed.classification,
                           entities=parsed.entities, reliability=parsed.reliability, impact=parsed.impact,
                           contradiction_key=parsed.contradiction_key, published_at=published_at))
            db.commit()
        finally: db.close()
        high = [e for e in evidence if e.impact * e.reliability >= .3]
        return {"sport": sport, "evidence_count": len(evidence), "actionable_count": len(high),
                "contradiction_rate": round(contradiction_rate(evidence), 3),
                "findings": [e.to_dict() for e in high[:15]],
                "disclaimer": "Research signals, not betting advice. Verify official injury and lineup sources."}
