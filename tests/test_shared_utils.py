"""Tests for the shared utilities extracted from duplicated bot code:

- core.affiliate.utm_link / make_utm — the UTM link builder that was
  copy-pasted (as ``_utm``) into every affiliate/content bot.
- core.base_bot.BaseBot.slugify / timestamp — the filesystem-safe slug and
  timestamp idioms that were copy-pasted across ~60 bots.
"""
from core.affiliate import (
    AMAZON_TAG,
    BLOG_URL,
    DEFAULT_CAMPAIGN,
    STAN_STORE_URL,
    make_utm,
    utm_link,
)
from core.base_bot import BaseBot


def test_utm_link_default_base_and_campaign():
    assert utm_link("77_ai_tools_affiliate_bot", "coinbase") == (
        f"{STAN_STORE_URL}?utm_source=77_ai_tools_affiliate_bot"
        f"&utm_medium=content&utm_campaign={DEFAULT_CAMPAIGN}&utm_content=coinbase"
    )


def test_utm_link_custom_medium_base_campaign():
    assert utm_link("bot", "cta", medium="blog", campaign="camp_x", base=BLOG_URL) == (
        f"{BLOG_URL}?utm_source=bot&utm_medium=blog&utm_campaign=camp_x&utm_content=cta"
    )


def test_make_utm_matches_legacy_format():
    _utm = make_utm("89_affiliate_growth_hacker", campaign="affiliate_swap_2026_05_29")

    def legacy(content, medium="content", base=STAN_STORE_URL):
        return (
            f"{base}?utm_source=89_affiliate_growth_hacker&utm_medium={medium}"
            f"&utm_campaign=affiliate_swap_2026_05_29&utm_content={content}"
        )

    assert _utm("coinbase") == legacy("coinbase")
    assert _utm("cta", medium="blog", base=BLOG_URL) == legacy("cta", medium="blog", base=BLOG_URL)


def test_amazon_tag_default():
    assert AMAZON_TAG  # resolved from env or default, never empty


def test_slugify_matches_legacy_idiom():
    for text, n in [("Top 10 AI tools!", 40), ("a b/c*d", 25), ("émoji😀x", 30)]:
        legacy = "".join(c if c.isalnum() else "_" for c in text[:n])
        assert BaseBot.slugify(text, n) == legacy


def test_slugify_default_length_and_none_safe():
    assert BaseBot.slugify("x" * 100) == "x" * 40  # default max_len=40
    assert BaseBot.slugify(None) == ""


def test_timestamp_format():
    ts = BaseBot.timestamp()
    assert len(ts) == 15 and ts[8] == "_"
    assert ts.replace("_", "").isdigit()
