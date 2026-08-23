"""Pure reference-prompt helpers for the legacy LLM batch-score facade."""

_REF_RUBRIC_TEMPLATE = (
    "=== \u4f60\u662f\u4e13\u4e1a\u7f51\u6587\u7f16\u8f91\uff0c\u5bf9\u7ae0\u8282\u9605\u8bfb\u4f53\u9a8c\u72ec\u7acb\u8bc4\u5206 ===\n\n"
    "\u8bf7\u5bf9\u4e0b\u65b9\u7ae0\u8282\u8bc4\u5206\uff0c\u5927\u80c6\u4f7f\u7528\u5168\u91cf\u7a0b(1-10)\uff0c\u4e0d\u8981\u6324\u5728\u4e2d\u6bb5\u3002\n\n"
    "### \u6821\u51c6\u53c2\u8003\u6bb5\u843d (\u5df2\u77e5\u4eba\u5de5\u8bc4\u5206) ###\n"
    "\u4ee5\u4e0b\u6bb5\u843d\u6765\u81ea\u5df2\u6807\u6ce8\u7684\u672b\u4e16\u5c0f\u8bf4\u7ae0\u8282\uff0c\u4eba\u5de5\u8bc4\u5206\u5df2\u9a8c\u8bc1\u3002\n"
    "\u8bf7\u53c2\u7167\u8fd9\u4e9b\u6bb5\u843d\u7684\u8bc4\u5206\u57fa\u51c6\u6765\u6821\u51c6\u4f60\u7684\u8bc4\u5206\u5c3a\u5ea6\u3002\n\n"
    "{reference_section}\n\n"
    "### \u8bc4\u5206\u91cf\u89c4 (Rubric) ###\n"
    "1. \u723d\u70b9\u5f3a\u5ea6 (1-10): 1=\u5e73\u6de1\u94fa\u57ab 3=\u5c0f\u723d 5=\u660e\u663e\u723d\u611f 7=\u5f3a\u70c8\u9ad8\u5149 10=\u5dc5\u5cf0\u795e\u4f5c\n"
    "   [\u951a\u5b9a] \u666e\u901a\u8fc7\u6e21\u7ae0=3 | \u6807\u51c6\u6253\u8138\u6210\u529f=5 | \u7edd\u5883\u7ffb\u76d8=7 | \u5168\u4e66\u6700\u4f73\u9ad8\u6f6e=9-10\n"
    "2. \u51b2\u7a81\u7b49\u7ea7: none/low/medium/high\n"
    "3. \u60c5\u7eea\u6c1b\u56f4: \u723d\u5feb/\u7d27\u5f20/\u60b2\u58ee/\u60ac\u7591/\u65e5\u5e38/\u6e29\u60c5/\u538b\u6291\n"
    "4. \u8282\u594f: fast/medium/slow\n"
    "5. \u94a9\u5b50\u8d28\u91cf: none/weak/strong\n"
    "6. \u8bfb\u8005\u7559\u5b58\u529b (1-10): 1=\u53ef\u80fd\u5f03\u4e66 5=\u666e\u901a 7=\u60f3\u8ffd 10=\u71ac\u591c\u4e5f\u8981\u770b\n"
    "   [\u951a\u5b9a] \u5f00\u7bc7\u94fa\u57ab=4 | \u5c0f\u9ad8\u6f6e\u540e=6 | \u91cd\u5927\u53cd\u8f6c\u540e=8 | \u5168\u4e66\u9ad8\u6f6e=9-10\n\n"
    "### \u8f93\u51fa\u683c\u5f0f (\u5148\u5206\u6790\u518d\u8bc4\u5206) ###\n"
    "\u5148\u7528\u4e00\u53e5\u8bdd\uff08\u4e0d\u8d85\u8fc730\u5b57\uff09\u6982\u62ec\u672c\u7ae0\u6838\u5fc3\u770b\u70b9\uff0c\u7136\u540e\u53c2\u7167\u53c2\u8003\u6bb5\u843d\u8bc4\u4f30\u672c\u7ae0\u6c34\u5e73\uff0c\u6700\u540e\u8f93\u51fa\u8bc4\u5206JSON\u3002\n"
    "\u6ce8\u610f\uff1a\u5206\u6790\u5fc5\u987b\u7b80\u77ed\uff0c\u91cd\u70b9\u8f93\u51faJSON\u3002\n"
    "\u683c\u5f0f:\n"
    "\u5206\u6790: [\u4e00\u53e5\u8bdd\u6982\u62ec]\n"
    '{"intensity":5,"conflict":"medium","emotion":"\u65e5\u5e38","pace":"medium","hook":"weak","retention":5}'
)


def _build_reference_system_prompt(references):
    """Build system prompt with reference passages injected."""
    band_labels = {
        "low": "\u4f4e\u5206\u6bb5 (\u5e73\u6de1\u94fa\u57ab)",
        "medium_low": "\u4e2d\u4f4e\u5206\u6bb5 (\u6709\u51b2\u7a81\u4f46\u4e0d\u591f\u5f3a)",
        "medium_high": "\u4e2d\u9ad8\u5206\u6bb5 (\u660e\u786e\u723d\u611f)",
        "high": "\u9ad8\u5206\u6bb5 (\u5f3a\u70c8\u9ad8\u6f6e)",
    }

    ref_parts = []
    for i, ref in enumerate(references, 1):
        band_label = band_labels.get(ref["band"], ref["band"])
        ref_parts.append(
            f"[\u53c2\u8003{i} - {band_label} | \u4eba\u5de5\u8bc4\u5206: \u723d\u70b9{ref['human_intensity']:.1f}, \u7559\u5b58{ref['human_retention']:.1f}]\n"
            f"\u6765\u6e90: {ref['book']} \u7b2c{ref['ch_num']}\u7ae0\n"
            f"\u6807\u7b7e: {ref.get('tags', '\u65e0')}\n"
            f'"{ref["excerpt"]}"'
        )

    reference_section = "\n\n".join(ref_parts)
    return _REF_RUBRIC_TEMPLATE.replace("{reference_section}", reference_section)
