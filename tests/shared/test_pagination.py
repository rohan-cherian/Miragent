"""
tests/shared/test_pagination.py — W1-SRC-04 shared emulator pagination

Three vendor styles must stay distinct:
  Zendesk — opaque after_cursor
  Jira    — startAt / maxResults / total
  Entra   — $skiptoken / @odata.nextLink
"""

from __future__ import annotations

import pytest

from scout.shared.pagination import (
    decode_odata_skiptoken,
    decode_zendesk_cursor,
    encode_odata_skiptoken,
    encode_zendesk_cursor,
    paginate_entra,
    paginate_jira,
    paginate_zendesk,
    parse_entra_skiptoken_from_url,
    slice_items,
)


ITEMS = [{"id": i} for i in range(1, 26)]  # 25 items


class TestZendeskCursorPagination:
    def test_first_page_has_opaque_cursor(self):
        page = paginate_zendesk(ITEMS, per_page=10, resource_key="tickets")
        assert len(page["tickets"]) == 10
        assert page["tickets"][0]["id"] == 1
        assert page["meta"]["has_more"] is True
        cursor = page["meta"]["after_cursor"]
        assert cursor  # opaque, not a bare integer string that equals offset
        assert cursor != "10"
        assert "page[after]=" in page["links"]["next"]

    def test_follow_cursor_to_second_page(self):
        first = paginate_zendesk(ITEMS, per_page=10)
        cursor = first["meta"]["after_cursor"]
        second = paginate_zendesk(ITEMS, after_cursor=cursor, per_page=10)
        assert [x["id"] for x in second["tickets"]] == list(range(11, 21))

    def test_last_page_has_no_more(self):
        first = paginate_zendesk(ITEMS, per_page=10)
        second = paginate_zendesk(
            ITEMS, after_cursor=first["meta"]["after_cursor"], per_page=10
        )
        third = paginate_zendesk(
            ITEMS, after_cursor=second["meta"]["after_cursor"], per_page=10
        )
        assert len(third["tickets"]) == 5
        assert third["meta"]["has_more"] is False
        assert "after_cursor" not in third["meta"]
        assert third["links"]["next"] is None

    def test_cursor_roundtrip(self):
        encoded = encode_zendesk_cursor(42)
        assert decode_zendesk_cursor(encoded) == 42

    def test_invalid_cursor_raises(self):
        with pytest.raises(ValueError):
            decode_zendesk_cursor("!!!not-a-cursor!!!")


class TestJiraOffsetPagination:
    def test_first_page_shape(self):
        page = paginate_jira(ITEMS, start_at=0, max_results=10)
        assert page["startAt"] == 0
        assert page["maxResults"] == 10
        assert page["total"] == 25
        assert len(page["issues"]) == 10

    def test_second_page(self):
        page = paginate_jira(ITEMS, start_at=10, max_results=10)
        assert [x["id"] for x in page["issues"]] == list(range(11, 21))
        assert page["total"] == 25

    def test_past_end_empty(self):
        page = paginate_jira(ITEMS, start_at=25, max_results=10)
        assert page["issues"] == []
        assert page["total"] == 25

    def test_no_cursor_fields(self):
        page = paginate_jira(ITEMS, start_at=0, max_results=5)
        assert "meta" not in page
        assert "@odata.nextLink" not in page
        assert "after_cursor" not in page


class TestEntraODataPagination:
    def test_first_page_has_next_link_with_skiptoken(self):
        page = paginate_entra(ITEMS, top=10)
        assert len(page["value"]) == 10
        assert "@odata.context" in page
        next_link = page["@odata.nextLink"]
        assert "$skiptoken=" in next_link
        assert "$top=10" in next_link

    def test_follow_next_link(self):
        first = paginate_entra(ITEMS, top=10)
        token = parse_entra_skiptoken_from_url(first["@odata.nextLink"])
        assert token is not None
        second = paginate_entra(ITEMS, skiptoken=token, top=10)
        assert [x["id"] for x in second["value"]] == list(range(11, 21))

    def test_last_page_omits_next_link(self):
        first = paginate_entra(ITEMS, top=10)
        token1 = parse_entra_skiptoken_from_url(first["@odata.nextLink"])
        second = paginate_entra(ITEMS, skiptoken=token1, top=10)
        token2 = parse_entra_skiptoken_from_url(second["@odata.nextLink"])
        third = paginate_entra(ITEMS, skiptoken=token2, top=10)
        assert len(third["value"]) == 5
        assert "@odata.nextLink" not in third

    def test_skiptoken_roundtrip(self):
        assert decode_odata_skiptoken(encode_odata_skiptoken(7)) == 7


class TestStylesAreDistinct:
    def test_three_shapes_differ(self):
        zd = paginate_zendesk(ITEMS, per_page=5)
        jira = paginate_jira(ITEMS, max_results=5)
        entra = paginate_entra(ITEMS, top=5)

        assert "meta" in zd and "after_cursor" in zd["meta"]
        assert "startAt" in jira and "maxResults" in jira and "total" in jira
        assert "value" in entra and "@odata.nextLink" in entra

        assert "startAt" not in zd
        assert "meta" not in jira
        assert "after_cursor" not in entra.get("value", {})


class TestSliceAndPartial:
    def test_force_partial_keeps_has_more(self):
        page = slice_items(ITEMS, offset=0, page_size=10, force_partial=True)
        assert len(page.items) == 5
        assert page.has_more is True
        assert page.is_partial is True

    def test_zendesk_partial_page(self):
        page = paginate_zendesk(ITEMS, per_page=10, force_partial=True)
        assert len(page["tickets"]) == 5
        assert page["meta"]["has_more"] is True
        assert "after_cursor" in page["meta"]
