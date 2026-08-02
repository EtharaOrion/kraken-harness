def test_apply_invalid_apiversion_returns_error(cli, tmp_path):
    manifest = tmp_path / "bogus-kind.yaml"
    manifest.write_text(
        "apiVersion: v99/BogusKind\nkind: BogusKind\nmetadata:\n  name: bogus-apply-ne02\n  namespace: default\n"
    )
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "unable" in stderr or "no matches" in stderr or "not found" in stderr or "unknown" in stderr
