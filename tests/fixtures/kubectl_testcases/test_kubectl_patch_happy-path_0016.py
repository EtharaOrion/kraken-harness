def test_patch_secret_0016_merge(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: pse-0016\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "secret", "pse-0016", "-n", "default", "--type=merge", "-p", '{"metadata":{"labels":{"lane":"b16"}}}')
    assert result.returncode == 0, result.stderr
    assert "pse-0016" in result.stdout
