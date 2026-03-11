from typing import Dict, List, Union


def summarize_numbers(numbers: List[float]) -> Dict[str, Union[int, float]]:
    values = [float(x) for x in numbers]
    if not values:
        return {"count": 0, "sum": 0.0, "avg": 0.0, "max": 0.0, "min": 0.0}

    total = sum(values)
    return {
        "count": len(values),
        "sum": total,
        "avg": total / len(values),
        "max": max(values),
        "min": min(values),
    }
