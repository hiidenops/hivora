from pathlib import Path
from typing import Any

import pytest
import yaml

from hivora.core.errors import ValidationError
from hivora.templates import (
    AppContext,
    Catalog,
    FormValidationError,
    HostInfo,
    TemplateInvalidError,
    compile_template,
    validate_inputs,
)
from hivora.templates.catalog import parse_template
from hivora.templates.expressions import (
    TemplateExpressionError,
    parse_expression,
    render,
)

CTX: dict[str, Any] = {
    "form": {"name": "Léa", "port": 8211, "on": True, "empty": ""},
    "host": {"lan_ip": None},
}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{{ form.port }}", 8211),  # a lone expression keeps its type
        ("{{ form.on | upper }}", "TRUE"),
        ("Hi {{ form.name | lower }}!", "Hi léa!"),
        ('{{ host.lan_ip | default("localhost") }}', "localhost"),
        ("{{ form.empty | default(42) }}", 42),
        ("{{ form.name | quote }}", '"Léa"'),
        ("{{ secret.admin_password }}", "${HV_SECRET_ADMIN_PASSWORD:-}"),
        ("{{ form.missing }}", None),
    ],
)
def test_render(text: str, expected: Any) -> None:
    assert render(text, CTX) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "user.name",
        "form",
        "form.x | shell",
        "form.x | default",
        "secret.x | upper",
        "form.x | default(__import__('os'))",
        "form.x | default([1])",
    ],
)
def test_expression_rejects_anything_outside_the_grammar(bad: str) -> None:
    with pytest.raises(TemplateExpressionError):
        parse_expression(bad)


def test_render_escapes_user_values_for_compose() -> None:
    assert (
        render("x={{ form.v }}", {"form": {"v": "a$b"}}, escape=lambda s: s.replace("$", "$$"))
        == "x=a$$b"
    )


def minimal(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "apiVersion": "hivora/v1", "kind": "Template",
        "metadata": {"slug": "demo", "name": "Demo", "version": "1.0.0", "category": "services"},
        "requirements": {"arch": ["amd64", "arm64"]},
        "form": {"basic": [{"id": "pw", "label": "pw", "type": "secret"}]},
        "services": {"web": {"image": "demo", "tag": "1",
                             "env": {"PW": "{{ secret.pw }}"}}},
    }  # fmt: skip
    doc.update(overrides)
    return doc


@pytest.mark.parametrize(
    "overrides",
    [
        {"services": {"web": {"image": "x", "tag": "1", "env": {"A": "{{ form.nope }}"}}}},
        {"services": {"web": {"image": "x", "tag": "1", "env": {"A": "{{ form.pw }}"}}}},
        {"services": {"web": {"image": "x", "tag": "1", "depends_on": ["db"]}}},
        {"services": {"web": {"image": "x", "tag": "1", "privileged": True}}},  # unknown key
        {"services": {"web": {"image": "x", "tag": "1", "env": {"A": "{{ service.db.host }}"}}}},
    ],
)
def test_schema_rejects_invalid_templates(overrides: dict[str, Any]) -> None:
    with pytest.raises(TemplateInvalidError):
        parse_template(yaml.safe_dump(minimal(**overrides)), require_pinned=False)


def test_official_templates_must_be_pinned() -> None:
    with pytest.raises(TemplateInvalidError, match="digest"):
        parse_template(yaml.safe_dump(minimal()), require_pinned=True)


def test_repo_templates_are_valid(catalog: Catalog) -> None:
    assert {"minecraft", "vaultwarden"} <= {e.slug for e in catalog.entries()}


def test_form_validation_reports_every_field(catalog: Catalog) -> None:
    with pytest.raises(FormValidationError) as err:
        validate_inputs(
            catalog.get("minecraft").template,
            {"eula": False, "max_players": 500, "difficulty": "x", "bogus": 1},
            {},
        )
    assert err.value.details["fields"] == {
        "bogus": "unknown_field", "eula": "must_accept", "max_players": "out_of_range",
        "difficulty": "invalid_choice",
    }  # fmt: skip


def test_form_defaults_and_generated_secrets(catalog: Catalog) -> None:
    form = validate_inputs(
        catalog.get("minecraft").template, {"eula": True}, {"app": {"name": "Cube"}}
    )
    assert form.values["motd"] == "Serveur Cube"
    assert form.values["game_port"] == 25565
    assert len(form.secrets["rcon_password"]) == 24
    assert "rcon_password" not in form.values


def test_secret_with_quote_is_rejected(catalog: Catalog) -> None:
    with pytest.raises(FormValidationError):
        validate_inputs(
            catalog.get("minecraft").template, {"eula": True, "rcon_password": "it's"}, {}
        )


def test_compile_minecraft(catalog: Catalog) -> None:
    template = catalog.get("minecraft").template
    form = validate_inputs(template, {"eula": True, "motd": "Cost $5"}, {"app": {"name": "C"}})
    compiled = compile_template(
        template, AppContext(slug="cube", name="C", revision=3, zone="gaming"),
        HostInfo(public_ip="203.0.113.7", lan_ip="192.168.1.10"), form, Path("/srv/hivora"),
    )  # fmt: skip
    svc = compiled.compose["services"]["server"]
    assert compiled.compose["name"] == "cube"
    assert svc["environment"]["EULA"] == "TRUE"
    assert svc["environment"]["MOTD"] == "Cost $$5"
    assert svc["environment"]["RCON_PASSWORD"] == "${HV_SECRET_RCON_PASSWORD:-}"
    assert svc["ports"] == [{"target": 25565, "published": "25565", "protocol": "tcp"}]
    assert svc["expose"] == ["25575/tcp"]
    assert svc["volumes"] == [
        {"type": "bind", "source": "/srv/hivora/cube/data", "target": "/data"}
    ]
    assert svc["labels"] == {
        "io.hivora.app": "cube",
        "io.hivora.revision": "3",
        "io.hivora.zone": "gaming",
    }
    assert compiled.env == {"HV_SECRET_RCON_PASSWORD": form.secrets["rcon_password"]}
    assert form.secrets["rcon_password"] not in compiled.compose_yaml
    assert compiled.access == {"game": "203.0.113.7:25565"}
    lan_only = compile_template(
        template, AppContext(slug="cube", name="C", revision=1), HostInfo(lan_ip="192.168.1.10"),
        form, Path("/srv/hivora"),
    )  # fmt: skip
    assert lan_only.access == {"game": "192.168.1.10:25565"}
    unknown = compile_template(
        template, AppContext(slug="cube", name="C", revision=1), HostInfo(), form, Path("/srv")
    )
    assert unknown.access == {}
    assert yaml.safe_load(compiled.compose_yaml) == compiled.compose


def test_lan_exposure_binds_lan_ip_and_vpn_requires_interface(catalog: Catalog) -> None:
    vw = catalog.get("vaultwarden").template
    form = validate_inputs(vw, {}, {"host": {"lan_ip": "10.0.0.2"}})
    app = AppContext(slug="vw", name="vw", revision=1)
    compiled = compile_template(vw, app, HostInfo(lan_ip="10.0.0.2"), form, Path("/srv"))
    assert compiled.compose["services"]["server"]["ports"][0]["host_ip"] == "10.0.0.2"
    assert form.values["domain"] == "http://10.0.0.2:8080"

    vpn = vw.model_copy(deep=True)
    vpn.services["server"].ports[0].__dict__["exposure"] = "vpn"
    with pytest.raises(ValidationError):
        compile_template(vpn, app, HostInfo(), form, Path("/srv"))


def test_empty_env_values_are_not_set(catalog: Catalog) -> None:
    template = catalog.get("minecraft").template
    form = validate_inputs(template, {"eula": True}, {"app": {"name": "C"}})
    env = compile_template(template, AppContext(slug="c", name="C", revision=1), HostInfo(), form,
                           Path("/srv")).compose["services"]["server"]["environment"]  # fmt: skip
    assert "CUSTOM_SERVER_PROPERTIES" not in env and "SEED" not in env and "CF_SLUG" not in env
    assert env["TYPE"] == "VANILLA"
    assert "None" not in env.values()


def test_service_image_follows_the_host_architecture() -> None:
    doc = minimal(form={}, requirements={"arch": ["amd64", "arm64"]}, services={"web": {
        "image": "x86", "tag": "1", "env": {"MODE": "native", "KEEP": "yes"},
        "arch": {"arm64": {"image": "arm", "tag": "2", "env": {"MODE": "arm"}}},
    }})  # fmt: skip
    template = parse_template(yaml.safe_dump(doc), require_pinned=False)
    app, form = AppContext(slug="d", name="D", revision=1), validate_inputs(template, {}, {})

    def service(arch: str) -> dict[str, Any]:
        host = HostInfo(arch=arch)
        compose = compile_template(template, app, host, form, Path("/srv")).compose
        return dict(compose["services"]["web"])

    amd, arm = service("amd64"), service("arm64")
    assert amd["image"] == "x86:1" and amd["environment"] == {"MODE": "native", "KEEP": "yes"}
    assert arm["image"] == "arm:2" and arm["environment"] == {"MODE": "arm", "KEEP": "yes"}

    doc["requirements"] = {"arch": ["amd64"]}  # an ARM image for an unsupported arch
    with pytest.raises(TemplateInvalidError, match="unsupported arch"):
        parse_template(yaml.safe_dump(doc), require_pinned=False)
    with pytest.raises(TemplateInvalidError, match="digest"):
        parse_template(yaml.safe_dump(minimal(services={"web": {
            "image": "x", "tag": "1@sha256:" + "0" * 64,
            "arch": {"arm64": {"image": "y", "tag": "2"}},
        }})), require_pinned=True)  # fmt: skip


def test_docker_reported_arch_wins() -> None:
    from hivora.templates import catalog as cat

    try:
        cat.set_host_arch("aarch64")
        assert cat.host_arch() == "arm64"
        cat.set_host_arch("x86_64")
        assert cat.host_arch() == "amd64"
    finally:
        cat.set_host_arch("")


def test_every_repo_template_compiles_on_its_architectures(catalog: Catalog) -> None:
    """Defaults + the required answers only: what a first deploy looks like."""
    answers = {
        "host": "vpn.example.org",
        "eula": True,
        "password": "hunter2x",
        "gslt": "TOKEN",
        "cluster_token": "pds-g^x",
        "admin_password": "correct-horse-12",
    }
    for entry in catalog.entries():
        t = entry.template
        ids = {f.id for f in t.form.fields}
        form = validate_inputs(t, {k: v for k, v in answers.items() if k in ids},
                               {"app": {"name": "Test"}})  # fmt: skip
        app = AppContext(slug=t.metadata.slug, name="Test", revision=1)
        for arch in t.requirements.arch:
            host = HostInfo(lan_ip="192.168.1.10", arch=arch)
            compiled = compile_template(t, app, host, form, Path("/srv"))
            main = compiled.compose["services"][t.main_service]
            assert "@sha256:" in main["image"], (t.metadata.slug, arch)
            if t.game and t.game.players and t.game.players.a2s_port:  # query port published
                ports = {(p.container_port, p.protocol)
                         for s in compiled.services for p in s.ports}  # fmt: skip
                assert (t.game.players.a2s_port, "udp") in ports, t.metadata.slug


@pytest.mark.parametrize(
    ("version", "java"),
    [("1.12.2", "java8"), ("1.16.5", "java8"), ("1.17", "java17"), ("1.20.4", "java17"),
     ("1.20.5", "java21"), ("1.21.1", "java21"), ("26.1", "java25"), ("LATEST", "java25"),
     ("SNAPSHOT", "java25")],
)  # fmt: skip
def test_minecraft_version_picks_its_java(catalog: Catalog, version: str, java: str) -> None:
    t = catalog.get("minecraft").template
    form = validate_inputs(t, {"eula": True, "version": version}, {"app": {"name": "C"}})
    compiled = compile_template(t, AppContext(slug="c", name="C", revision=1), HostInfo(), form,
                                Path("/srv"))  # fmt: skip
    assert f"-{java}@sha256:" in compiled.compose["services"]["server"]["image"]


def test_files_become_compose_configs_with_secret_references() -> None:
    doc = minimal(form={"basic": [{"id": "tok", "label": "t", "type": "secret"},
                                  {"id": "name", "label": "n", "type": "string"}]},
                  services={"web": {"image": "x", "tag": "1", "files": [
                      {"target": "/data/cfg/token.txt", "content": "{{ secret.tok }}"},
                      {"target": "/data/cfg/name.txt", "content": "name={{ form.name }}"},
                  ]}})  # fmt: skip
    t = parse_template(yaml.safe_dump(doc), require_pinned=False)
    form = validate_inputs(t, {"tok": "s3cret", "name": "Cu$be"}, {})  # a typed $ is escaped
    compose = compile_template(t, AppContext(slug="d", name="D", revision=1), HostInfo(), form,
                               Path("/srv")).compose  # fmt: skip
    assert compose["configs"] == {"web-file-0": {"content": "${HV_SECRET_TOK:-}"},
                                  "web-file-1": {"content": "name=Cu$$be"}}  # fmt: skip
    first = {"source": "web-file-0", "target": "/data/cfg/token.txt"}
    assert compose["services"]["web"]["configs"][0] == first
    assert "s3cret" not in yaml.safe_dump(compose)
    with pytest.raises(TemplateInvalidError):
        bad = minimal(services={"web": {"image": "x", "tag": "1", "files": [
            {"target": "/data/../etc/passwd", "content": "x"}]}})  # fmt: skip
        parse_template(yaml.safe_dump(bad), require_pinned=False)
