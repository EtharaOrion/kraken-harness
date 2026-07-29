def test_label_secret_0045_add_app(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: lse-0045\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "secret", "lse-0045", "app=api", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lse-0045" in result.stdout
