def test_delete_priorityclass_0027_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: scheduling.k8s.io/v1\nkind: PriorityClass\nmetadata:\n  name: dpr-0027\nvalue: 1000\ndescription: bulk-generated\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "priorityclass", "dpr-0027", "-n", "default")
    assert result.returncode == 0, result.stderr
