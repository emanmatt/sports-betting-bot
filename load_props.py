from data_ingestion.official.props_engine import PropsEngine
engine = PropsEngine()
edges = engine.analyze_props("MLB", search_web=False)
print(f"Found {len(edges)} prop edges")
for e in edges[:5]:
    print(f"{e.player_name} | {e.prop_label} | {e.edge_direction} {e.best_over_line} | Strength: {e.edge_strength}")