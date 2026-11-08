from app.services.caption_emphasis_service import emphasis_terms, product_terms_from_title


def test_numbers_with_units_and_product_name_win_over_punch_words():
    product = product_terms_from_title("果知纯绿豆沙")
    assert product[0] == "果知纯绿豆沙"
    assert emphasis_terms("整箱十瓶两百四十五克。") == ["十瓶", "两百四十五克"]
    assert emphasis_terms("植物饮料常温保质十二个月。") == ["常温", "十二个月"]
    assert emphasis_terms("换成这杯果知纯绿豆沙。", product_terms=product) == ["果知纯绿豆沙"]
    assert emphasis_terms("绿豆熬制零脂肪。") == ["熬制", "零脂肪"]
    assert emphasis_terms("净含量200ml，每瓶0脂肪。") == ["200ml", "0脂肪"]


def test_at_most_one_punch_word_and_never_overlapping_or_invented():
    assert emphasis_terms("绵细密腻原香清润。") == ["清润"]
    assert emphasis_terms("下午犯困口干，奶茶甜腻又长胖。") == ["犯困"]
    assert emphasis_terms("先逆着毛发轻轻梳开。") == []
    assert emphasis_terms("   ") == []
    text = "十二个月十二个月"
    for term in emphasis_terms(text):
        assert term in text
    assert product_terms_from_title("  ") == []
    assert product_terms_from_title("金银花双柚汁｜整箱装") == ["金银花双柚汁｜整箱装", "金银花双柚汁", "整箱装"]
