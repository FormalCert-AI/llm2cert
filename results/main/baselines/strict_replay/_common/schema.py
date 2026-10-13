"""Define baseline replay result records."""
SCHEMA_VERSION = "baseline-native-strict.v1"


def strict_pass_from_queries(queries):
    return bool(queries) and all(q.get("status") == "unsat" for q in queries)


def failure_reason_from_queries(queries):
    if not queries:
        return "no_queries"
    statuses = [q.get("status") for q in queries]
    if any(s == "delta-sat" or s == "sat_or_delta_sat" for s in statuses):
        return "delta-sat"
    if any(s == "timeout" for s in statuses):
        return "timeout"
    if any(s == "unknown" for s in statuses):
        return "unknown"
    if any(s not in ("unsat",) for s in statuses):
        return "not_all_unsat"
    return None
