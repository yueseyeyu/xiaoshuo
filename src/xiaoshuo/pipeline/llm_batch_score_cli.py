"""Pure CLI argument and tier-sampling functions for batch scoring."""


def parse_cli_args(argv):
    """Parse the existing options-only CLI convention manually."""
    if not isinstance(argv, (list, tuple)):
        raise TypeError("argv must be a list or tuple")

    book_filter = None
    max_ch = 30
    genre = "末世"
    sc_samples = 1
    tier_boost = False
    for i, arg in enumerate(argv):
        if arg == "--book" and i < len(argv) - 1:
            book_filter = argv[i + 1]
        if arg == "--max" and i < len(argv) - 1:
            max_ch = int(argv[i + 1])
        if arg == "--genre" and i < len(argv) - 1:
            genre = argv[i + 1]
        if arg == "--sc" and i < len(argv) - 1:
            sc_samples = int(argv[i + 1])
        if arg == "--tier-boost":
            tier_boost = True
    return {
        "book_filter": book_filter,
        "max_ch": max_ch,
        "genre": genre,
        "sc_samples": sc_samples,
        "tier_boost": tier_boost,
    }


def select_book_sampling(tier_boost, txt_file, default_max_ch, default_sc, tier, tier_sampling):
    """Select per-book sampling values while preserving tier truthiness semantics."""
    if tier_boost and tier in tier_sampling:
        return tier_sampling[tier]["max_ch"], tier_sampling[tier]["sc_samples"]
    return default_max_ch, default_sc
