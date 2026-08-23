"""Pure pairwise prompt and Bradley-Terry helpers for the legacy facade."""

_PAIRWISE_PROMPT = (
    "=== \u4f60\u662f\u4e13\u4e1a\u7f51\u6587\u7f16\u8f91\uff0c\u8bf7\u5bf9\u6bd4\u4e24\u7ae0\u7684\u9605\u8bfb\u4f53\u9a8c ===\n\n"
    "\u5bf9\u6bd4\u7ef4\u5ea6: \u6574\u4f53\u723d\u611f\u3001\u60c5\u8282\u5f20\u529b\u3001\u9605\u8bfb\u6d41\u7545\u5ea6\u3002\n"
    "\u53ea\u8003\u8651\u9605\u8bfb\u4f53\u9a8c\uff0c\u4e0d\u8003\u8651\u5b57\u6570\u591a\u5c11\u3002\n\n"
    "\u8f93\u51fa\u683c\u5f0f (\u53ea\u8f93\u51fa\u4e00\u4e2a\u5b57\u6bcd):\n"
    "A \u2014 \u7b2cA\u7ae0\u66f4\u597d\n"
    "B \u2014 \u7b2cB\u7ae0\u66f4\u597d\n"
    "T \u2014 \u4e24\u7ae0\u5dee\u4e0d\u591a\n"
)


def _bradley_terry_estimate(pairwise_results):
    """Convert pairwise win/loss records to 0-10 Bradley-Terry scores."""
    wins = {}
    losses = {}
    all_chs = set()

    for ch_a, ch_b, verdict in pairwise_results:
        all_chs.add(ch_a)
        all_chs.add(ch_b)
        if verdict == "A":
            wins[ch_a] = wins.get(ch_a, 0) + 1
            losses[ch_b] = losses.get(ch_b, 0) + 1
        elif verdict == "B":
            wins[ch_b] = wins.get(ch_b, 0) + 1
            losses[ch_a] = losses.get(ch_a, 0) + 1

    bt_scores = {}
    for ch in all_chs:
        w = wins.get(ch, 0) + 1
        l = losses.get(ch, 0) + 1
        bt_scores[ch] = round(w / (w + l) * 10, 1)

    return bt_scores
