from pathlib import Path
from subprocess import CalledProcessError
from types import ModuleType, SimpleNamespace

import pytest

from hermes_cli import config as hermes_config
from hermes_cli import main as hermes_main


def test_stash_local_changes_if_needed_returns_none_when_tree_clean(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[-2:] == ["status", "--porcelain"]:
            return SimpleNamespace(stdout="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    stash_ref = hermes_main._stash_local_changes_if_needed(["git"], tmp_path)

    assert stash_ref is None
    assert [cmd[-2:] for cmd, _ in calls] == [["status", "--porcelain"]]


def test_stash_local_changes_if_needed_returns_specific_stash_commit(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[-2:] == ["status", "--porcelain"]:
            return SimpleNamespace(stdout=" M hermes_cli/main.py\n?? notes.txt\n", returncode=0)
        if cmd[-2:] == ["ls-files", "--unmerged"]:
            return SimpleNamespace(stdout="", returncode=0)
        if cmd[1:4] == ["stash", "push", "--include-untracked"]:
            return SimpleNamespace(stdout="Saved working directory\n", returncode=0)
        if cmd[-3:] == ["rev-parse", "--verify", "refs/stash"]:
            return SimpleNamespace(stdout="abc123\n", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    stash_ref = hermes_main._stash_local_changes_if_needed(["git"], tmp_path)

    assert stash_ref == "abc123"
    assert calls[1][0][-2:] == ["ls-files", "--unmerged"]
    assert calls[2][0][1:4] == ["stash", "push", "--include-untracked"]
    assert calls[3][0][-3:] == ["rev-parse", "--verify", "refs/stash"]


def test_resolve_stash_selector_returns_matching_entry(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        assert cmd == ["git", "stash", "list", "--format=%gd %H"]
        return SimpleNamespace(
            stdout="stash@{0} def456\nstash@{1} abc123\n",
            returncode=0,
        )

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    assert hermes_main._resolve_stash_selector(["git"], tmp_path, "abc123") == "stash@{1}"



def test_restore_stashed_changes_prompts_before_applying(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="applied\n", stderr="", returncode=0)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "list"]:
            return SimpleNamespace(stdout="stash@{1} abc123\n", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "drop"]:
            return SimpleNamespace(stdout="dropped\n", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda: "")

    restored = hermes_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=True)

    assert restored is True
    assert calls[0][0] == ["git", "stash", "apply", "abc123"]
    assert calls[1][0] == ["git", "diff", "--name-only", "--diff-filter=U"]
    assert calls[2][0] == ["git", "stash", "list", "--format=%gd %H"]
    assert calls[3][0] == ["git", "stash", "drop", "stash@{1}"]
    out = capsys.readouterr().out
    assert "Restore local changes now? [Y/n]" in out
    assert "restored on top of the updated codebase" in out
    assert "git diff" in out
    assert "git status" in out


def test_restore_stashed_changes_can_skip_restore_and_keep_stash(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda: "n")

    restored = hermes_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=True)

    assert restored is False
    assert calls == []
    out = capsys.readouterr().out
    assert "Restore local changes now? [Y/n]" in out
    assert "Your changes are still preserved in git stash." in out
    assert "git stash apply abc123" in out


def test_restore_stashed_changes_applies_without_prompt_when_disabled(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="applied\n", stderr="", returncode=0)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "list"]:
            return SimpleNamespace(stdout="stash@{0} abc123\n", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "drop"]:
            return SimpleNamespace(stdout="dropped\n", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    restored = hermes_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=False)

    assert restored is True
    assert calls[0][0] == ["git", "stash", "apply", "abc123"]
    assert calls[1][0] == ["git", "diff", "--name-only", "--diff-filter=U"]
    assert calls[2][0] == ["git", "stash", "list", "--format=%gd %H"]
    assert calls[3][0] == ["git", "stash", "drop", "stash@{0}"]
    assert "Restore local changes now?" not in capsys.readouterr().out



def test_print_stash_cleanup_guidance_with_selector(capsys):
    hermes_main._print_stash_cleanup_guidance("abc123", "stash@{2}")

    out = capsys.readouterr().out
    assert "Check `git status` first" in out
    assert "git stash list --format='%gd %H %s'" in out
    assert "git stash drop stash@{2}" in out



def test_restore_stashed_changes_keeps_going_when_stash_entry_cannot_be_resolved(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="applied\n", stderr="", returncode=0)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "list"]:
            return SimpleNamespace(stdout="stash@{0} def456\n", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    restored = hermes_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=False)

    assert restored is True
    assert calls[0] == (["git", "stash", "apply", "abc123"], {"cwd": tmp_path, "capture_output": True, "text": True})
    assert calls[1] == (["git", "diff", "--name-only", "--diff-filter=U"], {"cwd": tmp_path, "capture_output": True, "text": True})
    assert calls[2] == (["git", "stash", "list", "--format=%gd %H"], {"cwd": tmp_path, "capture_output": True, "text": True, "check": True})
    out = capsys.readouterr().out
    assert "couldn't find the stash entry to drop" in out
    assert "stash was left in place" in out
    assert "Check `git status` first" in out
    assert "git stash list --format='%gd %H %s'" in out
    assert "Look for commit abc123" in out



def test_restore_stashed_changes_keeps_going_when_drop_fails(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="applied\n", stderr="", returncode=0)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "list"]:
            return SimpleNamespace(stdout="stash@{0} abc123\n", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "drop"]:
            return SimpleNamespace(stdout="", stderr="drop failed\n", returncode=1)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    restored = hermes_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=False)

    assert restored is True
    assert calls[3][0] == ["git", "stash", "drop", "stash@{0}"]
    out = capsys.readouterr().out
    assert "couldn't drop the saved stash entry" in out
    assert "drop failed" in out
    assert "Check `git status` first" in out
    assert "git stash list --format='%gd %H %s'" in out
    assert "git stash drop stash@{0}" in out


def test_restore_stashed_changes_always_resets_on_conflict(monkeypatch, tmp_path, capsys):
    """Conflicts always auto-reset (no prompt) and return False, even interactively.

    Leaving conflict markers in source files makes hermes unrunnable (SyntaxError).
    The stash is preserved for manual recovery; cmd_update continues normally.
    """
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="conflict output\n", stderr="conflict stderr\n", returncode=1)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="hermes_cli/main.py\n", stderr="", returncode=0)
        if cmd[1:3] == ["reset", "--hard"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda: "y")

    result = hermes_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=True)

    assert result is False
    out = capsys.readouterr().out
    assert "Conflicted files:" in out
    assert "hermes_cli/main.py" in out
    assert "stashed changes are preserved" in out
    assert "Working tree reset to clean state" in out
    assert "git stash apply abc123" in out
    reset_calls = [c for c, _ in calls if c[1:3] == ["reset", "--hard"]]
    assert len(reset_calls) == 1


def test_restore_stashed_changes_auto_resets_non_interactive(monkeypatch, tmp_path, capsys):
    """Non-interactive mode auto-resets without prompting and returns False
    instead of sys.exit(1) so the update can continue (gateway /update path)."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="applied\n", stderr="", returncode=0)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="cli.py\n", stderr="", returncode=0)
        if cmd[1:3] == ["reset", "--hard"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    result = hermes_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=False)

    assert result is False
    out = capsys.readouterr().out
    assert "Working tree reset to clean state" in out
    reset_calls = [c for c, _ in calls if c[1:3] == ["reset", "--hard"]]
    assert len(reset_calls) == 1


def test_stash_local_changes_if_needed_raises_when_stash_ref_missing(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        if cmd[-2:] == ["status", "--porcelain"]:
            return SimpleNamespace(stdout=" M hermes_cli/main.py\n", returncode=0)
        if cmd[-2:] == ["ls-files", "--unmerged"]:
            return SimpleNamespace(stdout="", returncode=0)
        if cmd[1:4] == ["stash", "push", "--include-untracked"]:
            return SimpleNamespace(stdout="Saved working directory\n", returncode=0)
        if cmd[-3:] == ["rev-parse", "--verify", "refs/stash"]:
            raise CalledProcessError(returncode=128, cmd=cmd)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    with pytest.raises(CalledProcessError):
        hermes_main._stash_local_changes_if_needed(["git"], Path(tmp_path))


# ---------------------------------------------------------------------------
# Update uses .[all] with fallback to .
# ---------------------------------------------------------------------------

def _setup_update_mocks(monkeypatch, tmp_path):
    """Common setup for cmd_update tests."""
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hermes_main, "_stash_local_changes_if_needed", lambda *a, **kw: None)
    monkeypatch.setattr(hermes_main, "_restore_stashed_changes", lambda *a, **kw: True)
    monkeypatch.setattr("hermes_cli.config.get_missing_env_vars", lambda required_only=True: [])
    monkeypatch.setattr("hermes_cli.config.get_missing_config_fields", lambda: [])
    monkeypatch.setattr("hermes_cli.config.check_config_version", lambda: (5, 5))
    monkeypatch.setattr("hermes_cli.config.migrate_config", lambda **kw: {"env_added": [], "config_added": []})


def _install_fake_update_surface_modules(monkeypatch, calls):
    skills_mod = ModuleType("tools.skills_sync")

    def fake_sync_skills(quiet=True):
        calls.append("skills")
        return {"copied": [], "updated": [], "user_modified": [], "cleaned": []}

    skills_mod.sync_skills = fake_sync_skills
    monkeypatch.setitem(hermes_main.sys.modules, "tools.skills_sync", skills_mod)

    profiles_mod = ModuleType("hermes_cli.profiles")
    profiles_mod.get_active_profile_name = lambda: "default"
    profiles_mod.list_profiles = lambda: [
        SimpleNamespace(name="default", path=Path("/tmp/default")),
        SimpleNamespace(name="work", path=Path("/tmp/work")),
    ]

    def fake_seed_profile_skills(path, quiet=True):
        calls.append("profile_skills")
        return {"copied": [], "updated": [], "user_modified": []}

    profiles_mod.seed_profile_skills = fake_seed_profile_skills
    monkeypatch.setitem(hermes_main.sys.modules, "hermes_cli.profiles", profiles_mod)

    honcho_mod = ModuleType("plugins.memory.honcho.cli")

    def fake_sync_honcho_profiles_quiet():
        calls.append("honcho")
        return 0

    honcho_mod.sync_honcho_profiles_quiet = fake_sync_honcho_profiles_quiet
    monkeypatch.setitem(hermes_main.sys.modules, "plugins.memory.honcho.cli", honcho_mod)


def test_cmd_update_retries_optional_extras_individually_when_all_fails(monkeypatch, tmp_path, capsys):
    """When .[all] fails, update should keep base deps and retry extras individually."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(hermes_main, "_load_installable_optional_extras", lambda: ["matrix", "mcp"])

    recorded = []

    def fake_run(cmd, **kwargs):
        recorded.append(cmd)
        if cmd == ["git", "status", "--porcelain"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd == ["git", "ls-files", "--unmerged"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd == ["git", "fetch", "origin"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(stdout="main\n", stderr="", returncode=0)
        if cmd == ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"]:
            return SimpleNamespace(stdout="0\t1\n", stderr="", returncode=0)
        if cmd == ["git", "rev-list", "HEAD..origin/main", "--count"]:
            return SimpleNamespace(stdout="1\n", stderr="", returncode=0)
        if cmd == ["git", "pull", "origin", "main"]:
            return SimpleNamespace(stdout="Updating\n", stderr="", returncode=0)
        if cmd == ["/usr/bin/uv", "pip", "install", "-e", ".[all]", "--quiet"]:
            raise CalledProcessError(returncode=1, cmd=cmd)
        if cmd == ["/usr/bin/uv", "pip", "install", "-e", ".", "--quiet"]:
            return SimpleNamespace(returncode=0)
        if cmd == ["/usr/bin/uv", "pip", "install", "-e", ".[matrix]", "--quiet"]:
            raise CalledProcessError(returncode=1, cmd=cmd)
        if cmd == ["/usr/bin/uv", "pip", "install", "-e", ".[mcp]", "--quiet"]:
            return SimpleNamespace(returncode=0)
        # Catch-all must include stdout/stderr so consumers that parse
        # output (e.g. the dashboard-restart `ps -A` scan added in the
        # updater) don't crash on AttributeError.
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    hermes_main.cmd_update(SimpleNamespace())

    install_cmds = [c for c in recorded if "pip" in c and "install" in c]
    assert install_cmds == [
        ["/usr/bin/uv", "pip", "install", "-e", ".[all]", "--quiet"],
        ["/usr/bin/uv", "pip", "install", "-e", ".", "--quiet"],
        ["/usr/bin/uv", "pip", "install", "-e", ".[matrix]", "--quiet"],
        ["/usr/bin/uv", "pip", "install", "-e", ".[mcp]", "--quiet"],
    ]

    out = capsys.readouterr().out
    assert "retrying extras individually" in out
    assert "Reinstalled optional extras individually: mcp" in out
    assert "Skipped optional extras that still failed: matrix" in out


def test_cmd_update_succeeds_with_extras(monkeypatch, tmp_path):
    """When .[all] succeeds, no fallback should be attempted."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    recorded = []

    def fake_run(cmd, **kwargs):
        recorded.append(cmd)
        if cmd == ["git", "status", "--porcelain"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd == ["git", "ls-files", "--unmerged"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd == ["git", "fetch", "origin"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(stdout="main\n", stderr="", returncode=0)
        if cmd == ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"]:
            return SimpleNamespace(stdout="0\t1\n", stderr="", returncode=0)
        if cmd == ["git", "rev-list", "HEAD..origin/main", "--count"]:
            return SimpleNamespace(stdout="1\n", stderr="", returncode=0)
        if cmd == ["git", "pull", "origin", "main"]:
            return SimpleNamespace(stdout="Updating\n", stderr="", returncode=0)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    hermes_main.cmd_update(SimpleNamespace())

    install_cmds = [c for c in recorded if "pip" in c and "install" in c]
    assert len(install_cmds) == 1
    assert ".[all]" in install_cmds[0]


# ---------------------------------------------------------------------------
# Raw update safety: divergence and failed fast-forward abort
# ---------------------------------------------------------------------------

def _make_update_side_effect(
    current_branch="main",
    commit_count="3",
    ahead_behind="0\t3",
    dirty_status="",
    unmerged="",
    ff_only_fails=False,
    reset_fails=False,
    rev_list_fails=False,
    malformed_ahead_behind=None,
    preflight_fails_at=None,
    fetch_fails=False,
    fetch_stderr="",
):
    """Build a subprocess.run side_effect for cmd_update tests."""
    recorded = []

    def side_effect(cmd, **kwargs):
        recorded.append(cmd)
        joined = " ".join(str(c) for c in cmd)
        if "status --porcelain" in joined:
            if preflight_fails_at == "status":
                raise CalledProcessError(returncode=128, cmd=cmd, stderr="fatal: status failed")
            return SimpleNamespace(stdout=dirty_status, stderr="", returncode=0)
        if "ls-files --unmerged" in joined:
            if preflight_fails_at == "ls-files":
                raise CalledProcessError(returncode=128, cmd=cmd, stderr="fatal: index failed")
            return SimpleNamespace(stdout=unmerged, stderr="", returncode=0)
        if "fetch" in joined and "origin" in joined:
            if fetch_fails:
                return SimpleNamespace(stdout="", stderr=fetch_stderr, returncode=128)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if "rev-parse" in joined and "--abbrev-ref" in joined:
            if preflight_fails_at == "rev-parse":
                raise CalledProcessError(returncode=128, cmd=cmd, stderr="fatal: not a branch")
            return SimpleNamespace(stdout=f"{current_branch}\n", stderr="", returncode=0)
        if "checkout" in joined and "main" in joined:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if "rev-list --left-right --count HEAD...origin/main" in joined:
            if rev_list_fails:
                raise CalledProcessError(
                    returncode=128,
                    cmd=cmd,
                    stderr="fatal: ambiguous argument 'HEAD...origin/main'",
                )
            if malformed_ahead_behind is not None:
                return SimpleNamespace(stdout=malformed_ahead_behind, stderr="", returncode=0)
            return SimpleNamespace(stdout=f"{ahead_behind}\n", stderr="", returncode=0)
        if "rev-list" in joined:
            return SimpleNamespace(stdout=f"{commit_count}\n", stderr="", returncode=0)
        if "--ff-only" in joined:
            if ff_only_fails:
                return SimpleNamespace(
                    stdout="",
                    stderr="fatal: Not possible to fast-forward, aborting.\n",
                    returncode=128,
                )
            return SimpleNamespace(stdout="Updating abc..def\n", stderr="", returncode=0)
        if "reset" in joined and "--hard" in joined:
            if reset_fails:
                return SimpleNamespace(stdout="", stderr="error: unable to write\n", returncode=1)
            return SimpleNamespace(stdout="HEAD is now at abc123\n", stderr="", returncode=0)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return side_effect, recorded


def test_cmd_update_aborts_without_reset_or_side_effects_when_diverged(monkeypatch, tmp_path, capsys):
    """Local-ahead or ahead+behind state must abort before pull/reset/deps."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(
        hermes_main,
        "_install_python_dependencies_with_optional_fallback",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("dependencies should not install")),
    )
    monkeypatch.setattr(
        hermes_main,
        "_update_node_dependencies",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("node deps should not update")),
    )
    monkeypatch.setattr(
        hermes_main,
        "_build_web_ui",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("web UI should not build")),
    )

    side_effect, recorded = _make_update_side_effect(ahead_behind="1\t96")
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    reset_calls = [c for c in recorded if "reset" in c and "--hard" in c]
    pull_calls = [c for c in recorded if "pull" in c]
    assert reset_calls == []
    assert pull_calls == []

    out = capsys.readouterr().out
    assert "diverged" in out or "local commit" in out


def test_cmd_update_aborts_on_local_ahead_only_without_side_effects(monkeypatch, tmp_path, capsys):
    """Local-ahead-only state is blocked before pull/install/sync/restart."""
    _setup_update_mocks(monkeypatch, tmp_path)
    late_calls = []
    _install_fake_update_surface_modules(monkeypatch, late_calls)
    monkeypatch.setattr(
        hermes_main,
        "_install_python_dependencies_with_optional_fallback",
        lambda *a, **kw: late_calls.append("deps"),
    )
    monkeypatch.setattr(hermes_main, "_update_node_dependencies", lambda: late_calls.append("node"))
    monkeypatch.setattr(hermes_main, "_build_web_ui", lambda *_: late_calls.append("build"))
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: late_calls.append("smoke"))

    side_effect, recorded = _make_update_side_effect(ahead_behind="1\t0")
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    assert [c for c in recorded if "pull" in c] == []
    assert late_calls == []
    out = capsys.readouterr().out
    assert "ahead 1" in out
    assert "behind 0" in out


def test_cmd_update_aborts_on_ahead_and_behind_divergence_with_clear_message(
    monkeypatch, tmp_path, capsys
):
    """Lock the high-risk ahead+behind state: divergence must never update."""
    _setup_update_mocks(monkeypatch, tmp_path)
    side_effect, recorded = _make_update_side_effect(ahead_behind="1\t96")
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    assert [c for c in recorded if "reset" in c] == []
    assert [c for c in recorded if "pull" in c] == []
    out = capsys.readouterr().out
    assert "ahead 1" in out
    assert "behind 96" in out
    assert "diverged" in out


def test_cmd_update_aborts_without_reset_when_ff_only_fails(monkeypatch, tmp_path, capsys):
    """A failed ff-only pull is a hard stop and never falls back to reset --hard."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    late_calls = []
    _install_fake_update_surface_modules(monkeypatch, late_calls)
    monkeypatch.setattr(
        hermes_main,
        "_install_python_dependencies_with_optional_fallback",
        lambda *a, **kw: late_calls.append("deps"),
    )
    monkeypatch.setattr(hermes_main, "_update_node_dependencies", lambda: late_calls.append("node"))
    monkeypatch.setattr(hermes_main, "_build_web_ui", lambda *_: late_calls.append("build"))
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: late_calls.append("smoke"))
    monkeypatch.setattr("hermes_cli.config.get_missing_env_vars", lambda required_only=True: late_calls.append("config_env") or [])
    monkeypatch.setattr("hermes_cli.config.get_missing_config_fields", lambda: late_calls.append("config_fields") or [])
    monkeypatch.setattr("hermes_cli.config.check_config_version", lambda: late_calls.append("config_version") or (5, 5))

    side_effect, recorded = _make_update_side_effect(ff_only_fails=True)
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    reset_calls = [c for c in recorded if "reset" in c and "--hard" in c]
    install_calls = [c for c in recorded if "pip" in c and "install" in c]
    assert reset_calls == []
    assert install_calls == []
    assert late_calls == []

    out = capsys.readouterr().out
    assert "Fast-forward not possible" in out


def test_cmd_update_rev_list_failure_aborts_cleanly_without_late_side_effects(monkeypatch, tmp_path, capsys):
    _setup_update_mocks(monkeypatch, tmp_path)
    late_calls = []
    _install_fake_update_surface_modules(monkeypatch, late_calls)
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: late_calls.append("smoke"))

    side_effect, recorded = _make_update_side_effect(rev_list_fails=True)
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    assert [c for c in recorded if "pull" in c] == []
    assert late_calls == []
    out = capsys.readouterr().out
    assert "could not compare local branch with origin/main" in out


@pytest.mark.parametrize("malformed", ["nonsense\n", "0\n", "0\tone\n"])
def test_cmd_update_malformed_rev_list_output_aborts_cleanly(monkeypatch, tmp_path, capsys, malformed):
    _setup_update_mocks(monkeypatch, tmp_path)
    late_calls = []
    _install_fake_update_surface_modules(monkeypatch, late_calls)
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: late_calls.append("smoke"))

    side_effect, recorded = _make_update_side_effect(malformed_ahead_behind=malformed)
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    assert [c for c in recorded if "pull" in c] == []
    assert late_calls == []
    out = capsys.readouterr().out
    assert "could not compare local branch with origin/main" in out


@pytest.mark.parametrize("failed_command", ["ls-files", "status", "rev-parse"])
def test_cmd_update_preflight_git_failure_aborts_cleanly_before_fetch(monkeypatch, tmp_path, capsys, failed_command):
    _setup_update_mocks(monkeypatch, tmp_path)
    late_calls = []
    _install_fake_update_surface_modules(monkeypatch, late_calls)
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: late_calls.append("smoke"))

    side_effect, recorded = _make_update_side_effect(preflight_fails_at=failed_command)
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    assert [c for c in recorded if "fetch" in c] == []
    assert [c for c in recorded if "pull" in c] == []
    assert late_calls == []
    out = capsys.readouterr().out
    assert "could not inspect local git state" in out


def test_cmd_update_no_reset_when_ff_only_succeeds(monkeypatch, tmp_path):
    """When --ff-only succeeds, no reset is attempted."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    side_effect, recorded = _make_update_side_effect()
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    hermes_main.cmd_update(SimpleNamespace())

    reset_calls = [c for c in recorded if "reset" in c and "--hard" in c]
    assert len(reset_calls) == 0


# ---------------------------------------------------------------------------
# Non-main branch must abort instead of auto-checkout
# ---------------------------------------------------------------------------

def test_cmd_update_switches_to_main_from_feature_branch(monkeypatch, tmp_path, capsys):
    """Raw update should abort on a non-main branch instead of auto-checkout."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    side_effect, recorded = _make_update_side_effect(current_branch="fix/something")
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    checkout_calls = [c for c in recorded if "checkout" in c and "main" in c]
    assert checkout_calls == []

    out = capsys.readouterr().out
    assert "fix/something" in out
    assert "main" in out


def test_cmd_update_switches_to_main_from_detached_head(monkeypatch, tmp_path, capsys):
    """Raw update should abort from detached HEAD instead of auto-checkout."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    side_effect, recorded = _make_update_side_effect(current_branch="HEAD")
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    checkout_calls = [c for c in recorded if "checkout" in c and "main" in c]
    assert checkout_calls == []

    out = capsys.readouterr().out
    assert "detached HEAD" in out


def test_cmd_update_aborts_dirty_tree_before_backup_fetch_or_stash(monkeypatch, tmp_path, capsys):
    """Default raw update must not auto-stash or create backups before preflight."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(
        hermes_main,
        "_run_pre_update_backup",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("backup should not run")),
    )
    monkeypatch.setattr(
        hermes_main,
        "_stash_local_changes_if_needed",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("auto-stash should not run")),
    )

    side_effect, recorded = _make_update_side_effect(
        dirty_status=" M hermes_cli/main.py\n",
    )
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    fetch_calls = [c for c in recorded if "fetch" in c]
    stash_calls = [c for c in recorded if "stash" in c]
    assert fetch_calls == []
    assert stash_calls == []
    out = capsys.readouterr().out
    assert "dirty" in out or "uncommitted" in out


def test_cmd_update_aborts_unmerged_index_without_reset_or_stash(monkeypatch, tmp_path, capsys):
    """Raw update must not clear conflict state with reset or hide it with stash."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(
        hermes_main,
        "_stash_local_changes_if_needed",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("auto-stash should not run")),
    )

    side_effect, recorded = _make_update_side_effect(
        unmerged="100644 abc 1\thermes_cli/main.py\n",
    )
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    reset_calls = [c for c in recorded if "reset" in c]
    stash_calls = [c for c in recorded if "stash" in c]
    assert reset_calls == []
    assert stash_calls == []
    out = capsys.readouterr().out
    assert "unmerged" in out or "conflict" in out


def test_cmd_update_no_checkout_when_already_on_main(monkeypatch, tmp_path):
    """When already on main, no checkout is needed."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    side_effect, recorded = _make_update_side_effect()
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    hermes_main.cmd_update(SimpleNamespace())

    checkout_calls = [c for c in recorded if "checkout" in c]
    assert len(checkout_calls) == 0


def test_cmd_update_success_path_runs_smoke_before_profile_config_side_effects(monkeypatch, tmp_path):
    """Successful raw update gates profile/config side effects behind smoke."""
    _setup_update_mocks(monkeypatch, tmp_path)
    calls = []
    _install_fake_update_surface_modules(monkeypatch, calls)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(
        hermes_main,
        "_install_python_dependencies_with_optional_fallback",
        lambda *a, **kw: calls.append("deps"),
    )
    monkeypatch.setattr(hermes_main, "_update_node_dependencies", lambda: calls.append("node"))
    monkeypatch.setattr(hermes_main, "_build_web_ui", lambda *_: calls.append("build"))
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: calls.append("smoke"))
    monkeypatch.setattr("hermes_cli.config.get_missing_env_vars", lambda required_only=True: calls.append("config_env") or [])
    monkeypatch.setattr("hermes_cli.config.get_missing_config_fields", lambda: calls.append("config_fields") or [])
    monkeypatch.setattr("hermes_cli.config.check_config_version", lambda: calls.append("config_version") or (5, 5))

    side_effect, _ = _make_update_side_effect()
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    hermes_main.cmd_update(SimpleNamespace())

    assert calls.index("deps") < calls.index("node") < calls.index("build")
    assert calls.index("build") < calls.index("smoke")
    assert calls.index("smoke") < calls.index("skills")
    assert calls.index("smoke") < calls.index("profile_skills")
    assert calls.index("smoke") < calls.index("honcho")
    assert calls.index("smoke") < calls.index("config_env")


def test_cmd_update_smoke_failure_blocks_profile_config_and_gateway_side_effects(monkeypatch, tmp_path, capsys):
    """No smoke pass means no skill/profile/Honcho/config/gateway side effects."""
    _setup_update_mocks(monkeypatch, tmp_path)
    calls = []
    _install_fake_update_surface_modules(monkeypatch, calls)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(
        hermes_main,
        "_install_python_dependencies_with_optional_fallback",
        lambda *a, **kw: calls.append("deps"),
    )
    monkeypatch.setattr(hermes_main, "_update_node_dependencies", lambda: calls.append("node"))
    monkeypatch.setattr(hermes_main, "_build_web_ui", lambda *_: calls.append("build"))

    def fail_smoke():
        calls.append("smoke")
        print("✗ Post-update smoke check failed: test failure")
        print("  Gateway restart skipped.")
        raise SystemExit(1)

    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", fail_smoke)
    monkeypatch.setattr("hermes_cli.config.get_missing_env_vars", lambda required_only=True: calls.append("config_env") or [])
    monkeypatch.setattr("hermes_cli.config.get_missing_config_fields", lambda: calls.append("config_fields") or [])
    monkeypatch.setattr("hermes_cli.config.check_config_version", lambda: calls.append("config_version") or (5, 5))

    side_effect, _ = _make_update_side_effect()
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace(gateway=True))

    assert calls == ["deps", "node", "build", "smoke"]
    assert not (tmp_path / ".update_exit_code").exists()
    assert "Gateway restart skipped" in capsys.readouterr().out


def test_raw_update_smoke_check_is_local_and_does_not_spawn_version_or_git(monkeypatch, tmp_path):
    """Smoke must use a fresh local Python process without git/version side effects."""
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", tmp_path)
    calls = []

    def smoke_subprocess(cmd, **kwargs):
        calls.append(cmd)
        joined = " ".join(str(part) for part in cmd)
        if "git" in joined or "fetch" in joined or "pull" in joined or "hermes_cli.main version" in joined:
            raise AssertionError(f"forbidden smoke subprocess: {cmd}")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(hermes_main.subprocess, "run", smoke_subprocess)

    hermes_main._run_raw_update_smoke_check()

    assert len(calls) == 1
    assert calls[0][0] == hermes_main.sys.executable
    assert "-c" in calls[0]
    assert "hermes_cli.main" in calls[0][calls[0].index("-c") + 1]


def test_raw_update_smoke_check_fresh_process_failure_aborts(monkeypatch, capsys):
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", Path.cwd())

    def failing_subprocess(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="fresh import failed")

    monkeypatch.setattr(hermes_main.subprocess, "run", failing_subprocess)

    with pytest.raises(SystemExit, match="1"):
        hermes_main._run_raw_update_smoke_check()

    out = capsys.readouterr().out
    assert "Post-update smoke check failed" in out
    assert "fresh import failed" in out


# ---------------------------------------------------------------------------
# Fetch failure — friendly error messages
# ---------------------------------------------------------------------------

def test_cmd_update_network_error_shows_friendly_message(monkeypatch, tmp_path, capsys):
    """Network failures during fetch show a user-friendly message."""
    _setup_update_mocks(monkeypatch, tmp_path)

    side_effect, _ = _make_update_side_effect(
        fetch_fails=True,
        fetch_stderr="fatal: unable to access 'https://...': Could not resolve host: github.com",
    )
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    out = capsys.readouterr().out
    assert "Network error" in out


def test_cmd_update_auth_error_shows_friendly_message(monkeypatch, tmp_path, capsys):
    """Auth failures during fetch show a user-friendly message."""
    _setup_update_mocks(monkeypatch, tmp_path)

    side_effect, _ = _make_update_side_effect(
        fetch_fails=True,
        fetch_stderr="fatal: Authentication failed for 'https://...'",
    )
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    out = capsys.readouterr().out
    assert "Authentication failed" in out


# ---------------------------------------------------------------------------
# reset --hard must not be part of raw update failure handling
# ---------------------------------------------------------------------------

def test_cmd_update_does_not_restore_stash_after_failed_code_update(monkeypatch, tmp_path, capsys):
    """Failed code update has no stash restore path because raw update never auto-stashes."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(
        hermes_main,
        "_stash_local_changes_if_needed",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("auto-stash should not run")),
    )
    restore_calls = []
    monkeypatch.setattr(
        hermes_main, "_restore_stashed_changes",
        lambda *a, **kw: restore_calls.append(1) or True,
    )

    side_effect, recorded = _make_update_side_effect(ff_only_fails=True, reset_fails=True)
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        hermes_main.cmd_update(SimpleNamespace())

    reset_calls = [c for c in recorded if "reset" in c and "--hard" in c]
    assert restore_calls == []
    assert reset_calls == []

    out = capsys.readouterr().out
    assert "Fast-forward not possible" in out


def test_cmd_update_success_path_never_calls_legacy_stash_helpers(monkeypatch, tmp_path):
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(
        hermes_main,
        "_stash_local_changes_if_needed",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("legacy stash helper called")),
    )
    monkeypatch.setattr(
        hermes_main,
        "_restore_stashed_changes",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("legacy restore helper called")),
    )
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: None)

    side_effect, _ = _make_update_side_effect()
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    hermes_main.cmd_update(SimpleNamespace(no_skills=True))


def test_cmd_update_skips_fork_sync_and_never_pushes(monkeypatch, tmp_path):
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(hermes_main, "_get_origin_url", lambda *_: "https://github.com/example/hermes-agent-fork.git")
    monkeypatch.setattr(hermes_main, "_is_fork", lambda *_: True)
    monkeypatch.setattr(
        hermes_main,
        "_sync_with_upstream_if_needed",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("fork sync should not run")),
    )
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: None)

    side_effect, recorded = _make_update_side_effect()
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    hermes_main.cmd_update(SimpleNamespace(no_skills=True))

    assert [c for c in recorded if "push" in c] == []


def test_update_skills_sync_enabled_by_default(monkeypatch):
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {})

    assert hermes_main._should_sync_update_skills(SimpleNamespace()) is True


def test_update_skills_sync_disabled_by_config(monkeypatch):
    monkeypatch.setattr(
        hermes_config,
        "load_config",
        lambda: {"updates": {"sync_skills": False}},
    )

    assert hermes_main._should_sync_update_skills(SimpleNamespace()) is False


def test_update_skills_sync_disabled_by_cli_even_when_config_enabled(monkeypatch):
    monkeypatch.setattr(
        hermes_config,
        "load_config",
        lambda: {"updates": {"sync_skills": True}},
    )

    assert hermes_main._should_sync_update_skills(SimpleNamespace(no_skills=True)) is False


def test_cmd_update_config_false_skips_bundled_and_profile_skill_sync(monkeypatch, tmp_path):
    _setup_update_mocks(monkeypatch, tmp_path)
    calls = []
    _install_fake_update_surface_modules(monkeypatch, calls)
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"updates": {"sync_skills": False}})
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: calls.append("smoke"))

    side_effect, _ = _make_update_side_effect()
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    hermes_main.cmd_update(SimpleNamespace())

    assert "smoke" in calls
    assert "skills" not in calls
    assert "profile_skills" not in calls
    assert "honcho" in calls


def test_cmd_update_no_skills_flag_skips_skill_sync_even_when_config_enabled(monkeypatch, tmp_path):
    _setup_update_mocks(monkeypatch, tmp_path)
    calls = []
    _install_fake_update_surface_modules(monkeypatch, calls)
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"updates": {"sync_skills": True}})
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: calls.append("smoke"))

    side_effect, _ = _make_update_side_effect()
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    hermes_main.cmd_update(SimpleNamespace(no_skills=True))

    assert "smoke" in calls
    assert "skills" not in calls
    assert "profile_skills" not in calls
    assert "honcho" in calls


def test_cmd_update_syncs_bundled_and_profile_skills_after_smoke_when_enabled(monkeypatch, tmp_path):
    _setup_update_mocks(monkeypatch, tmp_path)
    calls = []
    _install_fake_update_surface_modules(monkeypatch, calls)
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"updates": {"sync_skills": True}})
    monkeypatch.setattr(hermes_main, "_run_raw_update_smoke_check", lambda: calls.append("smoke"))

    side_effect, _ = _make_update_side_effect()
    monkeypatch.setattr(hermes_main.subprocess, "run", side_effect)

    hermes_main.cmd_update(SimpleNamespace())

    assert calls.index("smoke") < calls.index("skills")
    assert calls.index("smoke") < calls.index("profile_skills")


def test_update_parser_sets_no_skills_flag(monkeypatch):
    captured = {}

    def fake_cmd_update(args):
        captured["no_skills"] = args.no_skills

    monkeypatch.setattr(hermes_main, "cmd_update", fake_cmd_update)
    monkeypatch.setattr(hermes_main.sys, "argv", ["hermes", "update", "--no-skills"])

    hermes_main.main()

    assert captured["no_skills"] is True
