import json

from mini_nanobot.tools import AnalyzeParkingTool


def test_analyze_parking_tool_returns_low_risk_for_comfortable_slot():
    tool = AnalyzeParkingTool()
    result_raw = tool.run(
        scenario={
            "slot_width_m": 2.7,
            "slot_length_m": 5.4,
            "vehicle_width_m": 1.85,
            "vehicle_length_m": 4.7,
            "left_clearance_m": 0.4,
            "right_clearance_m": 0.45,
            "front_clearance_m": 0.5,
            "rear_clearance_m": 0.4,
            "speed_kmh": 2.0,
            "sensor_confidence": 0.95,
            "camera_occlusion_ratio": 0.05,
        }
    )

    result = json.loads(result_raw)
    assert result["fit_feasible"] is True
    assert result["risk_level"] in {"low", "medium"}
    assert result["key_metrics_m"]["min_clearance"] >= 0.3


def test_analyze_parking_tool_detects_high_risk_for_tight_slot():
    tool = AnalyzeParkingTool()
    result_raw = tool.run(
        scenario={
            "slot_width_m": 2.2,
            "slot_length_m": 4.95,
            "vehicle_width_m": 1.92,
            "vehicle_length_m": 4.8,
            "left_clearance_m": 0.11,
            "right_clearance_m": 0.1,
            "front_clearance_m": 0.18,
            "rear_clearance_m": 0.12,
            "speed_kmh": 4.5,
            "sensor_confidence": 0.62,
            "camera_occlusion_ratio": 0.5,
            "obstacles": [{"name": "pillar", "distance_m": 0.08}],
        }
    )

    result = json.loads(result_raw)
    assert result["risk_level"] == "high"
    assert result["risk_score_0_to_100"] >= 60
    assert result["key_metrics_m"]["min_clearance"] <= 0.1
