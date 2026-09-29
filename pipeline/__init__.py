"""Phase-0 event-based ALPR pipeline scaffold.

Additive only: nothing here is imported by the legacy runtime path
(``video_processor.py``, ``api.py``, ``alpr_engine.py``). The new pipeline
stays disabled until ``pipeline.flags`` explicitly opts a source in.

Layout (mirrors ALPR_ARCHITECTURE_DESIGN.md Part 1 / Appendix A):
  pipeline/config.py        PipelineConfig knobs (Appendix C)
  pipeline/flags.py         feature flags: OLD pipeline default, NEW opt-in
  pipeline/metrics.py       counters/gauges/EMA + snapshot() (Appendix E.1)
  pipeline/types.py         Box, Track, TrackUpdate, PlateRead, PlateObservation,
                            ConsensusCandidate, ConsensusResult, ScheduleDecision,
                            EmissionRequest, VehicleEvent
  pipeline/tracker.py       in-repo ByteTrack, camera-scoped (design §2.2 option B)
  pipeline/track_manager.py lifecycle state machine (design §2.4)
  pipeline/consensus.py     pure multi-frame voting (design Part 4)
  pipeline/event_builder.py event-key idempotency (design §2.5)
"""

__all__ = [
    "config",
    "flags",
    "metrics",
    "types",
    "tracker",
    "track_manager",
    "consensus",
    "event_builder",
]
