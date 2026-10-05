"""Pick spliced answers to an exact count per model, with each base
answer used a limited number of times. Solved as a maximum flow, so a
selection is found whenever one exists."""

from collections import deque


def select(candidates, models, per_model, max_base_uses, rng):
    """candidates are dicts with model and base_id, at most one per base
    and donor. Returns the chosen candidates and how many each of models
    got, never more than per_model per model or max_base_uses per base.
    Candidates are tried in an order shuffled with rng, which spreads the
    choice and keeps it reproducible."""
    order = list(range(len(candidates)))
    rng.shuffle(order)
    graph, capacity = {}, {}

    def link(u, v, cap):
        graph.setdefault(u, []).append(v)
        graph.setdefault(v, []).append(u)
        capacity[u, v] = capacity.get((u, v), 0) + cap
        capacity.setdefault((v, u), 0)

    for model in models:
        link("source", ("model", model), per_model)
    for i in order:
        candidate = candidates[i]
        if candidate["model"] in models:
            link(("model", candidate["model"]), ("candidate", i), 1)
            link(("candidate", i), ("base", candidate["base_id"]), 1)
    for base in sorted({c["base_id"] for c in candidates}):
        link(("base", base), "sink", max_base_uses)

    # augmenting paths found breadth first, one unit of flow each
    while True:
        parent = {"source": None}
        queue = deque(["source"])
        while queue and "sink" not in parent:
            u = queue.popleft()
            for v in graph.get(u, []):
                if v not in parent and capacity[u, v] > 0:
                    parent[v] = u
                    queue.append(v)
        if "sink" not in parent:
            break
        v = "sink"
        while parent[v] is not None:
            u = parent[v]
            capacity[u, v] -= 1
            capacity[v, u] += 1
            v = u

    chosen = [
        candidates[i] for i in order
        if ("candidate", i) in graph and capacity[("candidate", i), ("base", candidates[i]["base_id"])] == 0
    ]
    counts = {model: sum(c["model"] == model for c in chosen) for model in models}
    return chosen, counts
