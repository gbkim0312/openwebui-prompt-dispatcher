from prompt_dispatcher.application.services.markdown import normalize_markdown_ranges


def test_normalize_markdown_ranges_replaces_single_tilde_only() -> None:
    assert normalize_markdown_ranges("14~16시, 37~38°C, 8월 4일~6일") == "14–16시, 37–38°C, 8월 4일–6일"
    assert normalize_markdown_ranges("~~완료~~") == "~~완료~~"
