def test_apply_pod_0091_view_last_applied(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: alpo-0091\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = cli("apply", "-f", str(manifest))
    assert seed.returncode == 0, seed.stderr
    result = cli("apply", "view-last-applied", "pod", "alpo-0091", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "alpo-0091" in result.stdout
