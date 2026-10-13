"""Unpack the saved experiment records from the repository root."""
import argparse
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("groups", nargs="*", choices=["main", "rq1", "rq2", "rq3"])
args = parser.parse_args()
for group in args.groups or ["main", "rq1", "rq2", "rq3"]:
    directory = ROOT / "results" / group
    archive = directory / "records.tar.gz"
    with tarfile.open(archive) as records:
        for member in records.getmembers():
            path = Path(member.name)
            if not path.is_relative_to(Path("results") / group):
                raise ValueError(f"Record outside its experiment: {member.name}")
        records.extractall(ROOT, filter="data")
    print(f"Unpacked {group}")
