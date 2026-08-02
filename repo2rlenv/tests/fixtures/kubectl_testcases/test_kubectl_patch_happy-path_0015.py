def test_patch_secret_0015_strategic(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: pse-0015\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "secret", "pse-0015", "-n", "default", "-p", '{"metadata":{"labels":{"lane":"a15"}}}')
    assert result.returncode == 0, result.stderr
    assert "pse-0015" in result.stdout
