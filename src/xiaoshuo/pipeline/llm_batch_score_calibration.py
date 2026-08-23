"""Pure calibration and bootstrap helpers for the legacy facade."""


def build_calibration_plan(paired_int, paired_ret, wls_params=None):
    """Build the numeric calibration plan without file, row, or logger effects."""
    import statistics

    int_offsets = [human - llm for llm, human in paired_int]
    ret_offsets = [human - llm for llm, human in paired_ret]
    intensity_offset = round(statistics.median(int_offsets), 1)
    retention_offset = round(statistics.median(ret_offsets), 1)
    n_golden = len(paired_int)
    shrinkage = 0.6 if n_golden >= 20 else 0.4
    intensity_skip = abs(intensity_offset) < 0.5
    retention_skip = abs(retention_offset) < 0.5
    skipped = intensity_skip and retention_skip
    method = "smart_skip" if skipped else ("wls" if wls_params else "median_offset_shrinkage")
    return {
        "intensity_offset": intensity_offset,
        "retention_offset": retention_offset,
        "n_golden": n_golden,
        "shrinkage": shrinkage,
        "intensity_skip": intensity_skip,
        "retention_skip": retention_skip,
        "method": method,
        "skipped": skipped,
        "wls_params": wls_params,
    }


def apply_calibration_values(old_int, old_ret, plan):
    """Apply a pure calibration plan to two numeric values."""
    if plan["wls_params"] and not plan["skipped"]:
        new_int = round(max(1.0, min(10.0, plan["wls_params"]["intensity"]["intercept"] + plan["wls_params"]["intensity"]["slope"] * old_int)), 1)
        new_ret = round(max(1.0, min(10.0, plan["wls_params"]["retention"]["intercept"] + plan["wls_params"]["retention"]["slope"] * old_ret)), 1)
    else:
        new_int = round(max(1.0, min(10.0, old_int + plan["shrinkage"] * plan["intensity_offset"])), 1) if not plan["intensity_skip"] else old_int
        new_ret = round(max(1.0, min(10.0, old_ret + plan["shrinkage"] * plan["retention_offset"])), 1) if not plan["retention_skip"] else old_ret
    return new_int, new_ret


def bootstrap_rank_analysis(books, n_bootstrap=1000):
    """Return bootstrap ranking metrics while preserving legacy sampling semantics."""
    import random
    import statistics

    book_names = list(books.keys())
    boot_means = {name: [] for name in book_names}
    boot_ranks = {name: [] for name in book_names}

    random.seed(42)
    for _ in range(n_bootstrap):
        means_this_round = {}
        for name in book_names:
            scores = books[name]
            resampled = [random.choice(scores) for _ in range(len(scores))]
            means_this_round[name] = statistics.mean(resampled)

        sorted_books = sorted(means_this_round.items(), key=lambda x: -x[1])
        for rank, (name, _) in enumerate(sorted_books, 1):
            boot_ranks[name].append(rank)
            boot_means[name].append(means_this_round[name])

    results = []
    for name in book_names:
        means_sorted = sorted(boot_means[name])
        ranks_sorted = sorted(boot_ranks[name])
        mean_ci_low = means_sorted[int(0.025 * n_bootstrap)]
        mean_ci_high = means_sorted[int(0.975 * n_bootstrap)]
        rank_ci_low = ranks_sorted[int(0.025 * n_bootstrap)]
        rank_ci_high = ranks_sorted[int(0.975 * n_bootstrap)]
        rank_median = int(statistics.median(ranks_sorted))

        rank_range = rank_ci_high - rank_ci_low
        if rank_range <= 2:
            stability = "stable"
        elif rank_range <= 5:
            stability = "unstable"
        else:
            stability = "volatile"

        results.append({
            "book": name,
            "n_chapters": len(books[name]),
            "mean_intensity": round(statistics.mean(books[name]), 2),
            "mean_ci_95": [round(mean_ci_low, 2), round(mean_ci_high, 2)],
            "rank_median": rank_median,
            "rank_ci_95": [rank_ci_low, rank_ci_high],
            "stability": stability,
        })

    results.sort(key=lambda x: x["rank_median"])
    return results
