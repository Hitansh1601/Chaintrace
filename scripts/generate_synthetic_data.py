"""Regenerate the bundled synthetic dataset (deterministic; seed is fixed)."""
from chaintrace.synthetic import SAMPLE_DIR, write_sample_files

if __name__ == "__main__":
    write_sample_files()
    print(f"Wrote synthetic dataset to {SAMPLE_DIR}")
