def test_patch_pod_0405_dryrun(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: pd-0405\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "pod", "pd-0405", "-n", "default", "--dry-run=client", "-p", '{"metadata":{"annotations":{"note":"n405"}}}')
    assert result.returncode == 0, result.stderr
    assert "pd-0405" in result.stdout
