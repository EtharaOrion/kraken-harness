def test_patch_pod_0006_strategic(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: ppo-0006\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "pod", "ppo-0006", "-n", "default", "-p", '{"metadata":{"labels":{"lane":"a6"}}}')
    assert result.returncode == 0, result.stderr
    assert "ppo-0006" in result.stdout
