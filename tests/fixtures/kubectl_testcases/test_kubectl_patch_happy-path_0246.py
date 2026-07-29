def test_patch_pod_0246_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: pipo-0246\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "pod", "pipo-0246", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x246"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "pod", "pipo-0246", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x246"}}}')
    assert r2.returncode == 0, r2.stderr
