# tests/test_factory_runner_build.py
from factory import roles, runner


def test_build_argv_has_required_flags():
    role = roles.ROLES["engineer"]
    argv = runner.build_argv(role, claude_bin="/fake/claude")
    assert argv[0] == "/fake/claude"
    assert "-p" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--append-system-prompt") + 1] == role.system_prompt
    assert argv[argv.index("--max-budget-usd") + 1] == str(role.max_budget_usd)


def test_build_argv_allowedtools_is_last_and_variadic():
    role = roles.ROLES["engineer"]
    argv = runner.build_argv(role)
    i = argv.index("--allowedTools")
    assert tuple(argv[i + 1:]) == role.allowed_tools  # nothing after the tool list


def test_build_argv_no_positional_prompt():
    # prompt is delivered via stdin, so no role text should appear as a bare positional
    argv = runner.build_argv(roles.ROLES["reviewer"])
    assert "-p" in argv and argv.count("-p") == 1


def test_build_env_drops_secret_shaped_vars():
    src = {
        "PATH": "/usr/bin", "HOME": "/home/x",
        "OPENAI_API_KEY": "sk-secret", "MY_TOKEN": "t", "DB_PASSWORD": "p",
        "ANTHROPIC_API_KEY": "ak",  # explicit claude-auth — allowed through
    }
    env = runner.build_env(src)
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/x"
    assert "OPENAI_API_KEY" not in env
    assert "MY_TOKEN" not in env
    assert "DB_PASSWORD" not in env
    assert env.get("ANTHROPIC_API_KEY") == "ak"  # only the explicit auth var survives


def test_build_env_only_claude_auth_is_secret_shaped():
    import re
    src = {"PATH": "/usr/bin", "AWS_SECRET_ACCESS_KEY": "x", "ANTHROPIC_API_KEY": "ak"}
    env = runner.build_env(src)
    secretish = [k for k in env if re.search(r"KEY|SECRET|TOKEN|PASSWORD|DSN|CREDENTIAL", k, re.I)]
    assert secretish == ["ANTHROPIC_API_KEY"]
