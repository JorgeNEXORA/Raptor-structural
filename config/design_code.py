import json
import os

def load_design_code(root_dir: str):
    path = os.path.join(root_dir, "config", "design_code.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
