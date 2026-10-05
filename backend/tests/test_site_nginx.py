"""sites.nginx: the files Hivora writes for a host's sites, from the database rows."""

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from hivora.sites import nginx as n

MAIN = n.NginxSite(id=1, slug="main", root="", port=None, server_name=None, enabled=True)
BLOG = n.NginxSite(id=7, slug="blog", root="blog", port=8096, server_name="blog.example.com",
                   enabled=True)  # fmt: skip
WIKI = n.NginxSite(id=8, slug="wiki", root="wiki", port=8097, server_name=None, enabled=True)


def test_render_site_exactly() -> None:
    assert n.render_site(BLOG) == (
        '# Managed by Hivora: site "blog" (id 7). Regenerated from the database, do not edit.\n'
        "server {\n"
        "    listen 8096;\n"
        "    server_name blog.example.com;\n"
        "    root /usr/share/nginx/sites/blog;\n"
        "    index index.html index.htm;\n"
        "}\n"
    )
    assert "    server_name _;\n" in n.render_site(WIKI)  # no name: any host
    assert n.render_site(BLOG) == n.render_site(BLOG)  # deterministic
    with pytest.raises(n.InvalidSiteConfigError):
        n.render_site(MAIN)  # the main site is served by the fixed default.conf


@pytest.mark.parametrize(
    ("sites", "files"),
    [
        ([], []),  # an nginx whose sites Hivora does not manage
        ([MAIN], []),  # the main site on: nothing to include
        ([replace(MAIN, enabled=False)], ["main-off.conf"]),
        ([MAIN, BLOG], ["site-blog.conf"]),
        ([MAIN, replace(BLOG, enabled=False)], []),  # an added site off: no file
        (
            [WIKI, replace(MAIN, enabled=False), BLOG],
            ["main-off.conf", "site-blog.conf", "site-wiki.conf"],
        ),
    ],
)
def test_desired_files(sites: list[n.NginxSite], files: list[str]) -> None:
    got = n.desired_files(sites)
    assert list(got) == files  # sorted by name
    assert got == n.desired_files(list(reversed(sites)))  # the same whatever the order
    if "main-off.conf" in got:
        assert got["main-off.conf"] == "return 503;\n"
    for name, content in got.items():
        if name.startswith("site-"):
            assert content == n.render_site(next(s for s in sites if f"site-{s.slug}.conf" == name))
        assert n.MANAGED.match(name)


@pytest.mark.parametrize(
    "slug", ["Blog", "../x", "a b", "", "-blog", "b" * 64, "main", "blog;", "blog.conf", "été"]
)
def test_bad_slugs_are_refused(slug: str) -> None:
    with pytest.raises(n.InvalidSiteConfigError):
        n.check(replace(BLOG, slug=slug, root=slug))


@pytest.mark.parametrize("port", [0, 80, 65536, 70000, -1, None, True, "8096"])
def test_bad_ports_are_refused(port: object) -> None:
    with pytest.raises(n.InvalidSiteConfigError):
        n.check(replace(BLOG, port=port))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "name",
    ["a.com; include /etc/passwd", "a{", "a}", "$host", "a b", "a.com\nlisten 22",
     "-a.com", "a-.com", "*.a.com", "A.COM", "a..com", ".a.com", "a.com.", "a_b.com",
     "a" * 64 + ".com", ".".join(["a" * 50] * 5) + ".com", "", "\"a.com\"", "é.com"],
)  # fmt: skip
def test_bad_server_names_are_refused(name: str) -> None:
    with pytest.raises(n.InvalidSiteConfigError):
        n.check(replace(BLOG, server_name=name))


@pytest.mark.parametrize("name", ["blog.example.com", "localhost", "a-b.c-d.fr", "x1.y2"])
def test_good_server_names(name: str) -> None:
    n.check(replace(BLOG, server_name=name))


def test_rows_that_do_not_fit_are_refused() -> None:
    bad = [
        replace(BLOG, root="other"),  # a folder that is not the slug
        replace(MAIN, slug="principal"),  # the main site is "main"
        replace(MAIN, port=8095),  # the main site has no port of its own
        replace(MAIN, server_name="a.com"),  # nor a name (served by default.conf)
    ]
    for site in bad:
        with pytest.raises(n.InvalidSiteConfigError) as err:
            n.check(site)
        assert err.value.code == "invalid_site_config" and err.value.details == {"site": site.id}
    for sites in (
        [MAIN, replace(MAIN, id=2)],  # two main sites
        [BLOG, replace(WIKI, slug="blog", root="blog")],  # the same slug twice
        [BLOG, replace(WIKI, port=8096)],  # the same port twice
    ):
        with pytest.raises(n.InvalidSiteConfigError):
            n.desired_files(sites)
    with pytest.raises(n.InvalidSiteConfigError):  # one bad row: no file at all
        n.desired_files([MAIN, BLOG, replace(WIKI, server_name="a;b")])


@pytest.mark.parametrize(
    ("name", "managed"),
    [("main-off.conf", True), ("site-blog.conf", True), ("site-a-b.conf", True),
     ("default.conf", False), ("site-.conf", False), ("site-../x.conf", False),
     ("notes.txt", False), ("site-blog.conf.bak", False), ("Site-blog.conf", False),
     ("main-off.conf/x", False)],
)  # fmt: skip
def test_managed_file_names(name: str, managed: bool) -> None:
    assert bool(n.MANAGED.match(name)) is managed


def test_generator_does_no_io() -> None:
    """Pure: no filesystem, process or network module, no Docker."""
    tree = ast.parse(Path(n.__file__).read_text())
    imported = {a.name.split(".")[0] for x in ast.walk(tree) if isinstance(x, ast.Import)
                for a in x.names}  # fmt: skip
    imported |= {x.module for x in ast.walk(tree) if isinstance(x, ast.ImportFrom) and x.module}
    assert imported == {"re", "collections.abc", "dataclasses", "hivora.core.errors"}
