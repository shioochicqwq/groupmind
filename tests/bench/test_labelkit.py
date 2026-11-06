from bench import labelkit


def test_build_inlines_kit_page_and_escaped_data(tmp_path):
    out = labelkit.build("k_round1", "t", {"pack": "x", "terms": [], "note": "</script><b>"}, tmp_path / "p.html")
    html = out.read_text(encoding="utf-8")
    assert "window.LabelKit = LK" in html and "LabelKit.queue" not in html.split("window.DATA")[0]
    assert "<\\/script><b>" in html and html.count("</script>") == 3
