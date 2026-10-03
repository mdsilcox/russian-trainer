import pytest

from app.web import NAV_GROUPS, nav_active

ALL_LINKS = [href for g in NAV_GROUPS for href, _, _ in g["items"]]


def test_every_section_appears_once_and_groups_are_small():
    assert len(ALL_LINKS) == len(set(ALL_LINKS))
    assert all(1 <= len(g["items"]) <= 4 for g in NAV_GROUPS)
    assert {"/learn", "/review", "/plan", "/settings", "/shelf", "/scenarios", "/workshop", "/drills", "/grammar", "/dashboard", "/cards", "/import"} <= set(ALL_LINKS)


@pytest.mark.parametrize("path, key", [("/", "today"), ("/learn/u01/lesson", "learn"), ("/scenarios/c/4", "practice"),
                                       ("/plan", "progress"), ("/import/starter/review", "library"), ("/contents", "contents"),
                                       ("/review", "practice"), ("/nowhere", "")])
def test_nav_active_group(path, key):
    assert nav_active(path) == key


def test_menu_renders_groups_with_active_group(client):
    page = client.get("/review").text
    assert page.count("data-nav-group") == len(NAV_GROUPS)
    assert 'class="nav-top is-active"' in page and 'href="/contents"' in page
    assert '<a href="/review" aria-current="page"' in page


def test_contents_lists_every_section_with_hints(client):
    page = client.get("/contents").text
    for href in ALL_LINKS:
        assert f'href="{href}"' in page
    assert "Contents" in page and "in your deck" in page and "waiting today" in page


def test_every_menu_link_resolves(client):
    for href in ALL_LINKS + ["/", "/contents"]:
        assert client.get(href).status_code == 200, href
