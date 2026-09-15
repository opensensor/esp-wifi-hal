#!/usr/bin/env python3
"""Parse bounded TX records; never copy unrelated serial lines into a report."""
import re

ENTRY = re.compile(
    r"stage=tx_probe cycle=(\d+) tag=(\d+) sequence=(\d+) phase=(Accepted|Queued|Picked|Finished) "
    r"accepted_us=(\d+) queued_us=(None|Some\(\d+\)) picked_us=(None|Some\(\d+\)) "
    r"finished_us=(None|Some\(\d+\)) result=(.+)"
)
SUMMARY = re.compile(
    r"stage=tx_probe_summary cycle=(\d+) retained=(\d+) capacity=(\d+) rejected=(\d+) "
    r"exhausted=(\d+) invalid=(\d+) scope_changes=(\d+) attempt_hooks=false"
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _optional(value):
    return None if value == "None" else int(value[5:-1])


def _result(text):
    if text == "None":
        return None
    success = re.fullmatch(r"Some\(Ok\((\d+)\)\)", text)
    if success:
        retries = int(success[1])
        _require(retries <= 255, "invalid retry count")
        return {"success": True, "retries": retries}
    error = re.fullmatch(
        r"Some\(Err\((BufferTooShort|DisabledKeySlot|OutOfBounds|InvalidEdcaParameters|"
        r"ChannelAccess\((?:Timeout|Collision)\)|"
        r"MacProtocol\((?:AckTimeout|CtsTimeout|InvalidKeyId|RtsChannelAccessError\((?:Timeout|Collision)\)|"
        r"Unknown \{ error: \d+, sub_error: \d+ \})\))\)\)", text
    )
    _require(error is not None, "unrecognized TX result")
    return {"success": False, "error": error[1], "retries": None}


def parse(serial):
    """Return strict numeric records, preserving incomplete and failed outcomes."""
    serial = re.sub(r"\x1b\[[0-9;]*m", "", serial)
    entries, summaries, tags = [], [], set()
    for line in serial.splitlines():
        if "stage=tx_probe" not in line:
            continue
        line = line[line.index("stage=tx_probe"):].strip()
        if line.startswith("stage=tx_probe_summary"):
            match = SUMMARY.fullmatch(line)
            _require(match is not None, "malformed probe summary")
            keys = ("cycle", "retained", "capacity", "rejected", "exhausted", "invalid", "scope_changes")
            row = dict(zip(keys, map(int, match.groups())))
            _require(row["retained"] <= row["capacity"], "retained count exceeds capacity")
            _require(row["cycle"] not in [s["cycle"] for s in summaries], "duplicate cycle summary")
            row["attempt_hooks"] = False
            summaries.append(row)
            continue
        match = ENTRY.fullmatch(line)
        _require(match is not None, "malformed probe entry")
        cycle, tag, sequence, phase, accepted, queued, picked, finished, result = match.groups()
        cycle, tag, sequence = int(cycle), int(tag), int(sequence)
        _require(cycle > 0 and tag > 0 and 1 <= sequence <= 20, "invalid packet identity")
        _require(tag not in tags, "duplicate submission tag")
        tags.add(tag)
        times = [int(accepted), _optional(queued), _optional(picked), _optional(finished)]
        n = ("Accepted", "Queued", "Picked", "Finished").index(phase) + 1
        _require(all(t is not None for t in times[:n]) and all(t is None for t in times[n:]),
                 "timestamps disagree with phase")
        _require(times[:n] == sorted(times[:n]), "timestamps went backwards")
        outcome = _result(result)
        _require((outcome is not None) == (phase == "Finished"), "result disagrees with phase")
        entries.append(dict(cycle=cycle, tag=tag, sequence=sequence, phase=phase,
                            accepted_us=times[0], queued_us=times[1], picked_us=times[2],
                            finished_us=times[3], result=outcome))
    # An absent final summary is evidence of interruption, not a passing batch.
    for summary in summaries:
        count = sum(e["cycle"] <= summary["cycle"] for e in entries)
        _require(count == summary["retained"], "summary differs from retained entry count")
    return {"entries": entries, "summaries": summaries,
            "cycles_without_summary": sorted({e["cycle"] for e in entries} - {s["cycle"] for s in summaries})}
