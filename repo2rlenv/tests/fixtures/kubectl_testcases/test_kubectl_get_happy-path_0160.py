def test_get_pods_0160_by_selector(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: gspo-0160\n  namespace: default\n  labels:\n    tier: "lbl0160"\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "pods", "-l", "tier=lbl0160", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "gspo-0160" in result.stdout
