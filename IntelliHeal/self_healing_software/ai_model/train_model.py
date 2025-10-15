"""
Optional training script.
This is a utility to create a tiny JSON "model" mapping fault_type -> recommended spare_id.
It's intentionally simple to avoid heavy dependencies at runtime.
You can extend this to use scikit-learn and then export a lightweight model for inference.
"""

import json
import os

OUT_PATH = os.path.join(os.path.dirname(__file__), "model.json")

# Example training dataset (simulated) mapping
# In practice, collect real telemetry/fault -> best_spare examples.
EXAMPLE_MAPPING = {
    "missing_heartbeat": "spare_1",
    "error_count_exceeded": "spare_2",
    "stuck_at_1": "spare_3"
}

def train_and_export(mapping=None):
    mapping = mapping or EXAMPLE_MAPPING
    model = {"mapping": mapping, "meta": {"trained_on": "simulated_data_v1"}}
    with open(OUT_PATH, "w") as f:
        json.dump(model, f, indent=2)
    print("Exported lightweight model to", OUT_PATH)

if __name__ == "__main__":
    train_and_export()
