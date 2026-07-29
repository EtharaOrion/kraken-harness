def test_patch_pod_0442_dryrun(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: pd-0442\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "pod", "pd-0442", "-n", "default", "--dry-run=client", "-p", '{"metadata":{"annotations":{"note":"n442"}}}')
    assert result.returncode == 0, result.stderr
    assert "pd-0442" in result.stdout
