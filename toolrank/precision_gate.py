"""Precision-side gate for category ownership candidates."""

from __future__ import annotations

from toolrank.schemas_v2 import Step1EvidencePacket


def matched_source_ids(packet: Step1EvidencePacket) -> set[str]:
    ids = {neighbor.paper_id for neighbor in packet.scene_pool.neighbors if neighbor.paper_id}
    for neighbor in packet.scene_pool.neighbors:
        ids.update(neighbor.provenance_refs)
    return ids


def top_scene_source_ids(packet: Step1EvidencePacket) -> list[str]:
    if not packet.scene_pool.neighbors:
        return []
    top = packet.scene_pool.neighbors[0]
    ids: list[str] = []
    if top.paper_id:
        ids.append(top.paper_id)
    ids.extend(top.provenance_refs)
    return list(dict.fromkeys(ids))


def candidate_passes_precision_gate(packet: Step1EvidencePacket, tool: str) -> bool:
    """No absolute precision gate. Precision now enters the decision relatively — via
    scene_scoring's precision rank inside S_scene — and via category-specific
    fp_precision_risk passages weighed by the LLM. Kept as a pass-through so existing
    call sites stay valid without a fixed 0.15 floor."""
    _ = (packet, tool)
    return True
